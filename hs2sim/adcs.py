"""Magnetorquer authority, slew times and duty cycle.

The question is how much magnetorquers throttle operations. Three things
matter, and all of them come out of the magnetic field history that Basilisk
produced:

1. **Torque is never available about the field direction.** The achievable
   torque ``m x B`` always lies in the plane perpendicular to ``B``, so there
   is *no* authority about an axis parallel to the field, and only partial
   authority about anything close to it. The maximum torque about a unit axis
   ``e``, over a dipole box ``|m_i| <= m_i^max``, is

       tau_e^max = max_m  e . (m x B) = max_m  m . (B x e) = sum_i m_i^max |(B x e)_i|

   which is zero exactly when ``e`` is parallel to ``B``, as it must be. Note
   this is the achievable *projection* onto ``e``; a pure torque about ``e``
   with no cross-axis component exists only when ``e`` is perpendicular to
   ``B``. Magnetorquer-only slews accept the cross-axis term and let it wash
   out as the field rotates, which is what the slew model below assumes.

2. **Slew time is not sqrt(angle x inertia / torque).** That closed form
   assumes constant authority. Here the authority about the slew eigenaxis
   varies from zero to full twice per orbit, so a slew that starts with its
   eigenaxis along the field simply cannot begin -- it waits for the geometry
   to improve. ``slew_time_eigenaxis`` therefore integrates a bang-bang
   profile forward through the real field history instead of evaluating a
   formula, and the constant-torque version is kept only as a reference point
   to show how optimistic it is.

3. **Disturbances have to be absorbed too.** Gravity gradient, aerodynamic and
   residual-dipole torques all have to fit inside the same budget, otherwise
   the actuators saturate and pointing is lost.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from .config import MissionConfig
from .environment import EnvironmentResult, MU_EARTH

MU0 = 4e-7 * math.pi


def pointing_margin_deg(cfg: MissionConfig) -> float:
    """Buffer every keep-out has to be enforced with, in degrees.

    A commanded attitude sitting exactly on a keep-out boundary is not safe.
    Two independent things move the real boresight away from where the flight
    software believes it is:

    * **Control error** -- the true attitude differs from the commanded one.
      Magnetorquers produce ``m x B`` and so have no authority about the field
      direction; the vehicle is instantaneously under-actuated and this term
      dominates.
    * **Knowledge error** -- the estimated attitude differs from the true one,
      set by the star tracker and its mounting alignment.

    Both push the same way as far as a keep-out is concerned: the true
    boresight can be anywhere within their combination of where the estimate
    says it is, in *any* direction. So the cone is enforced at
    ``exclusion + margin`` and the usable attitude set shrinks from every side.

    ``sum`` is the worst case and the default, because the requirement is
    stated absolutely rather than statistically. ``rss`` treats the two as
    independent random errors instead.
    """
    adcs_cfg = cfg.spacecraft.adcs
    control = float(adcs_cfg.control_error_deg)
    knowledge = float(adcs_cfg.knowledge_error_deg)
    rule = str(getattr(adcs_cfg, "pointing_error_combination", "sum")).lower()
    if rule == "rss":
        return math.hypot(control, knowledge)
    if rule == "sum":
        return control + knowledge
    raise ValueError(
        f"pointing_error_combination must be 'sum' or 'rss', got {rule!r}")


@dataclasses.dataclass
class TorqueAuthority:
    """Achievable control torque statistics over the propagation."""

    b_magnitude_nt: np.ndarray       # (N,) field magnitude
    max_torque_nm: np.ndarray        # (N,) best-case torque with full dipole
    axis_torque_nm: np.ndarray       # (N,3) torque available about each body axis
    mean_max_torque_nm: float
    min_max_torque_nm: float
    worst_axis_mean_nm: float


def dipole_vector(cfg: MissionConfig) -> np.ndarray:
    """Per-axis dipole capability from the magnetorquer list, A m^2."""
    m = np.zeros(3)
    for torquer in cfg.spacecraft.adcs.magnetorquers:
        axis = np.asarray(torquer.axis, dtype=float)
        axis = axis / np.linalg.norm(axis)
        m += np.abs(axis) * float(torquer.dipole_am2)
    return m


def available_torque_about(m_max: np.ndarray, b: np.ndarray,
                           axis: np.ndarray) -> np.ndarray:
    """Greatest torque obtainable about ``axis``, N m. Vectorised over time.

    ``e . (m x B) = m . (B x e)``, and maximising a linear function over the
    box ``|m_i| <= m_i^max`` puts every coil at its limit with the sign of the
    corresponding component::

        tau_e^max = sum_i m_i^max |(B x e)_i|

    Zero exactly when ``B`` is parallel to ``axis``, which is the property the
    whole model turns on.

    ``b`` is (N,3) in the same frame as ``axis`` and ``m_max``. Note the two
    must be in **body** axes for the per-coil limits to mean anything.
    """
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    return np.abs(np.cross(np.asarray(b, dtype=float), axis)) @ np.asarray(m_max)


def max_torque_magnitude(m_max: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Largest ``|m x B|`` available from the dipole box, N m.

    ``|m x B|`` is convex in ``m``, so its maximum over a box is attained at a
    vertex; there are only eight and they come in antipodal pairs, so four
    evaluations settle it exactly.
    """
    b = np.asarray(b, dtype=float)
    best = np.zeros(len(b))
    for sx, sy, sz in ((1, 1, 1), (1, 1, -1), (1, -1, 1), (-1, 1, 1)):
        m = np.asarray(m_max) * np.array([sx, sy, sz], dtype=float)
        best = np.maximum(best, np.linalg.norm(np.cross(m, b), axis=1))
    return best


def inertia_matrix(cfg: MissionConfig) -> np.ndarray:
    inertia = cfg.spacecraft.bus.inertia_kgm2
    return np.diag([float(inertia.xx), float(inertia.yy), float(inertia.zz)])


def torque_authority(cfg: MissionConfig, env: EnvironmentResult,
                     dcm_BN: np.ndarray | None = None) -> TorqueAuthority:
    """Control torque available over time.

    If an attitude history is supplied the field is expressed in body axes so
    per-axis authority is meaningful; otherwise the inertial field magnitude is
    used, which still bounds the total torque.
    """
    m = dipole_vector(cfg)
    b_N = env.b_field_N
    b_mag = np.linalg.norm(b_N, axis=1)

    if dcm_BN is not None:
        b_B = np.einsum("nij,nj->ni", dcm_BN, b_N)
    else:
        b_B = b_N

    # Torque available about each body axis, as an envelope over the dipole
    # box rather than the torque from one arbitrary corner of it.
    tau_abs = np.stack([available_torque_about(m, b_B, axis)
                        for axis in np.eye(3)], axis=1)
    max_torque = max_torque_magnitude(m, b_B)

    return TorqueAuthority(
        b_magnitude_nt=b_mag * 1e9,
        max_torque_nm=max_torque,
        axis_torque_nm=tau_abs,
        mean_max_torque_nm=float(np.mean(max_torque)),
        min_max_torque_nm=float(np.min(max_torque)),
        worst_axis_mean_nm=float(np.min(np.mean(tau_abs, axis=0))),
    )


def slew_time_s(angle_rad: float, inertia: float, torque_nm: float,
                margin: float = 1.3) -> float:
    """Time-optimal bang-bang slew time with a settling margin.

    Accelerate for half the angle, decelerate for the other half:
        theta/2 = 1/2 (tau/J) (t/2)^2   ->   t = 2 sqrt(theta J / tau)
    """
    if torque_nm <= 0:
        return math.inf
    return margin * 2.0 * math.sqrt(angle_rad * inertia / torque_nm)


def eigenaxis_inertia(inertia: np.ndarray, axis: np.ndarray) -> float:
    """Moment of inertia about an arbitrary axis, kg m^2."""
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    return float(axis @ inertia @ axis)


def slew_time_eigenaxis(torque_series: np.ndarray,
                        inertia_about_axis: float,
                        angle_rad: float,
                        dt_s: float,
                        start_index: int = 0,
                        margin: float = 1.3,
                        max_seconds: float = 6.0 * 3600.0) -> float:
    """Bang-bang slew time about one eigenaxis, through the real field history.

    ``torque_series`` is the authority about that eigenaxis at each sample --
    from ``available_torque_about`` -- so it already carries the twice-per-orbit
    collapse to zero as the field sweeps past the axis. The profile is
    integrated forward rather than solved in closed form, because the closed
    form assumes a constant torque that this vehicle never has:

        accelerate while the angle needed to stop is less than the angle left,
        otherwise decelerate.

    When the authority is zero the vehicle simply coasts -- if it has not
    started moving yet, it waits. That waiting is the whole point: a slew whose
    eigenaxis starts along the field is not impossible, it is *delayed* until
    the geometry rotates, and no constant-torque formula can show that.

    Returns seconds including the settling ``margin``, or ``inf`` if the slew
    has not completed within ``max_seconds``.
    """
    if angle_rad <= 0:
        return 0.0
    n = len(torque_series)
    theta = 0.0
    omega = 0.0
    elapsed = 0.0
    i = int(start_index)
    # A slew is finished when the vehicle is *at* the target and *at rest*.
    # Stopping the clock the moment the angle is reached lets it arrive still
    # rotating -- the discrete switch to braking lands up to a step late, so
    # there is always some residual rate -- and that silently under-reports
    # every manoeuvre by several percent.
    rest_tol = 1.0e-5           # rad/s, far below any pointing requirement
    while (theta < angle_rad or omega > rest_tol) and elapsed < max_seconds:
        alpha = float(torque_series[i % n]) / inertia_about_axis
        remaining = angle_rad - theta
        # Angle that would be swept while braking to rest at this authority.
        stopping = omega * omega / (2.0 * alpha) if alpha > 0.0 else math.inf
        # Past the target there is nothing to do but null the rate.
        braking = remaining <= 0.0 or stopping >= remaining
        rate = -alpha if braking else alpha
        # Advance with theta += w dt + a dt^2 / 2 rather than theta += w dt.
        # The cheap form is only first order and biases *every* slew fast --
        # 10 % at the 5 s sample step, which is the wrong way to be wrong when
        # the point of the model is to stop under-counting slew cost. This one
        # is exact whenever the authority is constant across the step.
        span = dt_s
        if braking and alpha > 0.0:
            # Do not integrate past the instant it comes to rest.
            span = min(dt_s, omega / alpha)
        theta += omega * span + 0.5 * rate * span * span
        omega = max(0.0, omega + rate * dt_s)
        elapsed += dt_s
        i += 1
    complete = theta >= angle_rad and omega <= rest_tol
    return margin * elapsed if complete else math.inf


def _fibonacci_axes(count: int) -> np.ndarray:
    """``count`` roughly-uniform unit vectors on the sphere."""
    k = np.arange(count) + 0.5
    phi = np.arccos(1.0 - 2.0 * k / count)
    theta = math.pi * (1.0 + 5.0 ** 0.5) * k
    return np.stack([np.cos(theta) * np.sin(phi),
                     np.sin(theta) * np.sin(phi),
                     np.cos(phi)], axis=1)


def slew_time_profile(cfg: MissionConfig, authority: TorqueAuthority,
                      angle_deg: float, env: EnvironmentResult | None = None,
                      n_axes: int = 24, n_starts: int = 16) -> dict[str, float]:
    """Slew-time distribution over eigenaxis direction and start time.

    A single "slew time" is a fiction for a magnetically actuated vehicle: the
    answer depends on which way you are turning relative to the field and on
    when you start. So the manoeuvre is integrated for a spread of eigenaxes
    and a spread of start phases, and the spread is reported.

    ``worst_axis_s`` is the case the constant-torque formula cannot represent
    at all: the eigenaxis starting parallel to the field, where authority is
    zero and the vehicle has to wait for the geometry to move.

    ``constant_torque_s`` is the old closed-form answer, kept for comparison.
    """
    inertia = inertia_matrix(cfg)
    margin = float(cfg.spacecraft.adcs.settle_margin)
    angle = math.radians(angle_deg)
    m = dipole_vector(cfg)

    reference = slew_time_s(angle, float(np.max(np.diag(inertia))),
                            float(np.median(authority.max_torque_nm)), margin)
    if env is None:
        return {"angle_deg": angle_deg, "constant_torque_s": reference}

    b = env.b_field_N
    dt = env.dt_s
    starts = np.linspace(0, len(b) - 1, n_starts, dtype=int)

    times: list[float] = []
    for axis in _fibonacci_axes(n_axes):
        series = available_torque_about(m, b, axis)
        j = eigenaxis_inertia(inertia, axis)
        for start in starts:
            times.append(slew_time_eigenaxis(series, j, angle, dt, int(start),
                                             margin))
    finite = np.array([t for t in times if math.isfinite(t)])

    # The pathological case, stated explicitly rather than left to sampling:
    # start each slew with its eigenaxis exactly along the field.
    aligned: list[float] = []
    for start in starts:
        axis = b[int(start)] / np.linalg.norm(b[int(start)])
        series = available_torque_about(m, b, axis)
        j = eigenaxis_inertia(inertia, axis)
        aligned.append(slew_time_eigenaxis(series, j, angle, dt, int(start),
                                           margin))
    aligned_finite = np.array([t for t in aligned if math.isfinite(t)])

    return {
        "angle_deg": angle_deg,
        "best_s": float(finite.min()) if finite.size else math.inf,
        "median_s": float(np.median(finite)) if finite.size else math.inf,
        "p90_s": float(np.percentile(finite, 90)) if finite.size else math.inf,
        "worst_s": float(finite.max()) if finite.size else math.inf,
        "worst_axis_s": (float(np.median(aligned_finite))
                         if aligned_finite.size else math.inf),
        "constant_torque_s": reference,
        "optimism_factor": (float(np.median(finite)) / reference
                            if finite.size and reference > 0 else math.inf),
        "unreachable_fraction": float(
            sum(1 for t in times if not math.isfinite(t)) / max(1, len(times))),
    }


# ---------------------------------------------------------------------------
# Disturbance torques
# ---------------------------------------------------------------------------

def gravity_gradient_torque(cfg: MissionConfig, env: EnvironmentResult,
                            worst_case: bool = True) -> np.ndarray:
    """Gravity-gradient torque magnitude, N m.

    Worst case (maximum principal-inertia difference at 45 deg to nadir):
        tau = 3 mu / (2 r^3) * |Iz - Ix|
    """
    inertia = inertia_matrix(cfg)
    spread = float(np.max(np.diag(inertia)) - np.min(np.diag(inertia)))
    r = np.linalg.norm(env.r_BN_N, axis=1)
    return 1.5 * MU_EARTH / r ** 3 * spread


def magnetic_disturbance_torque(cfg: MissionConfig, env: EnvironmentResult) -> np.ndarray:
    """Torque from the bus residual dipole, N m."""
    residual = float(cfg.spacecraft.bus.residual_dipole_am2)
    return residual * np.linalg.norm(env.b_field_N, axis=1)


def aerodynamic_torque(cfg: MissionConfig, env: EnvironmentResult,
                       density_kg_m3: float = 2.0e-12) -> np.ndarray:
    """Aerodynamic torque, N m.

    Density defaults to a representative value for ~415 km at moderate solar
    activity; it swings by more than an order of magnitude over a solar cycle,
    so treat this as an order-of-magnitude check rather than a prediction.
    """
    bus = cfg.spacecraft.bus
    d = bus.dimensions_m
    area = float(d.y) * float(d.z)          # largest projected face
    cd = float(bus.drag_coefficient)
    offset = float(bus.cp_cm_offset_m)
    speed = np.linalg.norm(env.v_BN_N, axis=1)
    return 0.5 * density_kg_m3 * cd * area * speed ** 2 * offset


def disturbance_summary(cfg: MissionConfig, env: EnvironmentResult,
                        authority: TorqueAuthority) -> dict[str, float]:
    gg = gravity_gradient_torque(cfg, env)
    mag = magnetic_disturbance_torque(cfg, env)
    aero = aerodynamic_torque(cfg, env)
    total = gg + mag + aero
    return {
        "gravity_gradient_nm_mean": float(np.mean(gg)),
        "gravity_gradient_nm_max": float(np.max(gg)),
        "residual_dipole_nm_mean": float(np.mean(mag)),
        "aero_nm_mean": float(np.mean(aero)),
        "total_disturbance_nm_mean": float(np.mean(total)),
        "total_disturbance_nm_max": float(np.max(total)),
        "control_authority_nm_mean": authority.mean_max_torque_nm,
        "authority_margin_mean": float(authority.mean_max_torque_nm / np.mean(total)),
        "authority_margin_worst": float(authority.min_max_torque_nm / np.max(total)),
    }


def detumble_time_s(cfg: MissionConfig, env: EnvironmentResult,
                    authority: TorqueAuthority) -> dict[str, float]:
    """B-dot detumble estimate from the configured initial tumble rate.

    B-dot achieves roughly 30-50 % of the ideal ``m x B`` torque because the
    control law is not torque-optimal; 0.4 is used here.
    """
    inertia = inertia_matrix(cfg)
    rate = math.radians(float(cfg.spacecraft.adcs.initial_tumble_rate_dps))
    j_max = float(np.max(np.diag(inertia)))
    momentum = j_max * rate
    effective = 0.4 * authority.mean_max_torque_nm
    return {
        "initial_rate_dps": float(cfg.spacecraft.adcs.initial_tumble_rate_dps),
        "initial_momentum_nms": momentum,
        "effective_torque_nm": effective,
        "detumble_hours": momentum / effective / 3600.0 if effective > 0 else math.inf,
    }


def momentum_dumping_per_orbit(cfg: MissionConfig, env: EnvironmentResult,
                               authority: TorqueAuthority,
                               period_s: float) -> dict[str, float]:
    """Fraction of each orbit the magnetorquers must be energised.

    Compares the secular momentum built up by disturbances over one orbit
    against the momentum the actuators can remove, giving a duty cycle. This is
    the "how often am I using them" number.
    """
    gg = gravity_gradient_torque(cfg, env)
    mag = magnetic_disturbance_torque(cfg, env)
    aero = aerodynamic_torque(cfg, env)
    # Gravity gradient largely averages out over an orbit for a controlled
    # vehicle; aero and residual dipole accumulate more persistently.
    secular = float(np.mean(0.2 * gg + mag + aero))
    momentum_per_orbit = secular * period_s
    removal_rate = authority.mean_max_torque_nm
    seconds_needed = momentum_per_orbit / removal_rate if removal_rate > 0 else math.inf
    return {
        "secular_disturbance_nm": secular,
        "momentum_per_orbit_nms": momentum_per_orbit,
        "removal_seconds_per_orbit": seconds_needed,
        "duty_cycle": seconds_needed / period_s if period_s else math.inf,
    }
