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
