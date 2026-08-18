"""Synthetic environments shared by the test modules.

Nothing here needs Basilisk: the orbits are analytic, which is what lets the
whole suite run in a plain checkout.
"""

from __future__ import annotations

import math

import numpy as np

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


def orbit_env(n: int, dt: float, period: float, phase0: float = 0.0,
              inclination_deg: float = 51.64) -> EnvironmentResult:
    """Circular inclined orbit, so z crosses zero once per revolution."""
    t = np.arange(n) * dt
    theta = 2 * math.pi * t / period + phase0
    r = R_EARTH + 415e3
    inc = math.radians(inclination_deg)
    pos = np.stack([r * np.cos(theta),
                    r * np.sin(theta) * math.cos(inc),
                    r * np.sin(theta) * math.sin(inc)], axis=1)
    return EnvironmentResult(
        t_s=t, r_BN_N=pos, v_BN_N=np.zeros((n, 3)),
        r_sun_N=np.tile([1.496e11, 0.0, 0.0], (n, 1)),
        shadow_factor=np.ones(n), b_field_N=np.zeros((n, 3)),
        dcm_PN=np.tile(np.eye(3), (n, 1, 1)),
        station_access=np.zeros((1, n), dtype=bool),
        station_elevation=np.zeros((1, n)), station_range=np.full((1, n), 1e7),
        station_names=["test"])


def detumble_env(duration_s: float = 8000.0, dt_s: float = 5.0,
                 raan_deg: float = 0.0, altitude_km: float = 415.0,
                 inclination_deg: float = 51.64,
                 sun_ecliptic_deg: float = 0.0) -> EnvironmentResult:
    """A LEO case complete enough to exercise the detumble simulation.

    The detumble Monte Carlo consumes ``EnvironmentResult`` objects produced by
    Basilisk. Building a stand-in here keeps the test suite runnable in a plain
    checkout, exactly as the two helpers above do -- but this one has to be a
    good deal more complete than they are, because the detumble sim uses the
    magnetic field, the eclipse flag and the Sun direction rather than just the
    positions. It carries a circular orbit, a tilted centred dipole field, a
    real Sun direction and a cylindrical shadow.

    It is a TEST FIXTURE, not a model: the field is dipole-only with no secular
    variation, the shadow is a cylinder rather than a cone, and there is no J2.
    Nothing in ``hs2sim`` imports it.
    """
    n = int(round(duration_s / dt_s)) + 1
    t = np.arange(n) * dt_s
    r = R_EARTH + altitude_km * 1e3
    period = 2 * math.pi * math.sqrt(r ** 3 / 3.986004418e14)
    speed = 2 * math.pi * r / period

    inc, raan = math.radians(inclination_deg), math.radians(raan_deg)
    theta = 2 * math.pi * t / period
    # Perifocal -> inertial for a circular orbit with zero argument of perigee.
    p_hat = np.array([math.cos(raan), math.sin(raan), 0.0])
    q_hat = np.array([-math.sin(raan) * math.cos(inc),
                      math.cos(raan) * math.cos(inc), math.sin(inc)])
    pos = r * (np.cos(theta)[:, None] * p_hat + np.sin(theta)[:, None] * q_hat)
    vel = speed * (-np.sin(theta)[:, None] * p_hat + np.cos(theta)[:, None] * q_hat)

    # Sun on the ecliptic, at the requested ecliptic longitude.
    obliquity = math.radians(23.4392911)
    lam = math.radians(sun_ecliptic_deg)
    sun_hat = np.array([math.cos(lam),
                        math.sin(lam) * math.cos(obliquity),
                        math.sin(lam) * math.sin(obliquity)])
    sun = np.tile(sun_hat * 1.495978707e11, (n, 1))

    # Tilted centred dipole, IGRF-13 epoch 2020, spun up with Earth.
    g = np.array([-1450.9e-9, 4652.5e-9, -29404.8e-9])     # (g11, h11, g10)
    spin = 7.292115e-5 * t
    g_N = np.stack([g[0] * np.cos(spin) - g[1] * np.sin(spin),
                    g[0] * np.sin(spin) + g[1] * np.cos(spin),
                    np.full(n, g[2])], axis=1)
    r_hat = pos / np.linalg.norm(pos, axis=1, keepdims=True)
    proj = np.sum(g_N * r_hat, axis=1, keepdims=True)
    b_field = (R_EARTH ** 3 / r ** 3) * (3.0 * proj * r_hat - g_N)

    # Cylindrical shadow: behind Earth and inside its radius.
    along = pos @ sun_hat
    perp = np.linalg.norm(pos - along[:, None] * sun_hat, axis=1)
    shadow = np.where((along < 0) & (perp < R_EARTH), 0.0, 1.0)

    spin_dcm = np.zeros((n, 3, 3))
    spin_dcm[:, 0, 0] = np.cos(spin)
    spin_dcm[:, 0, 1] = np.sin(spin)
    spin_dcm[:, 1, 0] = -np.sin(spin)
    spin_dcm[:, 1, 1] = np.cos(spin)
    spin_dcm[:, 2, 2] = 1.0

    return EnvironmentResult(
        t_s=t, r_BN_N=pos, v_BN_N=vel, r_sun_N=sun,
        shadow_factor=shadow, b_field_N=b_field, dcm_PN=spin_dcm,
        station_access=np.zeros((1, n), dtype=bool),
        station_elevation=np.zeros((1, n)),
        station_range=np.full((1, n), 1e7), station_names=["test"])
