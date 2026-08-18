"""Detumble simulation: sensors, actuation, dynamics and the control law.

The point of most of these is to pin down the properties the whole analysis
leans on -- that no torque is ever applied along the field, that the sun
sensor obeys the datasheet's cosine law, that a coplanar sensor set is exactly
as blind as it looks -- rather than to check arithmetic.

Nothing here needs Basilisk. The environment comes from
``helpers.detumble_env``, which builds the same ``EnvironmentResult`` Basilisk
produces.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from hs2sim import detumble
from hs2sim.config import MissionConfig

from helpers import detumble_env


@pytest.fixture(scope="module")
def cfg() -> MissionConfig:
    return MissionConfig()


def _ensemble(n_trials: int = 6, duration_s: float = 600.0, n_cases: int = 2):
    cases = [detumble_env(duration_s=duration_s + 5570.0, dt_s=5.0,
                          raan_deg=180.0 * i / n_cases,
                          sun_ecliptic_deg=60.0 * i)
             for i in range(n_cases)]
    return detumble.build_environment_ensemble(
        cases, n_trials, duration_s, np.random.default_rng(3))


# ---------------------------------------------------------------------------
# The property the whole analysis rests on
# ---------------------------------------------------------------------------


def test_control_torque_is_always_perpendicular_to_the_field():
    """``m x B`` has no component along B, for any dipole and any field.

    This is the reason magnetorquer-only control is hard and the reason this
    study had to be simulated rather than reduced to a formula. If a change
    ever makes this fail, the results stop meaning anything.
    """
    rng = np.random.default_rng(0)
    b = rng.normal(size=(500, 3)) * 3e-5
    m = rng.uniform(-0.2, 0.2, size=(500, 3))
    torque = np.cross(m, b)
    along = np.sum(torque * b, axis=1) / np.linalg.norm(b, axis=1)
    assert np.max(np.abs(along)) < 1e-18


def test_commanded_dipole_delivers_the_perpendicular_part_of_the_demand():
    """The projection law gives exactly ``tau_d`` minus its component along B.

    Run with no saturation so the projection is the only thing being tested.
    """
    rng = np.random.default_rng(1)
    n = 400
    b = rng.normal(size=(n, 3)) * 3e-5
    tau_d = rng.normal(size=(n, 3)) * 1e-9      # tiny: never saturates
    m = detumble.commanded_dipole(
        mode=np.zeros(n, dtype=np.int8),
        omega_meas=-tau_d / 1.0e-4,             # tau_desired = -k omega
        b_meas=b, sun_meas=np.zeros((n, 3)),
        sun_valid=np.zeros(n, dtype=bool),
        target_axis_B=np.zeros((n, 3)),
        k_detumble=1.0e-4, k_p=0.0, k_d=0.0,
        m_max=np.full(3, 1e6))
    applied = np.cross(m, b)
    b_hat = b / np.linalg.norm(b, axis=1, keepdims=True)
    expected = tau_d - np.sum(tau_d * b_hat, axis=1, keepdims=True) * b_hat
    assert np.allclose(applied, expected, atol=1e-18)


def test_b_cross_control_removes_energy_from_the_tumble():
    """Rate damping is dissipative: with no disturbances, |omega| never grows.

    The perpendicular projection cannot reverse the sign of
    ``omega . tau``, so the rotational kinetic energy has to fall.
    """
    rng = np.random.default_rng(2)
    n = 300
    omega = rng.normal(size=(n, 3)) * 0.1
    b = rng.normal(size=(n, 3)) * 3e-5
    m = detumble.commanded_dipole(
        mode=np.zeros(n, dtype=np.int8), omega_meas=omega, b_meas=b,
        sun_meas=np.zeros((n, 3)), sun_valid=np.zeros(n, dtype=bool),
        target_axis_B=np.zeros((n, 3)), k_detumble=1.0e-4, k_p=0.0, k_d=0.0,
        m_max=np.full(3, 1e6))
    power = np.sum(omega * np.cross(m, b), axis=1)
    assert np.all(power <= 1e-20)


# ---------------------------------------------------------------------------
# Dynamics
# ---------------------------------------------------------------------------


def _free_context(n: int) -> detumble.DynamicsContext:
    inertia = np.diag([0.05, 0.05, 0.01])
    return detumble.DynamicsContext(
        inertia=inertia, inertia_inv=np.linalg.inv(inertia),
        r_hat_N=np.tile([1.0, 0.0, 0.0], (n, 1)), r_mag=np.full(n, 6.79e6),
        v_hat_N=np.tile([0.0, 1.0, 0.0], (n, 1)), v_mag=np.full(n, 7660.0),
        b_N=np.zeros((n, 3)), dipole_B=np.zeros((n, 3)),
        residual_B=np.zeros((n, 3)), cp_offset_B=np.zeros((n, 3)),
        face_areas=np.array([0.03, 0.03, 0.01]), drag_coefficient=2.2,
        density=0.0, use_gravity_gradient=False, use_residual_dipole=False,
        use_aerodynamic=False)


def test_torque_free_motion_conserves_angular_momentum_and_energy():
    """The integrator does not quietly add or remove momentum.

    A torque-free asymmetric body is the classic integrator test: momentum in
    inertial axes and rotational energy are both exactly conserved, and an
    integrator with the wrong quaternion convention or a sign slip fails it
    immediately.

    The rate is set at the top of the modelled tumble range (20 deg/s). This
    3U has Ixx/Izz = 5, so its body-frame precession runs at four times the
    spin rate, and that -- not the spin itself -- is what the step size has to
    resolve. At 20 deg/s and the configured 0.25 s step, 1000 s of free motion
    holds momentum and energy to within a few parts in 10^6 across a spread of
    tumble axes; the assertions below sit just outside that, which is still
    orders of magnitude tighter than anything the analysis is sensitive to.
    """
    rng = np.random.default_rng(4)
    n = 32
    ctx = _free_context(n)
    q = detumble.random_quaternions(rng, n)
    omega = detumble.random_unit_vectors(rng, n) * math.radians(20.0)

    def momentum(q_, w_):
        dcm = detumble.quat_to_dcm(q_)
        h_body = w_ @ ctx.inertia.T
        return np.einsum("nji,nj->ni", dcm, h_body)      # body -> inertial

    h0 = momentum(q, omega)
    e0 = 0.5 * np.sum(omega * (omega @ ctx.inertia.T), axis=1)
    for _ in range(4000):
        q, omega = detumble.rk4_step(q, omega, 0.25, ctx)
    h1 = momentum(q, omega)
    e1 = 0.5 * np.sum(omega * (omega @ ctx.inertia.T), axis=1)

    assert np.max(np.abs(h1 - h0)) / np.max(np.linalg.norm(h0, axis=1)) < 1e-5
    assert np.max(np.abs(e1 - e0) / e0) < 1e-5
    assert np.allclose(np.linalg.norm(q, axis=1), 1.0)


def test_gravity_gradient_torque_vanishes_when_a_principal_axis_is_nadir():
    """No gravity gradient torque with a principal axis along the radius."""
    ctx = _free_context(1)
    ctx.use_gravity_gradient = True
    q = np.array([[1.0, 0.0, 0.0, 0.0]])        # body aligned with inertial
    _, tau = detumble.body_torques(q, ctx)      # r_hat is +x, a principal axis
    assert np.max(np.abs(tau)) < 1e-18


# ---------------------------------------------------------------------------
# Sun sensors
# ---------------------------------------------------------------------------


def test_photodiode_follows_the_datasheet_cosine_law(cfg):
    """Response is halved at the datasheet's 60 deg acceptance half angle.

    The SLCD-61N8 quotes a 60 deg half angle, and ``cos 60 = 0.5`` exactly,
    which is what identifies the part as a plain cosine receiver. This checks
    the model actually implements that rather than a fudged roll-off.
    """
    rng = np.random.default_rng(5)
    sensors = detumble.make_sun_sensors(
        cfg, np.array([[0.0, 0.0, 1.0]]), 1, rng, 1361.0)
    half_angle = math.radians(float(cfg.detumble.sun_sensor.acceptance_half_angle_deg))

    def current(angle_rad: float) -> float:
        sun = np.array([[math.sin(angle_rad), 0.0, math.cos(angle_rad)]])
        return float(sensors.measure(
            sun, np.zeros((1, 3)), np.ones(1), np.full(1, 1361.0),
            np.full(1, 6.79e6), None, np.random.default_rng(0))[0, 0])

    on_axis = current(0.0)
    assert current(half_angle) == pytest.approx(0.5 * on_axis, rel=0.02)
    assert current(math.radians(80.0)) == pytest.approx(
        math.cos(math.radians(80.0)) * on_axis, rel=0.05)
    # Behind the face plane the body occults the die entirely.
    assert current(math.radians(95.0)) < 0.01 * on_axis


def test_normal_incidence_current_matches_the_datasheet_scaling(cfg):
    """170 uA at 250 W/m^2 scales to ~0.93 mA at AM0, under the ADC full scale."""
    spec = cfg.detumble.sun_sensor
    expected = float(spec.isc_typ_a) * 1361.0 / float(spec.reference_irradiance_w_m2)
    assert expected == pytest.approx(925.6e-6, rel=0.01)
    assert expected < float(spec.adc_full_scale_a), "AM0 must not clip the ADC"


def _matched_gain_cfg(cfg: MissionConfig) -> MissionConfig:
    """A config whose photodiodes all share the datasheet's typical gain.

    Isolates layout geometry from part-to-part spread. Real parts do not come
    matched, which is what the next test measures.
    """
    return cfg.copy_with(**{
        "detumble.sun_sensor.isc_min_a": float(cfg.detumble.sun_sensor.isc_typ_a)})


def _estimate(cfg: MissionConfig, boresights: np.ndarray, truth: np.ndarray,
              seed: int = 0) -> np.ndarray:
    sensors = detumble.make_sun_sensors(cfg, boresights, 1,
                                        np.random.default_rng(seed), 1361.0)
    currents = sensors.measure(truth, np.zeros((1, 3)), np.ones(1),
                               np.full(1, 1361.0), np.full(1, 6.79e6), None,
                               np.random.default_rng(seed))
    estimate, valid = sensors.estimate_sun(currents)
    assert bool(valid[0])
    return estimate[0]


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(math.acos(float(np.clip(a @ b, -1, 1))))


def test_six_face_set_recovers_the_sun_vector_and_coplanar_sets_cannot(cfg):
    """The rank of a layout is what decides whether it can see out of plane.

    Both four-sensor geometries have every boresight in the body xy plane, so
    no combination of their readings carries any information about the Sun's z
    component -- and the least squares solve returns the in-plane projection,
    which it recovers essentially exactly. The six-face set sees all three
    axes. This is a property of the geometry, not of the estimator, and it is
    the headline result of the sensor trade.
    """
    matched = _matched_gain_cfg(cfg)
    truth = detumble.unit(np.array([[0.3, 0.5, 0.81]]))
    in_plane = detumble.unit(truth * np.array([1.0, 1.0, 0.0]))
    for name, geometry in cfg.sensor_geometries():
        boresights = np.asarray(geometry.boresights, dtype=float)
        estimate = _estimate(matched, boresights, truth)
        error = _angle_deg(estimate, truth[0])
        if name == "six_faces":
            assert error < 0.5
        else:
            assert error > 20.0, f"{name} should be blind to the z component"
            assert _angle_deg(estimate, in_plane[0]) < 0.5, name


def test_uncalibrated_channel_gains_cost_a_few_degrees(cfg):
    """The 100-170 uA datasheet spread is a real error if nothing calibrates it.

    Each channel draws its own gain, and the estimator normalises the solved
    vector rather than any individual reading, so a common gain cancels but a
    per-channel mismatch does not. It is worth knowing the size of what the
    minimal estimator gives up: a few degrees, which is an order of magnitude
    below the albedo error and so not worth flight software to fix.
    """
    boresights = np.asarray(cfg.detumble.sensor_geometries.six_faces.boresights,
                            dtype=float)
    truth = detumble.unit(np.array([[0.3, 0.5, 0.81]]))
    matched = np.median([_angle_deg(_estimate(_matched_gain_cfg(cfg), boresights,
                                              truth, seed=s), truth[0])
                         for s in range(40)])
    dispersed = np.median([_angle_deg(_estimate(cfg, boresights, truth, seed=s),
                                      truth[0]) for s in range(40)])
    assert matched < 0.5
    assert 0.5 < dispersed < 8.0


def test_sky_coverage_reports_the_expected_ranks(cfg):
    coverage = {name: detumble.sky_coverage(
        cfg, np.asarray(geometry.boresights, dtype=float), samples=4000)
        for name, geometry in cfg.sensor_geometries()}
    assert coverage["four_side_faces"]["sensed_subspace_rank"] == 2
    assert coverage["canted_y_pair"]["sensed_subspace_rank"] == 2
    assert coverage["six_faces"]["sensed_subspace_rank"] == 3
    # The canted pair puts two of its four normals 45 deg apart, so it is
    # measurably worse conditioned than the orthogonal four-face set even
    # though both light exactly two channels at a time.
    assert (coverage["canted_y_pair"]["noise_amplification_median"]
            > 1.5 * coverage["four_side_faces"]["noise_amplification_median"])


def test_albedo_is_large_enough_to_matter():
    """A nadir-facing face over a sunlit Earth sees a quarter of a Sun.

    If this ever comes out small, the albedo model has been broken rather than
    the problem having gone away.
    """
    nadir_B = np.array([[0.0, 0.0, -1.0]])
    boresights = np.array([[0.0, 0.0, -1.0]])
    sun_B = np.array([[0.0, 0.0, 1.0]])       # Sun at the zenith
    irradiance = detumble.albedo_irradiance(
        nadir_B, boresights, sun_B, np.full(1, 6.79e6), np.full(1, 1361.0), 0.30)
    assert 300.0 < float(irradiance[0, 0]) < 400.0


# ---------------------------------------------------------------------------
# Actuators and array geometry
# ---------------------------------------------------------------------------


def test_coils_saturate_per_axis(cfg):
    rng = np.random.default_rng(7)
    coils = detumble.make_magnetorquers(cfg, 4, rng)
    huge = np.tile([100.0, -100.0, 100.0], (4, 1))
    realised = coils.realise(huge)
    # Scale-factor and misalignment errors are a few percent, so the realised
    # dipole sits near but not exactly on the box.
    assert np.all(np.abs(realised) < 1.2 * coils.m_max.max())
    assert np.all(np.abs(realised) > 0.8 * coils.m_max.min())


def test_array_power_axis_is_the_optimum_pointing_direction(cfg):
    """The power-weighted normal maximises array output, to the digit.

    Worth pinning because the sun acquisition law aims this axis and nothing
    else; if it is not the optimum then the controller is converging to the
    wrong place even when it works perfectly.
    """
    array = detumble.make_array(cfg, "C_2panel_135_plus_body")
    axis = array.power_axis
    best = array.best_capture_fraction()
    at_axis = float(array.capture_fraction(axis[None, :], np.ones(1))[0])
    assert at_axis == pytest.approx(best, rel=1e-3)
    assert best < 1.0, "a canted two-panel array cannot reach its peak rating"


def test_single_panel_array_can_reach_its_full_rating(cfg):
    array = detumble.make_array(cfg, "A_2panel_90")
    assert array.best_capture_fraction() == pytest.approx(1.0, abs=1e-3)
    assert np.allclose(array.power_axis, [-1.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# Environment plumbing and the end-to-end run
# ---------------------------------------------------------------------------


def test_environment_ensemble_interpolates_between_samples():
    env = _ensemble(n_trials=4, duration_s=600.0)
    # Pin the start times to the grid so all three samples below fall inside
    # one environment interval; the interpolation is piecewise linear, not
    # linear, so straddling a knot would not give the midpoint.
    env.start_s = np.zeros_like(env.start_s)
    early = env.sample(0.0)
    mid = env.sample(2.5)          # half a 5 s environment step in
    later = env.sample(5.0)
    assert np.allclose(mid["r_N"], 0.5 * (early["r_N"] + later["r_N"]), rtol=1e-9)
    assert np.allclose(np.linalg.norm(mid["sun_hat_N"], axis=1), 1.0)


def test_environment_ensemble_refuses_a_span_shorter_than_the_trial():
    cases = [detumble_env(duration_s=300.0, dt_s=5.0)]
    with pytest.raises(ValueError, match="shorter than the trial"):
        detumble.build_environment_ensemble(cases, 4, 21600.0,
                                            np.random.default_rng(0))


def test_measure_window_must_divide_the_integration_step(cfg):
    broken = cfg.copy_with(**{"detumble.monte_carlo.time_step_s": 0.4})
    with pytest.raises(ValueError, match="whole multiple"):
        detumble.run_monte_carlo(broken, "six_faces", _ensemble(2, 100.0),
                                 duration_s=100.0)


def test_a_short_run_reduces_the_tumble(cfg):
    """End to end: rates fall, the coils are used, nothing goes non-finite."""
    fast = cfg.copy_with(**{"detumble.monte_carlo.initial_rate_deg_per_s": [8.0, 12.0],
                            "detumble.metrics.steady_state_window_s": 200.0})
    env = _ensemble(n_trials=8, duration_s=900.0, n_cases=2)
    run = detumble.run_monte_carlo(fast, "six_faces", env, duration_s=900.0)
    assert np.all(np.isfinite(run.rate_deg_s))
    assert np.median(run.rate_deg_s[-1]) < 0.6 * np.median(run.rate_deg_s[0])
    assert run.summary["sensed_subspace_rank"] == 3
    assert 0.0 < run.summary["mean_dipole_fraction_median"] <= 1.0


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def test_every_detumble_figure_is_drawn(cfg, tmp_path):
    """The figure set renders from a real (tiny) run without special-casing.

    Cheap insurance: the plotting layer reads a dozen fields off
    ``MonteCarloResult`` and a rename on either side would otherwise only show
    up at the end of a two-minute Monte Carlo.
    """
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")

    from hs2sim.output import detumble_plots

    short = cfg.copy_with(**{"detumble.metrics.steady_state_window_s": 100.0})
    env = _ensemble(n_trials=6, duration_s=400.0, n_cases=2)
    runs = {name: detumble.run_monte_carlo(short, name, env, duration_s=400.0)
            for name in ("four_side_faces", "six_faces")}
    results = {"sky_coverage": {
        name: detumble.sky_coverage(cfg, np.asarray(geometry.boresights,
                                                    dtype=float), samples=2000)
        for name, geometry in cfg.sensor_geometries()}}

    detumble_plots.make_all(runs, results, tmp_path)
    expected = {"detumble_rate.png", "detumble_time_cdf.png",
                "detumble_power_capture.png", "detumble_sun_error.png",
                "detumble_sky_coverage.png", "detumble_steady_state.png"}
    written = {path.name for path in tmp_path.glob("*.png")}
    assert expected <= written
    assert all((tmp_path / name).stat().st_size > 5000 for name in expected)
