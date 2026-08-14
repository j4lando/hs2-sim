"""View factors: the quadrature must reproduce the closed form."""

from __future__ import annotations

import numpy as np

from helpers import make_env
from hs2sim import thermal


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
