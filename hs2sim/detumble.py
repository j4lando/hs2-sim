"""Monte Carlo detumble and sun acquisition for HS-2.

This is a separate analysis from the CONOPS study. Where ``hs2sim.conops``
asks "given a pointed, controlled vehicle, what can it get done", this module
asks the question that comes first: *starting from a post-deployment tumble,
with only magnetorquers, an IMU and a handful of photodiodes, does the
vehicle stop spinning and end up with its array facing the Sun?*

Read docs/DETUMBLE.md for the algorithm statement and the assumption list.
The three things worth knowing before reading the code:

1. **No torque is ever invented.** Every control torque in here is
   ``tau = m x B``, where ``m`` is a realisable coil dipole (saturated at the
   per-axis limit, with scale-factor and misalignment errors applied) and
   ``B`` is the true local field at the true position at that instant. The
   controller computes a *desired* torque and then asks for the dipole whose
   cross product comes closest to it,

       m = (B x tau_desired) / |B|^2   ->   tau = tau_desired - (tau_desired . Bhat) Bhat

   so the component of the desired torque along the field is simply lost. That
   under-actuation is the whole character of magnetic control and it is why
   this has to be simulated rather than reduced to a time constant.

2. **The environment is Basilisk's, not this module's.** There is no orbit,
   field or eclipse model in here. Position, velocity, the magnetic field, the
   Sun direction and the eclipse factor all come from
   ``hs2sim.environment.propagate`` -- the same propagation ``run_analysis.py``
   runs on. This module adds attitude, the sensors that observe it, the coils
   that change it, and nothing else. Basilisk is therefore a hard requirement.

3. **Every trial runs at once.** The Monte Carlo is vectorised: state arrays
   are ``(n_trials, ...)`` and one integration step advances the whole
   ensemble, so a couple of hundred trials cost barely more than one.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np

from .config import MissionConfig
from .environment import AU, MU_EARTH, R_EARTH

# ---------------------------------------------------------------------------
# Small vector / quaternion helpers, all vectorised over a leading trial axis.
#
# Quaternions are scalar-first, [w, x, y, z], and represent the rotation from
# the inertial frame N to the body frame B: v_B = A(q) v_N.
# ---------------------------------------------------------------------------


def unit(v: np.ndarray, axis: int = -1) -> np.ndarray:
    """Normalise along ``axis``; zero-length rows come back as zeros."""
    norm = np.linalg.norm(v, axis=axis, keepdims=True)
    return np.divide(v, norm, out=np.zeros_like(v), where=norm > 0)


def quat_normalize(q: np.ndarray) -> np.ndarray:
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def quat_to_dcm(q: np.ndarray) -> np.ndarray:
    """(N,4) scalar-first quaternion -> (N,3,3) DCM taking inertial to body."""
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)], -1),
        np.stack([2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)], -1),
        np.stack([2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)], -1),
    ], axis=-2)


def rotate_to_body(dcm: np.ndarray, v_N: np.ndarray) -> np.ndarray:
    """Apply a stack of DCMs: (N,3,3) x (N,3) -> (N,3)."""
    return np.einsum("nij,nj->ni", dcm, v_N)


def quat_derivative(q: np.ndarray, omega_B: np.ndarray) -> np.ndarray:
    """dq/dt for body rate ``omega_B``, scalar-first convention."""
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    p, r, s = omega_B[..., 0], omega_B[..., 1], omega_B[..., 2]
    return 0.5 * np.stack([
        -x * p - y * r - z * s,
        w * p - z * r + y * s,
        z * p + w * r - x * s,
        -y * p + x * r + w * s,
    ], axis=-1)


def random_quaternions(rng: np.random.Generator, n: int) -> np.ndarray:
    """``n`` attitudes drawn uniformly over SO(3) (Shoemake's method)."""
    u1, u2, u3 = rng.random(n), rng.random(n), rng.random(n)
    return np.stack([
        np.sqrt(u1) * np.cos(2 * np.pi * u3),
        np.sqrt(1 - u1) * np.sin(2 * np.pi * u2),
        np.sqrt(1 - u1) * np.cos(2 * np.pi * u2),
        np.sqrt(u1) * np.sin(2 * np.pi * u3),
    ], axis=-1)


def random_unit_vectors(rng: np.random.Generator, n: int) -> np.ndarray:
    """``n`` directions drawn uniformly over the sphere."""
    return unit(rng.normal(size=(n, 3)))


def small_rotation_matrices(rng: np.random.Generator, n: int,
                            sigma_deg: float) -> np.ndarray:
    """(n,3,3) misalignment matrices: small random rotations, 1-sigma per axis.

    Used for sensor and coil mounting error. At the fractions of a degree
    involved the first-order form ``I + [theta x]`` is exact to well under the
    noise floor, but it is orthonormalised anyway so repeated application
    cannot drift.
    """
    if sigma_deg <= 0:
        return np.broadcast_to(np.eye(3), (n, 3, 3)).copy()
    theta = np.radians(rng.normal(scale=sigma_deg, size=(n, 3)))
    skew = np.zeros((n, 3, 3))
    skew[:, 0, 1], skew[:, 0, 2] = -theta[:, 2], theta[:, 1]
    skew[:, 1, 0], skew[:, 1, 2] = theta[:, 2], -theta[:, 0]
    skew[:, 2, 0], skew[:, 2, 1] = -theta[:, 1], theta[:, 0]
    mats = np.eye(3) + skew
    # Re-orthonormalise (one Newton step of the polar decomposition).
    return 1.5 * mats - 0.5 * mats @ np.einsum("nij,nkj->nik", mats, mats)


# ---------------------------------------------------------------------------
# Environment
#
# There is no orbit, field or eclipse model in this file. Everything about
# where the spacecraft is, what the Sun is doing and what the local field is
# comes from ``hs2sim.environment.propagate`` -- the same Basilisk propagation
# the CONOPS analysis runs on, with the same J2 gravity, the same centred
# dipole field and the same eclipse module. This analysis only adds attitude.
#
# Two things have to be bridged to make that work:
#
# 1. **Resolution.** Basilisk is sampled at ``mission.simulation.time_step_s``
#    (5 s by default) while the attitude integrator runs at a quarter second.
#    The environment is therefore linearly interpolated onto the fine grid.
#    Over 5 s the vehicle covers 38 km of a 6790 km orbit and the field turns
#    by well under a degree, so the interpolation error is far below the
#    magnetometer noise it feeds.
#
# 2. **Dispersion.** One propagation is one orbit geometry. To disperse the
#    environment across the Monte Carlo, a handful of propagations are run at
#    different RAANs -- which is what moves the beta angle, and with it the
#    eclipse fraction and the Sun-to-orbit-plane geometry -- and each trial is
#    assigned one of them plus a random start time inside it. The number of
#    propagations is a cost knob: each one is a full Basilisk run.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class EnvironmentEnsemble:
    """Per-trial windows into a set of Basilisk environment histories.

    The case histories all share a time grid, so they stack into
    ``(n_cases, n_samples, ...)`` arrays and one gather serves the whole
    ensemble.
    """

    dt_s: float
    case_index: np.ndarray        # (N,) which propagation each trial reads
    start_s: np.ndarray           # (N,) offset into that propagation
    r_BN_N: np.ndarray            # (C,M,3) m
    v_BN_N: np.ndarray            # (C,M,3) m/s
    b_field_N: np.ndarray         # (C,M,3) T
    sun_hat_N: np.ndarray         # (C,M,3) unit, spacecraft to Sun
    sun_dist_m: np.ndarray        # (C,M)
    shadow: np.ndarray            # (C,M)
    beta_deg: np.ndarray          # (C,) mean |beta| of each case, for reporting

    @property
    def n_trials(self) -> int:
        return len(self.case_index)

    @property
    def span_s(self) -> float:
        return (self.r_BN_N.shape[1] - 1) * self.dt_s

    def sample(self, t_s: float) -> dict[str, np.ndarray]:
        """Linear interpolation of every history at ``t_s`` into each trial."""
        absolute = self.start_s + t_s
        raw = absolute / self.dt_s
        last = self.r_BN_N.shape[1] - 1
        low = np.clip(np.floor(raw).astype(int), 0, last - 1)
        frac = np.clip(raw - low, 0.0, 1.0)[:, None]
        case = self.case_index

        def lerp(table: np.ndarray) -> np.ndarray:
            a = table[case, low]
            b = table[case, low + 1]
            weight = frac if a.ndim == 2 else frac[:, 0]
            return a + (b - a) * weight

        r_N = lerp(self.r_BN_N)
        v_N = lerp(self.v_BN_N)
        return {
            "r_N": r_N,
            "v_N": v_N,
            "b_N": lerp(self.b_field_N),
            # Renormalised after interpolation: the chord between two unit
            # vectors is shorter than the arc, and the Sun direction is used
            # as a unit vector everywhere downstream.
            "sun_hat_N": unit(lerp(self.sun_hat_N)),
            "sun_dist_m": lerp(self.sun_dist_m),
            "shadow": np.clip(lerp(self.shadow), 0.0, 1.0),
        }


def propagate_cases(cfg: MissionConfig, n_cases: int, duration_s: float,
                    log=None) -> list:
    """Run ``n_cases`` Basilisk propagations at evenly spaced RAANs.

    RAAN is what the Monte Carlo disperses, because it is what moves the beta
    angle -- and beta sets both how much of each orbit is eclipsed (no sun
    sensor signal at all) and how the Sun sits relative to the orbit plane.
    Sweeping it evenly rather than randomly means a modest number of cases
    still covers the full range instead of clumping.

    Every case is propagated for ``duration_s``, which must cover a trial plus
    the largest start offset the ensemble uses.
    """
    from . import environment

    duration_days = duration_s / 86400.0
    cases = []
    for index in range(n_cases):
        raan = 360.0 * index / n_cases
        case_cfg = cfg.copy_with(**{
            "orbit.raan_deg": raan,
            "mission.simulation.duration_days": duration_days,
        })
        if log is not None:
            log(f"  propagating RAAN {raan:6.1f} deg "
                f"({index + 1}/{n_cases}, {duration_days:.3f} days)")
        cases.append(environment.propagate(case_cfg))
    return cases


def build_environment_ensemble(cases: list, n_trials: int, duration_s: float,
                               rng: np.random.Generator) -> EnvironmentEnsemble:
    """Assign trials to propagations and random start times inside them."""
    if not cases:
        raise ValueError("need at least one propagated environment case")
    dt_s = float(cases[0].dt_s)
    n_samples = min(case.n_samples for case in cases)
    for case in cases:
        if not math.isclose(case.dt_s, dt_s, rel_tol=1e-9):
            raise ValueError("environment cases must share a time step")

    span_s = (n_samples - 1) * dt_s
    slack_s = span_s - duration_s
    if slack_s < 0:
        raise ValueError(
            f"propagated span {span_s:.0f} s is shorter than the trial "
            f"duration {duration_s:.0f} s -- propagate for longer")

    def stack(getter) -> np.ndarray:
        return np.stack([np.asarray(getter(c))[:n_samples] for c in cases])

    # Cases are handed out round robin so every one gets the same share of
    # trials regardless of how the trial count divides.
    case_index = np.arange(n_trials) % len(cases)
    rng.shuffle(case_index)
    start_s = rng.uniform(0.0, slack_s, size=n_trials)

    sun_rel = stack(lambda c: c.r_sun_N - c.r_BN_N)
    sun_dist = np.linalg.norm(sun_rel, axis=-1)
    return EnvironmentEnsemble(
        dt_s=dt_s,
        case_index=case_index,
        start_s=start_s,
        r_BN_N=stack(lambda c: c.r_BN_N),
        v_BN_N=stack(lambda c: c.v_BN_N),
        b_field_N=stack(lambda c: c.b_field_N),
        sun_hat_N=sun_rel / sun_dist[..., None],
        sun_dist_m=sun_dist,
        shadow=stack(lambda c: c.shadow_factor),
        beta_deg=np.array([float(np.degrees(np.mean(np.abs(c.beta_angle()))))
                           for c in cases]),
    )


def albedo_irradiance(nadir_B: np.ndarray, boresights_B: np.ndarray,
                      sun_hat_B: np.ndarray, r_mag: np.ndarray,
                      solar_irradiance: np.ndarray,
                      reflectivity: float) -> np.ndarray:
    """Earth-reflected irradiance on each sensor face, W/m^2. (N, n_sensors)

    A deliberately coarse Lambert-sphere model, because a proper albedo model
    (a gridded reflectivity map integrated over the visible cap) would be more
    machinery than the rest of this simulation put together and would not
    change the conclusion. Earth is treated as a uniform Lambertian sphere of
    angular radius ``rho``, and a flat plate at angle ``gamma`` off nadir sees

        E = a * S * sin^2(rho) * max(0, cos gamma) * (1 + cos z) / 2

    where ``z`` is the solar zenith angle at the sub-satellite point. The last
    factor is the fraction of the visible disc that is sunlit: 1 with the Sun
    overhead, 1/2 at the terminator, 0 on the night side.

    The magnitude matters. At 415 km ``sin^2 rho`` is 0.88, so a nadir-facing
    photodiode over a fully sunlit sub-satellite point sees about
    0.3 * 1361 * 0.88 = 360 W/m^2 -- a quarter of the direct solar signal,
    arriving from a completely different direction. This is the dominant error
    source for coarse sun sensors in low orbit, and switching it off in
    config/detumble.yaml is the fastest way to see how much of the sun
    acquisition performance below is really an albedo story.
    """
    sin2_rho = np.clip((R_EARTH / r_mag) ** 2, 0.0, 1.0)[:, None]
    cos_zenith = -np.sum(sun_hat_B * nadir_B, axis=-1)[:, None]
    sunlit_fraction = np.clip(0.5 * (1.0 + cos_zenith), 0.0, 1.0)
    cos_gamma = np.clip(nadir_B @ boresights_B.T, 0.0, None)
    return (reflectivity * solar_irradiance[:, None] * sin2_rho
            * cos_gamma * sunlit_fraction)


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SunSensorArray:
    """A set of SLCD-61N8 photodiodes on body faces, plus their electronics.

    ``boresights`` is (n_sensors, 3) in body axes. Everything else is a
    per-trial dispersion drawn once at the start of a Monte Carlo run.
    """

    boresights: np.ndarray            # (S,3) unit, body frame
    isc_scale: np.ndarray             # (N,S) A per (W/m^2), per trial+sensor
    dark_current_a: np.ndarray        # (N,S) fixed offset
    lsb_a: float
    full_scale_a: float
    valid_threshold_a: float
    name: str = ""

    @property
    def n_sensors(self) -> int:
        return len(self.boresights)

    def measure(self, sun_hat_B: np.ndarray, nadir_B: np.ndarray,
                shadow: np.ndarray, solar_irradiance: np.ndarray,
                r_mag: np.ndarray, albedo_reflectivity: float | None,
                rng: np.random.Generator) -> np.ndarray:
        """Quantised photocurrent from every channel, A. (N, S)

        Cosine response with a hard zero behind the face plane -- see the
        angular-response note in config/detumble.yaml. Direct sunlight is
        scaled by the eclipse factor; Earth albedo is not, because a
        spacecraft in Earth's shadow sees no sunlit Earth either (the
        ``(1 + cos z)/2`` factor already goes to zero there).
        """
        cos_incidence = np.clip(sun_hat_B @ self.boresights.T, 0.0, None)
        direct = solar_irradiance[:, None] * shadow[:, None] * cos_incidence
        total = direct
        if albedo_reflectivity is not None:
            total = total + albedo_irradiance(nadir_B, self.boresights,
                                              sun_hat_B, r_mag,
                                              solar_irradiance,
                                              albedo_reflectivity)
        current = self.isc_scale * total + self.dark_current_a
        # Shot + electronics noise, floored so a dark channel still rattles.
        sigma = np.maximum(0.5 * self.lsb_a, 0.01 * current)
        current = current + rng.normal(scale=sigma)
        current = np.clip(current, 0.0, self.full_scale_a)
        return np.floor(current / self.lsb_a) * self.lsb_a

    def estimate_sun(self, currents: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Body-frame Sun direction from the channel currents. (N,3), (N,) valid

        THE FLIGHT ALGORITHM, and deliberately the whole of it: take every
        channel reading above the dark threshold, and solve the linear least
        squares problem

            minimise over v   sum_i ( I_i - n_i . v )^2

        then normalise ``v``. Each lit channel contributes ``I_i = k n_i . s``,
        so ``v`` recovers ``k s`` whenever the lit normals span three
        dimensions, and its normalisation removes the unknown gain ``k`` --
        which is exactly what makes the estimate immune to the datasheet's
        100-to-170 uA spread and to the solar-spectrum scaling.

        When the lit normals *do not* span three dimensions -- which is every
        sample for both four-sensor geometries, because none of their
        boresights has a z component -- the solve returns the minimum-norm
        solution, i.e. the true Sun vector projected into the span of the
        normals. For a body-fixed array whose panel normals also lie in that
        span, that projection is not an approximation to work around: it is
        precisely the direction the array should be turned towards. See
        docs/DETUMBLE.md.

        A fix is declared valid when at least two channels are lit. Two is
        enough to fix a direction within the plane the four-sensor sets can
        see; below that the estimate is a single channel's boresight and
        carries no directional information at all.
        """
        lit = currents > self.valid_threshold_a
        n_lit = lit.sum(axis=1)
        weighted = np.where(lit, currents, 0.0)
        # Normal equations: (Nt Nt^T) v = Nt I, restricted to lit channels.
        # Built per-trial from the lit mask, but only ever 3x3, so a batched
        # solve handles the whole ensemble in one call.
        gram = np.einsum("ns,si,sj->nij", lit.astype(float),
                         self.boresights, self.boresights)
        rhs = weighted @ self.boresights
        # Ridge term keeps the rank-deficient sets solvable and turns the
        # solve into the minimum-norm one. 1e-9 is ~1e-9 of the typical
        # diagonal, so it does not bias the well-conditioned directions.
        gram = gram + 1e-9 * np.eye(3)
        vec = np.linalg.solve(gram, rhs[..., None])[..., 0]
        return unit(vec), n_lit >= 2


def make_sun_sensors(cfg: MissionConfig, boresights: np.ndarray, n_trials: int,
                     rng: np.random.Generator, solar_constant: float,
                     name: str = "") -> SunSensorArray:
    """Build a dispersed sun sensor array for one Monte Carlo ensemble."""
    spec = cfg.detumble.sun_sensor
    boresights = unit(np.asarray(boresights, dtype=float))
    n_sensors = len(boresights)

    # Responsivity per W/m^2, from the datasheet stimulus. The 100-170 uA
    # min/typ spread is the real part-to-part uncertainty, so each channel of
    # each trial draws uniformly across it.
    isc_ref = rng.uniform(float(spec.isc_min_a), float(spec.isc_typ_a),
                          size=(n_trials, n_sensors))
    responsivity = (isc_ref / float(spec.reference_irradiance_w_m2)
                    * float(spec.solar_spectral_factor))

    # Dark current at the modelled temperature, from the 25 C datasheet max.
    tempco = float(spec.dark_current_tempco_per_c)
    temp_scale = (1.0 + tempco) ** (float(spec.temperature_c) - 25.0)
    dark = (float(spec.dark_current_a) * temp_scale
            * rng.uniform(0.2, 1.0, size=(n_trials, n_sensors)))

    full_scale = float(spec.adc_full_scale_a)
    lsb = full_scale / (2 ** int(spec.adc_bits) - 1)
    # Threshold is a fraction of the current a normal-incidence Sun makes.
    normal_incidence = float(spec.isc_typ_a) * solar_constant / float(
        spec.reference_irradiance_w_m2)
    return SunSensorArray(
        boresights=boresights,
        isc_scale=responsivity,
        dark_current_a=dark,
        lsb_a=lsb,
        full_scale_a=full_scale,
        valid_threshold_a=float(spec.valid_fraction) * normal_incidence,
        name=name,
    )


@dataclasses.dataclass
class Imu:
    """Gyro plus magnetometer, with the errors that actually bite.

    Both instruments carry a turn-on bias redrawn every trial, a per-axis
    scale factor error, a mounting misalignment and white noise. The gyro also
    has a slow in-run bias random walk; the magnetometer's equivalent (hard
    iron drift with the coils' thermal state) is folded into its turn-on bias,
    which is dominated by the bus anyway.
    """

    gyro_bias: np.ndarray            # (N,3) rad/s, walks during the run
    gyro_scale: np.ndarray           # (N,3)
    gyro_align: np.ndarray           # (N,3,3)
    gyro_arw: float                  # rad/s/sqrt(s)
    gyro_rrw: float                  # rad/s^2/sqrt(s)
    gyro_resolution: float           # rad/s
    gyro_range: float                # rad/s
    mag_bias: np.ndarray             # (N,3) T
    mag_scale: np.ndarray            # (N,3)
    mag_align: np.ndarray            # (N,3,3)
    mag_noise: float                 # T
    mag_range: float                 # T

    def read_gyro(self, omega_B: np.ndarray, dt_s: float,
                  rng: np.random.Generator) -> np.ndarray:
        self.gyro_bias = self.gyro_bias + self.gyro_rrw * math.sqrt(dt_s) * \
            rng.normal(size=self.gyro_bias.shape)
        measured = np.einsum("nij,nj->ni", self.gyro_align,
                             omega_B * self.gyro_scale)
        measured = measured + self.gyro_bias
        measured = measured + (self.gyro_arw / math.sqrt(dt_s)) * \
            rng.normal(size=measured.shape)
        measured = np.clip(measured, -self.gyro_range, self.gyro_range)
        return np.round(measured / self.gyro_resolution) * self.gyro_resolution

    def read_magnetometer(self, b_B: np.ndarray,
                          rng: np.random.Generator) -> np.ndarray:
        measured = np.einsum("nij,nj->ni", self.mag_align, b_B * self.mag_scale)
        measured = measured + self.mag_bias
        measured = measured + self.mag_noise * rng.normal(size=measured.shape)
        return np.clip(measured, -self.mag_range, self.mag_range)


def make_imu(cfg: MissionConfig, n_trials: int,
             rng: np.random.Generator) -> Imu:
    spec = cfg.detumble.imu
    gyro, mag = spec.gyro, spec.magnetometer
    deg = math.radians(1.0)
    # Angle random walk deg/sqrt(hr) -> rad/s/sqrt(s); bias stability
    # deg/hr -> a rate random walk via the usual tau = 1 hr correlation time.
    arw = math.radians(float(gyro.angle_random_walk_deg_per_sqrt_hr)) / 60.0
    bias_stab = math.radians(float(gyro.bias_stability_deg_per_hr)) / 3600.0
    rrw = bias_stab / math.sqrt(3600.0)
    return Imu(
        gyro_bias=rng.normal(
            scale=math.radians(float(gyro.turn_on_bias_deg_per_hr)) / 3600.0,
            size=(n_trials, 3)),
        gyro_scale=1.0 + rng.normal(scale=float(gyro.scale_factor_error),
                                    size=(n_trials, 3)),
        gyro_align=small_rotation_matrices(rng, n_trials,
                                           float(gyro.misalignment_deg)),
        gyro_arw=arw,
        gyro_rrw=rrw,
        gyro_resolution=float(gyro.resolution_deg_per_s) * deg,
        gyro_range=float(gyro.range_deg_per_s) * deg,
        mag_bias=rng.normal(scale=float(mag.turn_on_bias_nt) * 1e-9,
                            size=(n_trials, 3)),
        mag_scale=1.0 + rng.normal(scale=float(mag.scale_factor_error),
                                   size=(n_trials, 3)),
        mag_align=small_rotation_matrices(rng, n_trials,
                                          float(mag.misalignment_deg)),
        mag_noise=float(mag.noise_nt) * 1e-9,
        mag_range=float(mag.range_nt) * 1e-9,
    )


# ---------------------------------------------------------------------------
# Actuator, array geometry and the control law
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Magnetorquers:
    """Three orthogonal coils with per-axis limits and mounting error.

    ``m_max`` comes from config/spacecraft.yaml (0.2 A m^2 on each axis).
    Saturation is applied per axis, not to the vector magnitude, because that
    is what the hardware does -- and it means a saturated command points
    somewhere slightly different from where the controller asked, which the
    truth model then propagates honestly.
    """

    m_max: np.ndarray        # (3,) A m^2
    scale: np.ndarray        # (N,3)
    align: np.ndarray        # (N,3,3)

    def realise(self, m_cmd: np.ndarray) -> np.ndarray:
        """Commanded dipole -> dipole the coils actually produce, body axes."""
        saturated = np.clip(m_cmd, -self.m_max, self.m_max)
        return np.einsum("nij,nj->ni", self.align, saturated * self.scale)


def make_magnetorquers(cfg: MissionConfig, n_trials: int,
                       rng: np.random.Generator) -> Magnetorquers:
    from .adcs import dipole_vector
    spec = cfg.detumble.magnetorquer
    return Magnetorquers(
        m_max=dipole_vector(cfg),
        scale=1.0 + rng.normal(scale=float(spec.scale_factor_error),
                               size=(n_trials, 3)),
        align=small_rotation_matrices(rng, n_trials,
                                      float(spec.misalignment_deg)),
    )


@dataclasses.dataclass
class ArrayGeometry:
    """The solar array under test, reduced to what pointing cares about."""

    normals: np.ndarray       # (P,3) body frame, unit
    peak_w: np.ndarray        # (P,)
    peak_total_w: float
    name: str

    @property
    def power_axis(self) -> np.ndarray:
        """Power-weighted mean panel normal -- the axis to aim at the Sun.

        For an array whose panels are all lit at once, this is not a heuristic:
        setting the derivative of ``sum_p w_p cos(angle to panel p)`` to zero
        puts the optimum exactly along the power-weighted normal. For the
        baseline 135 deg configuration it lands 30.2 deg off +y, which is the
        true optimum to the digit.
        """
        return unit(self.peak_w @ self.normals)

    def capture_fraction(self, sun_hat_B: np.ndarray,
                         shadow: np.ndarray) -> np.ndarray:
        """Instantaneous array output as a fraction of the peak rating."""
        cos_incidence = np.clip(sun_hat_B @ self.normals.T, 0.0, None)
        return (cos_incidence @ self.peak_w) * shadow / self.peak_total_w

    def best_capture_fraction(self, samples: int = 20000) -> float:
        """Best capture any attitude can reach -- the fair yardstick.

        A body-fixed array cannot reach 1.0 unless every panel shares a
        normal. For the baseline 135 deg wing plus body panel the ceiling is
        0.93, so scoring the controller against 1.0 would charge it 7 % for
        geometry it cannot do anything about.
        """
        indices = np.arange(samples) + 0.5
        z = 1.0 - 2.0 * indices / samples
        radius = np.sqrt(np.clip(1.0 - z * z, 0.0, None))
        phi = np.pi * (1.0 + 5.0 ** 0.5) * indices
        dirs = np.stack([radius * np.cos(phi), radius * np.sin(phi), z], -1)
        return float(np.max(self.capture_fraction(dirs, np.ones(samples))))


def make_array(cfg: MissionConfig, option_name: str) -> ArrayGeometry:
    """Read one solar array option out of config/spacecraft.yaml.

    ``peak_w`` there is the total for the named panel group, not the per-panel
    figure, so the ``count`` field must not be multiplied back in -- doing so
    would double the deployable wing's weight in the pointing target and move
    the aim point several degrees.
    """
    option = cfg.spacecraft.solar_array_options[option_name]
    normals, weights = [], []
    for panel in option.panels:
        normals.append(unit(np.asarray(panel.normal, dtype=float)))
        weights.append(float(panel.peak_w))
    return ArrayGeometry(normals=np.asarray(normals),
                         peak_w=np.asarray(weights),
                         peak_total_w=float(option.peak_total_w),
                         name=option_name)


MODE_DETUMBLE = 0
MODE_SUN = 1


def commanded_dipole(mode: np.ndarray, omega_meas: np.ndarray,
                     b_meas: np.ndarray, sun_meas: np.ndarray,
                     sun_valid: np.ndarray, target_axis_B: np.ndarray,
                     k_detumble: float, k_p: float, k_d: float,
                     m_max: np.ndarray) -> np.ndarray:
    """The entire control law. Two modes, one projection, nothing else.

    DETUMBLE:  tau_desired = -k_detumble * omega
    SUN:       tau_desired = k_p (a x s) - k_d omega,  a = array power axis
               falling back to pure rate damping whenever the Sun fix is
               invalid (eclipse, or too few lit channels).

    Both then go through the same magnetic projection

        m = (B x tau_desired) / |B|^2

    which is the minimum-norm dipole whose cross product with B is the part of
    ``tau_desired`` perpendicular to B. The component along B is unreachable
    and is dropped -- not redirected, not scaled up to compensate. That single
    line is where magnetic under-actuation enters, and everything awkward
    about magnetorquer-only control follows from it.

    ``a x s`` is the standard two-axis attitude error: its magnitude is the
    sine of the angle between the array axis and the Sun and it vanishes at
    both 0 and 180 deg. The rate term is what makes 180 deg unstable and 0 deg
    stable, so the -k_d omega is load bearing, not just damping.

    Rotation about the array axis itself is left completely uncommanded. It
    does not affect power, and not controlling it means never fighting the
    field for authority that buys nothing.
    """
    tau_damp = -k_detumble * omega_meas
    tau_sun = k_p * np.cross(target_axis_B, sun_meas) - k_d * omega_meas
    tau_hold = -k_d * omega_meas
    in_sun_mode = (mode == MODE_SUN)[:, None]
    tau_desired = np.where(in_sun_mode,
                           np.where(sun_valid[:, None], tau_sun, tau_hold),
                           tau_damp)
    b_sq = np.sum(b_meas * b_meas, axis=-1, keepdims=True)
    m_cmd = np.divide(np.cross(b_meas, tau_desired), b_sq,
                      out=np.zeros_like(b_meas), where=b_sq > 0)
    return np.clip(m_cmd, -m_max, m_max)


# ---------------------------------------------------------------------------
# Truth dynamics
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DynamicsContext:
    """Everything the derivative needs that is fixed across a control step."""

    inertia: np.ndarray            # (3,3)
    inertia_inv: np.ndarray        # (3,3)
    r_hat_N: np.ndarray            # (N,3)
    r_mag: np.ndarray              # (N,)
    v_hat_N: np.ndarray            # (N,3)
    v_mag: np.ndarray              # (N,)
    b_N: np.ndarray                # (N,3)
    dipole_B: np.ndarray           # (N,3) actual coil dipole this substep
    residual_B: np.ndarray         # (N,3) bus residual dipole
    cp_offset_B: np.ndarray        # (N,3) centre of pressure offset
    face_areas: np.ndarray         # (3,)
    drag_coefficient: float
    density: float
    use_gravity_gradient: bool
    use_residual_dipole: bool
    use_aerodynamic: bool


def body_torques(q: np.ndarray, ctx: DynamicsContext) -> tuple[np.ndarray, np.ndarray]:
    """Control torque and total external torque in body axes, N m.

    Returned separately so the control torque can be logged on its own; the
    dynamics only ever uses the sum.
    """
    dcm = quat_to_dcm(q)
    b_B = rotate_to_body(dcm, ctx.b_N)
    tau_ctrl = np.cross(ctx.dipole_B, b_B)
    tau = tau_ctrl

    if ctx.use_gravity_gradient:
        r_hat_B = rotate_to_body(dcm, ctx.r_hat_N)
        tau = tau + (3.0 * MU_EARTH / ctx.r_mag ** 3)[:, None] * \
            np.cross(r_hat_B, r_hat_B @ ctx.inertia.T)
    if ctx.use_residual_dipole:
        tau = tau + np.cross(ctx.residual_B, b_B)
    if ctx.use_aerodynamic:
        v_hat_B = rotate_to_body(dcm, ctx.v_hat_N)
        # Projected area of the box normal to the flow.
        area = np.abs(v_hat_B) @ ctx.face_areas
        force = (0.5 * ctx.density * ctx.drag_coefficient * area
                 * ctx.v_mag ** 2)[:, None] * (-v_hat_B)
        tau = tau + np.cross(ctx.cp_offset_B, force)
    return tau_ctrl, tau


def _derivative(q: np.ndarray, omega: np.ndarray,
                ctx: DynamicsContext) -> tuple[np.ndarray, np.ndarray]:
    _, tau = body_torques(q, ctx)
    ang_mom = omega @ ctx.inertia.T
    omega_dot = (tau - np.cross(omega, ang_mom)) @ ctx.inertia_inv.T
    return quat_derivative(q, omega), omega_dot


def rk4_step(q: np.ndarray, omega: np.ndarray, dt_s: float,
             ctx: DynamicsContext) -> tuple[np.ndarray, np.ndarray]:
    """One classical RK4 step of the coupled kinematics and Euler equations.

    The inertial-frame quantities in ``ctx`` are held over the step, but every
    body-frame quantity -- and in particular the field in body axes, which is
    what sets the control torque -- is recomputed from the stage attitude. At
    20 deg/s the vehicle turns 5 deg per 0.25 s step, so freezing the body
    field instead would be a real error; freezing the *inertial* field over
    the same step moves the spacecraft 2 km along an orbit of radius 6800 km
    and changes the field by about 0.1 %.
    """
    k1q, k1w = _derivative(q, omega, ctx)
    k2q, k2w = _derivative(q + 0.5 * dt_s * k1q, omega + 0.5 * dt_s * k1w, ctx)
    k3q, k3w = _derivative(q + 0.5 * dt_s * k2q, omega + 0.5 * dt_s * k2w, ctx)
    k4q, k4w = _derivative(q + dt_s * k3q, omega + dt_s * k3w, ctx)
    q_next = q + (dt_s / 6.0) * (k1q + 2 * k2q + 2 * k3q + k4q)
    omega_next = omega + (dt_s / 6.0) * (k1w + 2 * k2w + 2 * k3w + k4w)
    return quat_normalize(q_next), omega_next


# ---------------------------------------------------------------------------
# The Monte Carlo
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class MonteCarloResult:
    """Downsampled histories plus the per-trial and aggregate metrics."""

    sensor_geometry: str
    array_option: str
    n_trials: int
    t_s: np.ndarray                  # (T,)
    rate_deg_s: np.ndarray           # (T,N) true body rate magnitude
    capture_sunlit: np.ndarray       # (T,N) array output fraction if lit
    capture_actual: np.ndarray       # (T,N) with eclipse applied
    sun_error_deg: np.ndarray        # (T,N) array power axis to true Sun
    est_error_deg: np.ndarray        # (T,N) estimated vs true Sun, 3-D
    est_inplane_error_deg: np.ndarray  # (T,N) same, within the sensed subspace
    sun_valid: np.ndarray            # (T,N) bool
    shadow: np.ndarray               # (T,N)
    mode: np.ndarray                 # (T,N) 0 detumble, 1 sun acquisition
    dipole_fraction: np.ndarray      # (T,N) |m| / |m_max|
    best_capture: float
    per_trial: dict[str, np.ndarray]
    summary: dict[str, Any]


def _first_sustained(mask: np.ndarray, sample_dt: float,
                     hold_s: float) -> np.ndarray:
    """First time each column of ``mask`` goes true and stays true.

    ``mask`` is (T,N). Returns (N,) seconds, NaN where it never happens or
    where the condition holds but not for the full ``hold_s`` before the run
    ends -- an unfinished hold is not a pass.
    """
    n_hold = max(1, int(round(hold_s / sample_dt)))
    n_t = mask.shape[0]
    if n_t < n_hold:
        return np.full(mask.shape[1], np.nan)
    # Rolling AND via a cumulative count of failures.
    fails = np.cumsum(~mask, axis=0)
    padded = np.vstack([np.zeros((1, mask.shape[1]), dtype=fails.dtype), fails])
    window_fails = padded[n_hold:] - padded[:-n_hold]
    ok = window_fails == 0                      # (T-n_hold+1, N)
    any_ok = ok.any(axis=0)
    first = np.argmax(ok, axis=0).astype(float)
    first[~any_ok] = np.nan
    return first * sample_dt


def run_monte_carlo(cfg: MissionConfig, sensor_geometry: str,
                    env: EnvironmentEnsemble,
                    duration_s: float | None = None,
                    array_option: str | None = None,
                    seed: int | None = None,
                    progress=None) -> MonteCarloResult:
    """Fly a dispersed detumble ensemble with one sun sensor layout.

    Every trial is integrated simultaneously: the state is ``(n_trials, ...)``
    and one call to :func:`rk4_step` advances the whole ensemble, so the cost
    is set by the number of time steps rather than the number of trials. A
    200-trial six-hour run is a couple of minutes.

    ``env`` carries the Basilisk-propagated environment and the per-trial
    assignment into it; build it with :func:`build_environment_ensemble`.
    Passing the same ``env`` to every sensor geometry is deliberate -- the
    layouts are then compared over identical orbits, identical field histories
    and identical eclipse timing, so the difference between them is the
    sensors and nothing else.
    """
    dcfg = cfg.detumble
    mc = dcfg.monte_carlo
    n_trials = env.n_trials
    duration_s = float(duration_s if duration_s is not None else mc.duration_s)
    array_option = array_option or str(mc.array_option)
    rng = np.random.default_rng(int(seed if seed is not None else mc.seed))

    dt_s = float(mc.time_step_s)
    control_period = float(dcfg.magnetorquer.control_period_s)
    measure_window = float(dcfg.magnetorquer.measure_window_s)
    n_sub = int(round(control_period / dt_s))
    n_measure_sub = int(round(measure_window / dt_s))
    if n_sub < 1 or not math.isclose(n_sub * dt_s, control_period, rel_tol=1e-9):
        raise ValueError("control_period_s must be a whole multiple of time_step_s")
    if not math.isclose(n_measure_sub * dt_s, measure_window, rel_tol=1e-9):
        raise ValueError(
            f"measure_window_s ({measure_window} s) must be a whole multiple "
            f"of time_step_s ({dt_s} s), otherwise the coils-off window the "
            f"magnetometer is read in silently rounds away")
    sample_step = float(mc.sample_step_s)
    n_control = int(round(duration_s / control_period))
    sample_every = int(round(sample_step / control_period))

    # -- hardware ------------------------------------------------------------
    boresights = np.asarray(dcfg.sensor_geometries[sensor_geometry].boresights,
                            dtype=float)
    solar_constant = float(cfg.env.solar_constant_w_m2)
    sensors = make_sun_sensors(cfg, boresights, n_trials, rng, solar_constant,
                               name=sensor_geometry)
    imu = make_imu(cfg, n_trials, rng)
    coils = make_magnetorquers(cfg, n_trials, rng)
    array = make_array(cfg, array_option)
    best_capture = array.best_capture_fraction()

    # Projector onto the subspace the sensor normals can see. Used only to
    # separate "the estimate is noisy" from "the geometry cannot see that
    # direction at all"; the flight algorithm never uses it.
    _, sing, vt = np.linalg.svd(sensors.boresights, full_matrices=False)
    rank = int(np.sum(sing > 1e-9 * sing[0]))
    basis = vt[:rank]
    projector = basis.T @ basis

    target_axis = array.power_axis
    if str(dcfg.control.sun_target_axis) != "array":
        target_axis = unit(np.asarray(dcfg.control.sun_target_axis, dtype=float))
    target_axis_B = np.broadcast_to(target_axis, (n_trials, 3))

    # -- vehicle -------------------------------------------------------------
    bus = cfg.spacecraft.bus
    inertia = np.diag([float(bus.inertia_kgm2.xx), float(bus.inertia_kgm2.yy),
                       float(bus.inertia_kgm2.zz)])
    dims = np.array([float(bus.dimensions_m.x), float(bus.dimensions_m.y),
                     float(bus.dimensions_m.z)])
    face_areas = np.array([dims[1] * dims[2], dims[0] * dims[2], dims[0] * dims[1]])
    residual_B = (float(bus.residual_dipole_am2)
                  * random_unit_vectors(rng, n_trials))
    cp_offset_B = float(bus.cp_cm_offset_m) * random_unit_vectors(rng, n_trials)

    env_cfg = dcfg.environment
    dist_cfg = env_cfg.disturbances
    albedo = (float(env_cfg.albedo.reflectivity)
              if bool(env_cfg.albedo.enabled) else None)

    ctx = DynamicsContext(
        inertia=inertia, inertia_inv=np.linalg.inv(inertia),
        r_hat_N=np.zeros((n_trials, 3)), r_mag=np.zeros(n_trials),
        v_hat_N=np.zeros((n_trials, 3)), v_mag=np.zeros(n_trials),
        b_N=np.zeros((n_trials, 3)), dipole_B=np.zeros((n_trials, 3)),
        residual_B=residual_B, cp_offset_B=cp_offset_B, face_areas=face_areas,
        drag_coefficient=float(bus.drag_coefficient),
        density=float(dist_cfg.atmospheric_density_kg_m3),
        use_gravity_gradient=bool(dist_cfg.gravity_gradient),
        use_residual_dipole=bool(dist_cfg.residual_dipole),
        use_aerodynamic=bool(dist_cfg.aerodynamic),
    )

    # -- initial state -------------------------------------------------------
    rate_lo, rate_hi = [float(v) for v in mc.initial_rate_deg_per_s]
    rate0 = np.radians(rng.uniform(rate_lo, rate_hi, size=n_trials))
    omega = random_unit_vectors(rng, n_trials) * rate0[:, None]
    q = random_quaternions(rng, n_trials)

    # -- mode state ----------------------------------------------------------
    control_cfg = dcfg.control
    enter_rate = math.radians(float(control_cfg.sun_mode_enter_deg_per_s))
    exit_rate = math.radians(float(control_cfg.sun_mode_exit_deg_per_s))
    dwell_steps = int(round(float(control_cfg.sun_mode_dwell_s) / control_period))
    mode = np.zeros(n_trials, dtype=np.int8)
    dwell = np.zeros(n_trials, dtype=np.int32)
    k_detumble = float(control_cfg.k_detumble_nms)
    k_p = float(control_cfg.k_p_sun_nm)
    k_d = float(control_cfg.k_d_sun_nms)
    m_max = coils.m_max

    # -- history buffers -----------------------------------------------------
    n_samples = n_control // sample_every + 1
    hist = {name: np.zeros((n_samples, n_trials), dtype=dtype)
            for name, dtype in [("rate", float), ("capture", float),
                                ("sun_error", float), ("est_error", float),
                                ("est_inplane", float), ("valid", bool),
                                ("shadow", float), ("mode", np.int8),
                                ("dipole", float)]}
    t_hist = np.zeros(n_samples)
    sample_index = 0

    for step in range(n_control):
        t_now = step * control_period

        # --- environment, interpolated from Basilisk and held over the
        #     control period -------------------------------------------------
        sample = env.sample(t_now)
        r_N = sample["r_N"]
        ctx.r_mag = np.linalg.norm(r_N, axis=-1)
        ctx.r_hat_N = r_N / ctx.r_mag[:, None]
        ctx.v_mag = np.linalg.norm(sample["v_N"], axis=-1)
        ctx.v_hat_N = sample["v_N"] / ctx.v_mag[:, None]
        ctx.b_N = sample["b_N"]
        sun_hat_N = sample["sun_hat_N"]
        shadow = sample["shadow"]
        solar_irradiance = solar_constant * (AU / sample["sun_dist_m"]) ** 2

        # --- coils off: the measurement window -----------------------------
        ctx.dipole_B = np.zeros((n_trials, 3))
        for _ in range(n_measure_sub):
            q, omega = rk4_step(q, omega, dt_s, ctx)

        # --- read the sensors, coils quiet ---------------------------------
        dcm = quat_to_dcm(q)
        b_B = rotate_to_body(dcm, ctx.b_N)
        sun_B = rotate_to_body(dcm, sun_hat_N)
        nadir_B = rotate_to_body(dcm, -ctx.r_hat_N)
        omega_meas = imu.read_gyro(omega, control_period, rng)
        b_meas = imu.read_magnetometer(b_B, rng)
        currents = sensors.measure(sun_B, nadir_B, shadow, solar_irradiance,
                                   ctx.r_mag, albedo, rng)
        sun_meas, sun_valid = sensors.estimate_sun(currents)
        sun_valid = sun_valid & (shadow > 0.5)

        # --- mode logic: two thresholds and a dwell timer -------------------
        rate_meas = np.linalg.norm(omega_meas, axis=-1)
        dwell = np.where(rate_meas < enter_rate, dwell + 1, 0)
        to_sun = (mode == MODE_DETUMBLE) & (dwell >= dwell_steps)
        to_detumble = (mode == MODE_SUN) & (rate_meas > exit_rate)
        mode = np.where(to_sun, MODE_SUN, np.where(to_detumble, MODE_DETUMBLE, mode))
        dwell = np.where(to_detumble, 0, dwell)

        m_cmd = commanded_dipole(mode, omega_meas, b_meas, sun_meas, sun_valid,
                                 target_axis_B, k_detumble, k_p, k_d, m_max)

        # --- log the measured state, before this period's torque ------------
        if step % sample_every == 0 and sample_index < n_samples:
            hist["rate"][sample_index] = np.degrees(np.linalg.norm(omega, axis=-1))
            hist["capture"][sample_index] = array.capture_fraction(
                sun_B, np.ones(n_trials))
            hist["sun_error"][sample_index] = np.degrees(np.arccos(np.clip(
                np.sum(target_axis_B * sun_B, axis=-1), -1, 1)))
            hist["est_error"][sample_index] = np.degrees(np.arccos(np.clip(
                np.sum(sun_meas * sun_B, axis=-1), -1, 1)))
            projected = unit(sun_B @ projector.T)
            hist["est_inplane"][sample_index] = np.degrees(np.arccos(np.clip(
                np.sum(sun_meas * projected, axis=-1), -1, 1)))
            hist["valid"][sample_index] = sun_valid
            hist["shadow"][sample_index] = shadow
            hist["mode"][sample_index] = mode
            hist["dipole"][sample_index] = (np.linalg.norm(m_cmd, axis=-1)
                                            / np.linalg.norm(m_max))
            t_hist[sample_index] = t_now
            sample_index += 1
            if progress is not None:
                progress(t_now, duration_s)

        # --- coils on for the rest of the period ---------------------------
        ctx.dipole_B = coils.realise(m_cmd)
        for _ in range(n_sub - n_measure_sub):
            q, omega = rk4_step(q, omega, dt_s, ctx)

    return _reduce(cfg, sensor_geometry, array, best_capture, rank,
                   t_hist[:sample_index],
                   {k: v[:sample_index] for k, v in hist.items()},
                   sample_step, n_trials, duration_s, env)


def _pct(values: np.ndarray, q: float) -> float:
    finite = values[np.isfinite(values)]
    return float(np.percentile(finite, q)) if finite.size else float("nan")


def _reduce(cfg: MissionConfig, sensor_geometry: str, array: ArrayGeometry,
            best_capture: float, sensed_rank: int, t_s: np.ndarray,
            hist: dict[str, np.ndarray], sample_step: float, n_trials: int,
            duration_s: float, env: EnvironmentEnsemble) -> MonteCarloResult:
    """Turn the histories into per-trial numbers and an aggregate summary."""
    metrics = cfg.detumble.metrics
    rate = hist["rate"]
    capture = hist["capture"]
    shadow = hist["shadow"]
    capture_actual = capture * shadow

    detumbled = rate < float(metrics.detumble_threshold_deg_per_s)
    t_detumble = _first_sustained(detumbled, sample_step,
                                  float(metrics.detumble_hold_s))

    # Sun acquisition is judged on the pointing the array achieves, not on the
    # power it happens to be making: a trial that acquires the Sun just before
    # entering eclipse has acquired it. `capture` is therefore the sunlit
    # potential, and eclipse enters only the energy number below.
    acquired = (capture / best_capture) >= float(metrics.power_capture_threshold)
    t_acquire = _first_sustained(acquired, sample_step,
                                 float(metrics.power_capture_hold_s))

    window = int(round(float(metrics.steady_state_window_s) / sample_step))
    window = max(1, min(window, len(t_s)))
    tail = slice(len(t_s) - window, len(t_s))
    lit_tail = shadow[tail] > 0.5

    def tail_mean(values: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
        block = values[tail]
        if mask is None:
            return block.mean(axis=0)
        counts = mask.sum(axis=0)
        total = np.where(mask, block, 0.0).sum(axis=0)
        return np.divide(total, counts, out=np.full(n_trials, np.nan),
                         where=counts > 0)

    valid_lit = hist["valid"][tail] & lit_tail
    per_trial = {
        "detumble_time_s": t_detumble,
        "sun_acquire_time_s": t_acquire,
        "steady_capture_fraction": tail_mean(capture),
        "steady_capture_normalised": tail_mean(capture) / best_capture,
        "steady_orbit_average_capture": tail_mean(capture_actual),
        "steady_sun_error_deg": tail_mean(hist["sun_error"]),
        "sun_fix_availability": (valid_lit.sum(axis=0)
                                 / np.maximum(lit_tail.sum(axis=0), 1)),
        "sun_estimate_error_deg": tail_mean(hist["est_error"], valid_lit),
        "sun_estimate_inplane_error_deg": tail_mean(hist["est_inplane"], valid_lit),
        "mean_dipole_fraction": hist["dipole"].mean(axis=0),
        "final_rate_deg_s": rate[-1],
        "initial_rate_deg_s": rate[0],
    }

    summary: dict[str, Any] = {
        "sensor_geometry": sensor_geometry,
        "array_option": array.name,
        "n_trials": n_trials,
        "duration_s": duration_s,
        "sensed_subspace_rank": sensed_rank,
        "environment_cases": int(env.r_BN_N.shape[0]),
        "beta_angle_deg_min": float(np.min(env.beta_deg)),
        "beta_angle_deg_max": float(np.max(env.beta_deg)),
        "eclipse_fraction": float(np.mean(hist["shadow"] < 0.5)),
        "best_capture_fraction": best_capture,
        "detumble_success_rate": float(np.mean(np.isfinite(t_detumble))),
        "sun_acquire_success_rate": float(np.mean(np.isfinite(t_acquire))),
    }
    for key, values in per_trial.items():
        summary[f"{key}_median"] = _pct(values, 50)
        summary[f"{key}_p05"] = _pct(values, 5)
        summary[f"{key}_p95"] = _pct(values, 95)

    return MonteCarloResult(
        sensor_geometry=sensor_geometry,
        array_option=array.name,
        n_trials=n_trials,
        t_s=t_s,
        rate_deg_s=rate,
        capture_sunlit=capture,
        capture_actual=capture_actual,
        sun_error_deg=hist["sun_error"],
        est_error_deg=hist["est_error"],
        est_inplane_error_deg=hist["est_inplane"],
        sun_valid=hist["valid"],
        shadow=shadow,
        mode=hist["mode"],
        dipole_fraction=hist["dipole"],
        best_capture=best_capture,
        per_trial=per_trial,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Sky coverage: a property of a sensor layout alone, no dynamics involved
# ---------------------------------------------------------------------------


def sky_coverage(cfg: MissionConfig, boresights: np.ndarray,
                 samples: int = 40000) -> dict[str, Any]:
    """How much of the sky a layout can see, and how well it sees it.

    Sweeps Sun directions uniformly over the sphere and, for each, records how
    many channels are lit and how far the noiseless least squares estimate
    lands from the truth. This isolates the geometry from everything else in
    the simulation: no albedo, no noise, no dynamics.
    """
    boresights = unit(np.asarray(boresights, dtype=float))
    indices = np.arange(samples) + 0.5
    z = 1.0 - 2.0 * indices / samples
    radius = np.sqrt(np.clip(1.0 - z * z, 0.0, None))
    phi = np.pi * (1.0 + 5.0 ** 0.5) * indices
    dirs = np.stack([radius * np.cos(phi), radius * np.sin(phi), z], -1)

    cos_incidence = np.clip(dirs @ boresights.T, 0.0, None)
    threshold = math.cos(math.radians(88.6))    # the valid_fraction cut
    lit = cos_incidence > threshold
    n_lit = lit.sum(axis=1)

    gram = np.einsum("ns,si,sj->nij", lit.astype(float), boresights, boresights)
    gram_reg = gram + 1e-9 * np.eye(3)

    def solve(readings: np.ndarray) -> np.ndarray:
        rhs = np.where(lit, readings, 0.0) @ boresights
        return unit(np.linalg.solve(gram_reg, rhs[..., None])[..., 0])

    est = solve(cos_incidence)
    error = np.degrees(np.arccos(np.clip(np.sum(est * dirs, axis=-1), -1, 1)))
    error[n_lit < 2] = np.nan

    # The subspace the normals span, and the truth projected into it. For a
    # coplanar layout the 3-D error above is dominated by the component the
    # sensors are blind to, which says nothing about how well they resolve the
    # directions they CAN see -- so that is measured separately.
    left, sing, vt = np.linalg.svd(boresights, full_matrices=False)
    rank = int(np.sum(sing > 1e-9 * sing[0]))
    basis = vt[:rank]
    in_plane_truth = unit(dirs @ (basis.T @ basis).T)
    in_plane_error = np.degrees(np.arccos(
        np.clip(np.sum(est * in_plane_truth, axis=-1), -1, 1)))
    in_plane_error[n_lit < 2] = np.nan
    del left

    # Conditioning: how much a reading error is amplified into a direction
    # error. This is where two layouts with identical lit-channel counts come
    # apart -- the canted pair has two of its four normals only 45 deg apart,
    # so over the sky directions that fall between the pairs it is solving for
    # a direction from what is effectively one useful reading.
    lit_sing = np.linalg.svd(gram, compute_uv=False)
    amplification = 1.0 / np.sqrt(np.maximum(lit_sing[:, rank - 1], 1e-12))
    # Undefined where fewer channels are lit than the layout's rank -- the
    # solve is degenerate there rather than merely ill-conditioned, and that
    # case is already counted by `fraction_three_or_more_lit`.
    amplification[n_lit < rank] = np.nan

    # Same solve with a reading perturbation, to put the conditioning in
    # degrees. 1 % of a normal-incidence reading is a stand-in for the
    # combined quantisation, dark-current and albedo error budget.
    noise_rng = np.random.default_rng(0)
    noisy = solve(cos_incidence + noise_rng.normal(scale=0.01, size=cos_incidence.shape))
    noisy_error = np.degrees(np.arccos(
        np.clip(np.sum(noisy * in_plane_truth, axis=-1), -1, 1)))
    noisy_error[n_lit < 2] = np.nan

    def stat(values: np.ndarray, q: float) -> float:
        finite = values[np.isfinite(values)]
        return float(np.percentile(finite, q)) if finite.size else float("nan")

    return {
        "n_sensors": int(len(boresights)),
        "sensed_subspace_rank": rank,
        "fraction_two_or_more_lit": float(np.mean(n_lit >= 2)),
        "fraction_three_or_more_lit": float(np.mean(n_lit >= 3)),
        "fraction_dark": float(np.mean(n_lit == 0)),
        "mean_lit_channels": float(np.mean(n_lit)),
        "geometric_error_median_deg": stat(error, 50),
        "geometric_error_p95_deg": stat(error, 95),
        "geometric_error_max_deg": float(np.nanmax(error)),
        "in_plane_error_median_deg": stat(in_plane_error, 50),
        "in_plane_error_p95_deg": stat(in_plane_error, 95),
        "noise_amplification_median": stat(amplification, 50),
        "noise_amplification_p95": stat(amplification, 95),
        "one_percent_noise_error_median_deg": stat(noisy_error, 50),
        "one_percent_noise_error_p95_deg": stat(noisy_error, 95),
    }
