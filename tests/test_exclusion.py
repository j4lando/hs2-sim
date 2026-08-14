"""The camera exclusion-angle trade and the pointing-error buffer."""

from __future__ import annotations

import math

import numpy as np
import pytest

from helpers import make_env
from hs2sim import adcs, exclusion, geometry
from hs2sim.config import MissionConfig


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


def test_fov_shrinks_by_the_margin_and_walls_off():
    """The keep-in constraint must shrink, not grow, with the buffer.

    FOUND's half field of view is 37 deg. Below that the shrink is not what
    binds; at or above it no commanded attitude can guarantee the limb is in
    frame, and the solver must say so with its own reject code rather than
    quietly returning attitudes it cannot honour.
    """
    cfg = MissionConfig()
    env = make_env(n=12)
    half_fov = float(cfg.spacecraft.sensors.found_camera.fov_full_deg) / 2.0

    inside = geometry.solve_experiment_pointing(
        cfg, env, n_azimuth=24, n_roll=24,
        pointing_margin_deg=half_fov - 1.0)
    at_wall = geometry.solve_experiment_pointing(
        cfg, env, n_azimuth=24, n_roll=24, pointing_margin_deg=half_fov)
    beyond = geometry.solve_experiment_pointing(
        cfg, env, n_azimuth=24, n_roll=24, pointing_margin_deg=half_fov + 5.0)

    assert not at_wall.feasible.any()
    assert not beyond.feasible.any()
    assert np.all(at_wall.reject_reason == geometry.REJECT_FOV_MARGIN)
    assert np.all(beyond.reject_reason == geometry.REJECT_FOV_MARGIN)
    # Below the wall the FOV is not the thing rejecting samples.
    assert not np.any(inside.reject_reason == geometry.REJECT_FOV_MARGIN)


def test_uncertainty_and_quoted_exclusion_are_interchangeable():
    """u deg of buffer == folding u into every quoted keep-out.

    This is the identity the effective-half-angle tables are built on. It has
    to hold below the field-of-view wall, and it has to *fail* above it --
    widening a keep-out does not shrink the FOV, but attitude uncertainty does.
    """
    cfg = MissionConfig()
    env = make_env(n=16)
    paths = exclusion.LOST_PATHS + (exclusion.FOUND_PATH,)

    for uncertainty in (0.0, 7.0, 15.0):
        shifted = cfg.copy_with(**{
            p: float(exclusion.getattr_dotted(cfg, p)) + uncertainty
            for p in paths})
        as_buffer = geometry.solve_experiment_pointing(
            cfg, env, n_azimuth=32, n_roll=32,
            pointing_margin_deg=uncertainty)
        as_cones = geometry.solve_experiment_pointing(
            shifted, env, n_azimuth=32, n_roll=32, pointing_margin_deg=0.0)
        assert as_buffer.feasible.tolist() == as_cones.feasible.tolist(), (
            f"{uncertainty} deg of uncertainty is not equivalent to "
            f"{uncertainty} deg of extra keep-out")


def test_keep_out_beyond_90_degrees_is_handled():
    """An exclusion half-angle past 90 deg is a cone bigger than a hemisphere.

    The allowed region for the boresight inverts: it becomes a cap of
    half-angle (180 - effective) about the anti-Sun direction. Feasibility must
    keep falling monotonically through that transition rather than wrapping.
    """
    cfg = MissionConfig()
    env = make_env(n=16)
    counts = []
    for angle in (80.0, 90.0, 100.0, 120.0, 150.0, 179.0):
        trial = cfg.copy_with(**{exclusion.FOUND_PATH: angle})
        result = geometry.solve_experiment_pointing(
            trial, env, n_azimuth=32, n_roll=32, pointing_margin_deg=0.0)
        counts.append(int(result.feasible.sum()))
        # Every surviving attitude must genuinely clear the oversized cone.
        if result.feasible.any():
            sun = env.sun_unit()[result.feasible]
            ang = geometry.angle_between(result.x_axis_N[result.feasible], sun)
            assert np.all(ang > math.radians(angle) - 1e-6)
    assert counts == sorted(counts, reverse=True)
    # A 179 deg keep-out leaves a 1 deg cap; nothing can satisfy it and the
    # limb requirement at once.
    assert counts[-1] == 0
