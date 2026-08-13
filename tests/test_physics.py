"""Checks on the parts of the model that have a known right answer.

These run without Basilisk: they exercise the geometry, view factor, link
budget and data budget maths against closed-form or hand-computed values. If
one of these fails, the corresponding number in the report is wrong.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from hs2sim import adcs, comms, exclusion, geometry, thermal
from hs2sim.config import MissionConfig
from hs2sim.environment import R_EARTH, EnvironmentResult


def make_env(n: int = 8, altitude_m: float = 415e3,
             sun_dir: np.ndarray | None = None) -> EnvironmentResult:
    """A synthetic circular-orbit environment with a fixed Sun direction."""
    r = R_EARTH + altitude_m
    angle = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pos = np.stack([r * np.cos(angle), r * np.sin(angle), np.zeros(n)], axis=1)
    vel = np.stack([-np.sin(angle), np.cos(angle), np.zeros(n)], axis=1) * 7660.0
    sun_dir = np.array([1.0, 0.0, 0.0]) if sun_dir is None else sun_dir
    sun = np.tile(sun_dir / np.linalg.norm(sun_dir) * 1.496e11, (n, 1))
    return EnvironmentResult(
        t_s=np.arange(n) * 60.0,
        r_BN_N=pos,
        v_BN_N=vel,
        r_sun_N=sun,
        shadow_factor=np.ones(n),
        b_field_N=np.tile(np.array([2e-5, 0.0, 3e-5]), (n, 1)),
        dcm_PN=np.tile(np.eye(3), (n, 1, 1)),
        station_access=np.zeros((1, n), dtype=bool),
        station_elevation=np.zeros((1, n)),
        station_range=np.full((1, n), 1e7),
        station_names=["test"],
    )


def test_earth_angular_radius_matches_geometry():
    env = make_env()
    expected = math.degrees(math.asin(R_EARTH / (R_EARTH + 415e3)))
    assert np.allclose(np.degrees(env.earth_angular_radius()), expected, atol=1e-9)
    # Sanity: from 415 km the Earth fills a ~70 deg half-cone.
    assert 69.0 < expected < 71.0


def test_view_factor_nadir_facing_equals_sin_squared_rho():
    """The closed-form check the quadrature must reproduce: F = sin^2(rho)."""
    env = make_env(n=4)
    nadir = env.nadir_unit()
    normals = nadir[:, None, :]                     # one face, pointing at Earth
    view = thermal._view_factor_to_earth(env, normals)
    rho = env.earth_angular_radius()
    assert np.allclose(view[:, 0], np.sin(rho) ** 2, rtol=2e-3)


def test_view_factor_zenith_facing_is_zero():
    env = make_env(n=4)
    normals = -env.nadir_unit()[:, None, :]         # pointing straight up
    view = thermal._view_factor_to_earth(env, normals)
    assert np.allclose(view, 0.0, atol=1e-6)


def test_view_factor_is_bounded():
    env = make_env(n=4)
    rng = np.random.default_rng(0)
    dirs = rng.normal(size=(4, 6, 3))
    dirs /= np.linalg.norm(dirs, axis=-1, keepdims=True)
    view = thermal._view_factor_to_earth(env, dirs)
    assert np.all(view >= 0.0) and np.all(view <= 1.0)


def test_orthonormal_basis_is_orthonormal():
    rng = np.random.default_rng(1)
    axis = rng.normal(size=(50, 3))
    axis /= np.linalg.norm(axis, axis=1, keepdims=True)
    u, v = geometry.orthonormal_basis(axis)
    assert np.allclose(np.sum(u * axis, axis=1), 0.0, atol=1e-12)
    assert np.allclose(np.sum(v * axis, axis=1), 0.0, atol=1e-12)
    assert np.allclose(np.sum(u * v, axis=1), 0.0, atol=1e-12)
    assert np.allclose(np.linalg.norm(u, axis=1), 1.0)
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0)


def test_experiment_pointing_produces_valid_rotations():
    """Every returned attitude must be a proper rotation matrix."""
    cfg = MissionConfig()
    env = make_env(n=12)
    result = geometry.solve_experiment_pointing(cfg, env, n_azimuth=24, n_roll=24)
    dcm = result.dcm_BN[result.feasible]
    if len(dcm) == 0:
        pytest.skip("no feasible samples in this synthetic geometry")
    identity = np.einsum("nij,nkj->nik", dcm, dcm)
    assert np.allclose(identity, np.eye(3), atol=1e-8)
    assert np.allclose(np.linalg.det(dcm), 1.0, atol=1e-8)


def test_experiment_pointing_respects_keep_out_cones():
    """Directly re-check the constraints on the solver's own answers."""
    cfg = MissionConfig()
    env = make_env(n=16)
    result = geometry.solve_experiment_pointing(cfg, env, n_azimuth=48, n_roll=48)
    if not result.feasible.any():
        pytest.skip("no feasible samples in this synthetic geometry")

    sel = result.feasible
    sun = env.sun_unit()[sel]
    nadir = env.nadir_unit()[sel]
    rho = env.earth_angular_radius()[sel]
    z_axis = result.z_axis_N[sel]
    x_axis = result.x_axis_N[sel]

    sensors = cfg.spacecraft.sensors
    z_sun_limit = math.radians(min(float(sensors.lost_camera.sun_exclusion_deg),
                                   float(sensors.star_tracker.sun_exclusion_deg)))
    z_earth_limit = math.radians(float(sensors.lost_camera.earth_exclusion_deg))
    x_sun_limit = math.radians(float(sensors.found_camera.sun_exclusion_deg))

    z_sun = geometry.angle_between(z_axis, sun)
    z_earth = geometry.angle_between(z_axis, nadir)
    x_sun = geometry.angle_between(x_axis, sun)
    x_nadir = geometry.angle_between(x_axis, nadir)

    assert np.all(z_sun > z_sun_limit - 1e-6), "Sun inside the +z keep-out"
    assert np.all(z_earth > rho + z_earth_limit - 1e-6), "Earth inside the +z keep-out"
    assert np.all(x_sun > x_sun_limit - 1e-6), "Sun inside the FOUND keep-out"
    # FOUND must be on the limb, i.e. exactly at the Earth angular radius.
    assert np.allclose(x_nadir, rho, atol=1e-6), "FOUND is not pointed at the limb"


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


# ---------------------------------------------------------------------------
# Exclusion-angle sweep
# ---------------------------------------------------------------------------

def test_exclusion_sweep_overrides_target_real_config_keys():
    """The dotted override paths must already exist in the YAML.

    ``MissionConfig.copy_with`` assigns into the target dict without checking
    that the key is there, so a typo in a path would silently create a new,
    unread key -- the sweep would run, produce a smooth-looking matrix, and be
    measuring nothing. This is the test that catches that.
    """
    cfg = MissionConfig()
    for dotted in exclusion.LOST_PATHS + (exclusion.FOUND_PATH,):
        node = cfg
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = getattr(node, part)
        assert parts[-1] in node, f"{dotted} is not a key in the config"


def test_exclusion_override_actually_changes_feasibility():
    """A much larger FOUND keep-out must reject at least as much as a small one."""
    cfg = MissionConfig()
    env = make_env(n=24)
    loose = cfg.copy_with(**{exclusion.FOUND_PATH: 20.0})
    tight = cfg.copy_with(**{exclusion.FOUND_PATH: 100.0})
    a = geometry.solve_experiment_pointing(loose, env, n_azimuth=24, n_roll=24)
    b = geometry.solve_experiment_pointing(tight, env, n_azimuth=24, n_roll=24)
    assert b.feasible.sum() <= a.feasible.sum()
    # And the tighter cone must reject *for the right reason*.
    if b.feasible.sum() < a.feasible.sum():
        assert np.any(b.reject_reason == geometry.REJECT_SUN_IN_FOUND)


def _fake_sweep() -> dict:
    """A sweep result with a known free band and a known scheduler spread."""
    lost = [20.0, 30.0, 40.0]
    found = [50.0, 60.0]
    # Rows 0 and 1 are identical -> free band up to 30 deg. Row 2 differs.
    feasible = [[0.50, 0.40], [0.50, 0.40], [0.30, 0.20]]
    # Cells sharing a feasibility disagree by 1000 images -> that is the noise.
    images = [[5000.0, 4000.0], [6000.0, 4000.0], [3000.0, 2000.0]]
    ceiling = [[f * 86400 * 0.2 * 2 for f in row] for row in feasible]
    return {
        "lost_deg": lost,
        "found_deg": found,
        "matrices": {
            "feasible_fraction": feasible,
            "images_per_day": images,
            "images_per_day_ceiling": ceiling,
        },
    }


def test_characterise_finds_the_free_band_and_the_knee():
    out = exclusion.characterise(_fake_sweep())
    assert out["lost_free_band_deg"] == 30.0
    assert out["lost_binds_above_deg"] == 40.0


def test_characterise_measures_scheduler_noise_from_equal_feasibility_cells():
    out = exclusion.characterise(_fake_sweep())
    # The 5000/6000 pair shares a feasibility of 0.50, so the noise is 1000.
    assert out["scheduler_noise_images_per_day"] == pytest.approx(1000.0)


def test_characterise_found_slope_sign_and_magnitude():
    out = exclusion.characterise(_fake_sweep())
    # Feasibility falls 10 pp over 10 deg in every row -> 1.0 pp/deg, positive
    # by the "cost of tightening" sign convention.
    assert out["found_feasibility_pp_per_deg"] == pytest.approx(1.0)
    assert out["found_monotone"] is True


def test_sensitivity_slopes_use_the_ceiling_not_the_noisy_count():
    sweep = _fake_sweep()
    out = exclusion.sensitivity(sweep, baseline_lost=30.0, baseline_found=60.0)
    # Loosening FOUND from 60 to 50 deg raises feasibility 0.40 -> 0.50, worth
    # 0.10 * 86400 * 0.2 Hz * 2 cameras = 3456 images/day over 10 deg. The
    # slope is d(images)/d(angle), so it is negative: a bigger cone means
    # fewer images. The report flips it when it prints "loosen".
    assert out["d_images_per_deg_found_looser"] == pytest.approx(-345.6)
    # It must not have been computed off the images_per_day matrix, where the
    # same step is flat (4000 -> 6000 is a different column).
    assert out["baseline_images_per_day"] == 4000.0


# ---------------------------------------------------------------------------
# Pointing-error buffer
# ---------------------------------------------------------------------------

def test_pointing_margin_combination_rules():
    cfg = MissionConfig()
    control = float(cfg.spacecraft.adcs.control_error_deg)
    knowledge = float(cfg.spacecraft.adcs.knowledge_error_deg)

    summed = cfg.copy_with(**{"spacecraft.adcs.pointing_error_combination": "sum"})
    rssed = cfg.copy_with(**{"spacecraft.adcs.pointing_error_combination": "rss"})
    assert adcs.pointing_margin_deg(summed) == pytest.approx(control + knowledge)
    assert adcs.pointing_margin_deg(rssed) == pytest.approx(
        math.hypot(control, knowledge))
    # Worst case is never smaller than the statistical combination.
    assert adcs.pointing_margin_deg(summed) >= adcs.pointing_margin_deg(rssed)

    bogus = cfg.copy_with(**{"spacecraft.adcs.pointing_error_combination": "mean"})
    with pytest.raises(ValueError):
        adcs.pointing_margin_deg(bogus)


def test_keep_outs_are_enforced_with_the_margin():
    """The solver's answers must clear cone + margin, not just the cone.

    This is the test that would catch the margin being plumbed through the
    signature but never reaching the inequality.
    """
    cfg = MissionConfig()
    env = make_env(n=16)
    margin_deg = 8.0            # exaggerated so a miss cannot hide in rounding
    result = geometry.solve_experiment_pointing(
        cfg, env, n_azimuth=48, n_roll=48, pointing_margin_deg=margin_deg)
    if not result.feasible.any():
        pytest.skip("no feasible samples in this synthetic geometry")

    sel = result.feasible
    sun = env.sun_unit()[sel]
    nadir = env.nadir_unit()[sel]
    rho = env.earth_angular_radius()[sel]
    margin = math.radians(margin_deg)

    sensors = cfg.spacecraft.sensors
    z_sun_limit = math.radians(min(float(sensors.lost_camera.sun_exclusion_deg),
                                   float(sensors.star_tracker.sun_exclusion_deg)))
    z_earth_limit = math.radians(float(sensors.lost_camera.earth_exclusion_deg))
    x_sun_limit = math.radians(float(sensors.found_camera.sun_exclusion_deg))

    z_sun = geometry.angle_between(result.z_axis_N[sel], sun)
    z_earth = geometry.angle_between(result.z_axis_N[sel], nadir)
    x_sun = geometry.angle_between(result.x_axis_N[sel], sun)

    assert np.all(z_sun > z_sun_limit + margin - 1e-6)
    assert np.all(z_earth > rho + z_earth_limit + margin - 1e-6)
    assert np.all(x_sun > x_sun_limit + margin - 1e-6)
    assert result.pointing_margin_deg == pytest.approx(margin_deg)


def test_feasibility_never_increases_with_the_margin():
    """A bigger buffer can only remove attitudes, never add them."""
    cfg = MissionConfig()
    env = make_env(n=24)
    counts = [
        geometry.solve_experiment_pointing(
            cfg, env, n_azimuth=32, n_roll=32,
            pointing_margin_deg=m).feasible.sum()
        for m in (0.0, 2.0, 5.0, 10.0)
    ]
    assert counts == sorted(counts, reverse=True)


def test_margin_defaults_to_the_configured_budget():
    """Omitting the argument must not silently disable the buffer."""
    cfg = MissionConfig()
    env = make_env(n=12)
    default = geometry.solve_experiment_pointing(cfg, env, n_azimuth=24, n_roll=24)
    assert default.pointing_margin_deg == pytest.approx(
        adcs.pointing_margin_deg(cfg))
    assert default.pointing_margin_deg > 0.0
