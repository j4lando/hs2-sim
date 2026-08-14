"""Orbit geometry and the experiment-pointing solver."""

from __future__ import annotations

import math

import numpy as np
import pytest

from helpers import make_env
from hs2sim import geometry
from hs2sim.config import MissionConfig
from hs2sim.environment import R_EARTH


def test_earth_angular_radius_matches_geometry():
    env = make_env()
    expected = math.degrees(math.asin(R_EARTH / (R_EARTH + 415e3)))
    assert np.allclose(np.degrees(env.earth_angular_radius()), expected, atol=1e-9)
    # Sanity: from 415 km the Earth fills a ~70 deg half-cone.
    assert 69.0 < expected < 71.0


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
