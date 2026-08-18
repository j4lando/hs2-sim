"""Link budget, bitrate selection and the data budget."""

from __future__ import annotations

import math

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


def test_the_margin_requirement_is_a_power_ratio_not_a_decibel_count():
    """"The noise floor plus 50 %" is 50 % more power, which is 1.76 dB.

    Reading it as 50 % more decibels would put a 14 dB GFSK threshold at 21 dB
    -- a *harder* requirement than the 6 dB flat margin it replaced, which is
    the opposite of what relaxing it means.
    """
    cfg = MissionConfig()
    assert float(cfg.radio.required_margin_factor) == 1.5
    assert comms.required_margin_db(cfg) == pytest.approx(
        10.0 * math.log10(1.5), abs=1e-9)
    assert comms.required_margin_db(cfg) < 2.0
    assert comms.link_threshold_db(cfg) == pytest.approx(
        comms.eb_n0_required_db(cfg) + comms.required_margin_db(cfg)
        + float(cfg.radio.implementation_loss_db))
    # Removing the factor falls back to the flat budget figure.
    flat = cfg.copy_with(**{"radio.required_margin_factor": 0.0})
    assert comms.required_margin_db(flat) == pytest.approx(
        float(cfg.radio.required_margin_db))


def test_a_looser_margin_never_closes_fewer_links():
    cfg = MissionConfig()
    strict = cfg.copy_with(**{"radio.required_margin_factor": 0.0})   # 6 dB
    ranges = np.linspace(400e3, 2000e3, 40)
    loose_rate = comms.achievable_bitrate_bps(cfg, ranges)
    strict_rate = comms.achievable_bitrate_bps(strict, ranges)
    assert np.all(loose_rate >= strict_rate)


def test_pointing_the_antenna_is_decided_by_the_link_not_by_policy():
    """Whether a contact has to be flown antenna-on-station is a budget answer.

    Turning the vehicle to put the +x patch on the station is what justifies
    the -3 dB nominal pointing loss rather than the -10 dB worst case. It also
    costs a magnetorquer manoeuvre at each end, so it is only worth doing where
    the link would not otherwise close.
    """
    cfg = MissionConfig()
    ranges = np.array([500e3, 1000e3, 1500e3])
    # At S-band with this EIRP the low-rate link closes even edge-on.
    assert np.all(comms.achievable_bitrate_bps(
        cfg, ranges, worst_case_pointing=True) > 0)
    assert not np.any(comms.downlink_needs_pointing(cfg, ranges))

    # Starve the link and the answer flips, without any policy changing.
    weak = cfg.copy_with(**{"radio.tx_power_w": 0.02,
                            "radio.tx_antenna_gain_dbi": -6.0})
    assert np.all(comms.downlink_needs_pointing(weak, ranges))


def test_margin_over_threshold_is_positive_exactly_when_the_link_closes():
    cfg = MissionConfig()
    ranges = np.linspace(400e3, 3000e3, 60)
    rate = comms.achievable_bitrate_bps(cfg, ranges)
    channel = rate * float(cfg.radio.fec_overhead)
    margin = comms.margin_over_threshold_db(cfg, ranges, channel)
    closes = rate > 0
    assert np.all(margin[closes] >= -1e-9)
    assert np.all(np.isnan(margin[~closes]))
