"""Link budget, bitrate selection and the data budget."""

from __future__ import annotations

import numpy as np
import pytest

from hs2sim import comms
from hs2sim.config import MissionConfig


def test_usb2_frame_rate_ceiling():
    cfg = MissionConfig()
    fps = comms.usb2_max_fps(cfg)
    payload = cfg.payload
    raw = payload.image_width_px * payload.image_height_px * payload.bits_per_pixel // 8
    expected = (payload.usb2_raw_mbps * 1e6 * payload.usb2_bulk_efficiency
                / (raw * 8) / payload.n_cameras)
    assert fps == pytest.approx(expected)
    # Two 1.31 MB frames over a 480 Mb/s bus: order 10 experiments/s, not 1000.
    assert 5.0 < fps < 30.0


def test_image_size_matches_supplied_budget():
    """1280 x 1024 x 8 bpp with 50 % compression is the budget's 655,360 B."""
    cfg = MissionConfig()
    assert comms.image_bytes(cfg) == 655360


def test_free_space_loss_matches_budget_value():
    """The budget quotes -163.9 dB at 1695.1 km and 2.2 GHz."""
    loss = comms.free_space_loss_db(np.array([1695.1e3]), 2.2e9)[0]
    assert loss == pytest.approx(163.9, abs=0.15)


def test_link_margin_improves_with_leaf_space_ground_station():
    """Leaf Line's 12.8 dB/K G/T should beat the budget's dish by ~13 dB."""
    cfg = MissionConfig()
    margin = comms.link_margin_db(cfg, 1695.1e3, 9600.0)
    # The spreadsheet closed at 6.03 dB with 10 kbps and a -0.6 dB/K station,
    # while carrying 10 dB of pointing loss. With a better station and a
    # controlled attitude there should be a lot more room than that.
    assert margin > 20.0


def test_bitrate_selection_is_monotonic_in_range():
    cfg = MissionConfig()
    near = comms.achievable_bitrate_bps(cfg, np.array([500e3]))[0]
    far = comms.achievable_bitrate_bps(cfg, np.array([2200e3]))[0]
    assert near >= far > 0


# ---------------------------------------------------------------------------
# Fixed-rate GFSK mode
# ---------------------------------------------------------------------------

def test_fixed_rate_mode_is_off_by_default():
    cfg = MissionConfig()
    assert not comms.fixed_rate_enabled(cfg)
    assert comms.eb_n0_required_db(cfg) == pytest.approx(
        float(cfg.radio.eb_n0_required_db))
    assert comms.candidate_bitrates_kbps(cfg) == [
        float(r) for r in cfg.radio.available_bitrates_kbps]


def test_fixed_rate_mode_uses_only_the_configured_gfsk_rate():
    cfg = MissionConfig().copy_with(**{"radio.fixed_rate.enabled": True})
    assert comms.fixed_rate_enabled(cfg)
    assert comms.candidate_bitrates_kbps(cfg) == [
        float(cfg.radio.fixed_rate.bitrate_kbps)]
    assert comms.eb_n0_required_db(cfg) == pytest.approx(
        float(cfg.radio.fixed_rate.eb_n0_required_db))

    fixed_rate_bps = float(cfg.radio.fixed_rate.bitrate_kbps) * 1e3 / float(
        cfg.radio.fec_overhead)
    close_range = np.array([500e3])
    rate = comms.achievable_bitrate_bps(cfg, close_range)[0]
    # Either the single fixed rate closes, or the link delivers nothing --
    # there is no adaptive fallback to a slower rate.
    assert rate == pytest.approx(fixed_rate_bps) or rate == 0.0


def test_fixed_rate_mode_never_exceeds_its_pinned_rate_even_when_closer():
    """A shorter range must not unlock a faster rate: there is only one."""
    cfg = MissionConfig().copy_with(**{"radio.fixed_rate.enabled": True})
    fixed_rate_bps = float(cfg.radio.fixed_rate.bitrate_kbps) * 1e3 / float(
        cfg.radio.fec_overhead)
    near = comms.achievable_bitrate_bps(cfg, np.array([500e3]))[0]
    far = comms.achievable_bitrate_bps(cfg, np.array([2200e3]))[0]
    assert near in (0.0, pytest.approx(fixed_rate_bps))
    assert far in (0.0, pytest.approx(fixed_rate_bps))


def test_fixed_rate_gfsk_requires_more_margin_than_adaptive_bpsk():
    """GFSK's non-coherent demod costs Eb/N0 relative to the BPSK default."""
    cfg = MissionConfig()
    gfsk = cfg.copy_with(**{"radio.fixed_rate.enabled": True})
    assert comms.eb_n0_required_db(gfsk) > comms.eb_n0_required_db(cfg)


def test_data_budget_scales_with_experiment_count():
    cfg = MissionConfig()
    contact = 60 * 60.0
    low = comms.data_budget(cfg, 1000.0, contact)
    high = comms.data_budget(cfg, 2000.0, contact)
    assert high.downlink_bytes_per_day > low.downlink_bytes_per_day
    # Only two images come down per day regardless of cadence.
    assert low.image_bytes_per_day == high.image_bytes_per_day


def test_max_experiments_inverts_the_data_budget():
    cfg = MissionConfig()
    contact = 60 * 60.0
    capacity = 40e6
    n = comms.max_experiments_from_downlink(cfg, capacity, contact)
    budget = comms.data_budget(cfg, n, contact)
    assert budget.downlink_bytes_per_day == pytest.approx(capacity, rel=1e-3)
