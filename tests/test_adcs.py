"""Magnetorquer authority, slew timing and rotation bookkeeping."""

from __future__ import annotations

import math

import numpy as np
import pytest

from hs2sim import adcs, conops


def _brute_force_torque_about(m_max, b, axis):
    """Maximum torque about `axis` by enumerating the dipole box vertices."""
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    best = -np.inf
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                m = np.asarray(m_max, float) * np.array([sx, sy, sz], float)
                best = max(best, float(np.cross(m, b) @ axis))
    return best


def test_available_torque_matches_the_dipole_box_envelope():
    m = np.array([0.2, 0.15, 0.1])
    rng = np.random.default_rng(3)
    for _ in range(20):
        b = rng.normal(scale=3e-5, size=3)
        axis = rng.normal(size=3)
        got = adcs.available_torque_about(m, b[None, :], axis)[0]
        assert got == pytest.approx(_brute_force_torque_about(m, b, axis))


def test_no_torque_about_the_field_direction():
    """The one property the whole slew model turns on."""
    m = np.array([0.2, 0.2, 0.2])
    rng = np.random.default_rng(4)
    for _ in range(20):
        b = rng.normal(scale=3e-5, size=3)
        along = adcs.available_torque_about(m, b[None, :], b)[0]
        assert along == pytest.approx(0.0, abs=1e-18)
        # ... and perpendicular to it there is authority.
        perp = np.cross(b, [1.0, 0.0, 0.0])
        if np.linalg.norm(perp) > 1e-9:
            assert adcs.available_torque_about(m, b[None, :], perp)[0] > 0.0


def test_max_torque_magnitude_matches_brute_force():
    m = np.array([0.2, 0.15, 0.1])
    rng = np.random.default_rng(5)
    b = rng.normal(scale=3e-5, size=(10, 3))
    got = adcs.max_torque_magnitude(m, b)
    for i in range(len(b)):
        best = 0.0
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    mm = m * np.array([sx, sy, sz], float)
                    best = max(best, float(np.linalg.norm(np.cross(mm, b[i]))))
        assert got[i] == pytest.approx(best)


def test_slew_integrator_reproduces_the_closed_form_at_constant_torque():
    """With a constant authority the integrator must match 2 sqrt(theta J/tau)."""
    tau, j, angle = 1.0e-5, 0.05, math.radians(90.0)
    series = np.full(20000, tau)
    got = adcs.slew_time_eigenaxis(series, j, angle, dt_s=0.5, margin=1.0)
    expected = 2.0 * math.sqrt(angle * j / tau)
    assert got == pytest.approx(expected, rel=0.02)


def test_slew_never_completes_if_the_field_stays_along_the_eigenaxis():
    """A static field parallel to the slew axis leaves zero authority forever."""
    b = np.tile(np.array([3e-5, 0.0, 0.0]), (4000, 1))
    axis = np.array([1.0, 0.0, 0.0])
    series = adcs.available_torque_about(np.array([0.2, 0.2, 0.2]), b, axis)
    assert np.allclose(series, 0.0)
    got = adcs.slew_time_eigenaxis(series, 0.05, math.radians(90.0),
                                   dt_s=5.0, max_seconds=3600.0)
    assert not math.isfinite(got)


def test_a_rotating_field_rescues_the_same_slew():
    """The same manoeuvre completes once the field sweeps off the eigenaxis.

    This is the behaviour a constant-torque formula cannot express, and the
    reason 'no authority about B' does not mean 'impossible'.
    """
    t = np.linspace(0.0, 2.0 * math.pi, 4000)
    b = 3e-5 * np.stack([np.cos(t), np.sin(t), np.zeros_like(t)], axis=1)
    axis = np.array([1.0, 0.0, 0.0])
    series = adcs.available_torque_about(np.array([0.2, 0.2, 0.2]), b, axis)
    assert series[0] == pytest.approx(0.0, abs=1e-18)   # starts with none
    got = adcs.slew_time_eigenaxis(series, 0.05, math.radians(90.0),
                                   dt_s=5.0, max_seconds=6.0 * 3600.0)
    assert math.isfinite(got)


def test_eigenaxis_inertia_matches_the_principal_axes():
    inertia = np.diag([0.05, 0.05, 0.01])
    assert adcs.eigenaxis_inertia(inertia, [0, 0, 1]) == pytest.approx(0.01)
    assert adcs.eigenaxis_inertia(inertia, [1, 0, 0]) == pytest.approx(0.05)
    # Halfway between x and z: (0.05 + 0.01)/2.
    assert adcs.eigenaxis_inertia(inertia, [1, 0, 1]) == pytest.approx(0.03)


def test_rotation_axis_angle_inverts_a_known_rotation():
    angle = math.radians(37.0)
    axis = np.array([1.0, 2.0, -3.0])
    axis /= np.linalg.norm(axis)
    skew = np.array([[0, -axis[2], axis[1]],
                     [axis[2], 0, -axis[0]],
                     [-axis[1], axis[0], 0]])
    rot = (np.eye(3) + math.sin(angle) * skew
           + (1 - math.cos(angle)) * (skew @ skew))
    got_axis, got_angle = conops.rotation_axis_angle(np.eye(3), rot)
    assert got_angle == pytest.approx(angle)
    assert np.allclose(np.abs(got_axis), np.abs(axis))
