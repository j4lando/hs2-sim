"""Magnetorquer authority, slew times and duty cycle.

The question is how much magnetorquers throttle operations. Three things
matter, and all of them come out of the magnetic field history that Basilisk
produced:

1. **Torque is never available about the field direction.** For a dipole ``m``
   the torque is ``m x B``, so the component of the commanded torque along
   ``B`` is unachievable. On a 51.6 deg orbit the field direction sweeps a
   large range each orbit, so the *instantaneous* authority about a given body
   axis varies from near zero to the full value twice per orbit.

2. **Slew time scales as sqrt(angle x inertia / torque).** With a bang-bang
   profile, ``t = 2 sqrt(theta J / tau)``. Since tau here is of order
   1e-5 N m and J is 0.05 kg m^2, a 90 deg slew takes minutes, not seconds --
   this is what sets the CONOPS cadence.

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

    # Torque about body axis k from the full dipole set: |m x B| projected.
    # Using the full dipole vector, the achievable torque envelope is
    # tau = m x B, evaluated with each axis at its own capability.
    tau = np.stack([
        m[1] * b_B[:, 2] - m[2] * b_B[:, 1],
        m[2] * b_B[:, 0] - m[0] * b_B[:, 2],
        m[0] * b_B[:, 1] - m[1] * b_B[:, 0],
    ], axis=1)
    tau_abs = np.abs(tau)
    max_torque = np.linalg.norm(tau, axis=1)

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


def slew_time_profile(cfg: MissionConfig, authority: TorqueAuthority,
                      angle_deg: float, axis: int = 0) -> dict[str, float]:
    """Slew time for a given angle using best, mean and worst-case authority."""
    inertia = inertia_matrix(cfg)
    j = float(inertia[axis, axis])
    margin = float(cfg.spacecraft.adcs.settle_margin)
    angle = math.radians(angle_deg)
    axis_torque = authority.axis_torque_nm[:, axis]
    positive = axis_torque[axis_torque > 0]
    return {
        "angle_deg": angle_deg,
        "best_s": slew_time_s(angle, j, float(np.max(axis_torque)), margin),
        "mean_s": slew_time_s(angle, j, float(np.mean(axis_torque)), margin),
        "p10_s": slew_time_s(angle, j, float(np.percentile(positive, 10)), margin)
        if positive.size else math.inf,
        "median_s": slew_time_s(angle, j, float(np.median(axis_torque)), margin),
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
