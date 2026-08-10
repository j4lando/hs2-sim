"""Attitude geometry: what the spacecraft is allowed to point at, and when.

The interesting question for HS-2 is not "can we point", it is "does a legal
attitude exist at all at this instant". Experiment mode has to satisfy four
constraints simultaneously:

  * FOUND (+x, 74 deg full FOV) must be looking at a **sunlit** limb of Earth.
  * FOUND must keep the Sun more than 70 deg off its boresight.
  * LOST and the star tracker (both +z, 40 deg half-cone keep-out) must have
    neither Earth nor Sun inside that keep-out.
  * The Sun must never enter any exclusion cone.

Because +x and +z are orthogonal, fixing the FOUND boresight still leaves one
degree of freedom: the roll about +x. So the feasibility test is

    for each candidate limb azimuth  ->  is there a roll angle that clears
    Earth and Sun out of the +z keep-out?

Geometry that makes this non-trivial: from 415 km the Earth disc has an
angular radius of about 70 deg, so pointing at the limb already puts +x about
70 deg off nadir, and +z must then be pushed more than 110 deg from nadir to
keep Earth out of a 40 deg keep-out. That is achievable but only over part of
the roll range, and it competes with the Sun keep-out.

Everything below is vectorised over time samples.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from .config import MissionConfig
from .environment import EnvironmentResult


def unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n == 0, 1.0, n)


def orthonormal_basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return two unit vectors spanning the plane perpendicular to ``axis``.

    ``axis`` is (N,3). Uses the least-aligned cardinal direction as the seed so
    the construction never degenerates.
    """
    seed = np.zeros_like(axis)
    smallest = np.argmin(np.abs(axis), axis=-1)
    seed[np.arange(len(axis)), smallest] = 1.0
    u = unit(np.cross(axis, seed))
    v = np.cross(axis, u)
    return u, v


@dataclasses.dataclass
class PointingResult:
    """Per-sample experiment-mode pointing feasibility and the chosen attitude."""

    feasible: np.ndarray        # (N,) bool - a legal experiment attitude exists
    dcm_BN: np.ndarray          # (N,3,3) chosen body-from-inertial DCM
    x_axis_N: np.ndarray        # (N,3) FOUND boresight in inertial frame
    z_axis_N: np.ndarray        # (N,3) LOST / star tracker boresight
    roll_used: np.ndarray       # (N,) roll about +x that was selected, radians
    array_power_frac: np.ndarray  # (N,) cosine factor achieved by the array
    reject_reason: np.ndarray   # (N,) int code, see REJECT_* below


REJECT_OK = 0
REJECT_NO_SUNLIT_LIMB = 1     # the whole visible limb is in darkness
REJECT_SUN_IN_FOUND = 2       # every sunlit limb violates FOUND's Sun keep-out
REJECT_NO_ROLL = 3            # no roll clears Earth+Sun from the +z keep-out


def _sunlit_limb_directions(env: EnvironmentResult, n_azimuth: int) -> np.ndarray:
    """Candidate FOUND boresight directions, one per limb azimuth.

    Returns (N, A, 3). Each direction lies on the cone of half-angle equal to
    Earth's angular radius about nadir, i.e. it points at the horizon.
    """
    nadir = env.nadir_unit()
    rho = env.earth_angular_radius()                      # (N,)
    u, v = orthonormal_basis(nadir)                       # (N,3) each
    az = np.linspace(0.0, 2 * math.pi, n_azimuth, endpoint=False)
    cos_r = np.cos(rho)[:, None, None]
    sin_r = np.sin(rho)[:, None, None]
    perp = (np.cos(az)[None, :, None] * u[:, None, :]
            + np.sin(az)[None, :, None] * v[:, None, :])
    return cos_r * nadir[:, None, :] + sin_r * perp


def _tangent_points(env: EnvironmentResult, limb_dirs: np.ndarray) -> np.ndarray:
    """Position of the Earth-surface tangent point for each limb direction.

    For a boresight on the limb cone the tangent point sits at distance
    sqrt(r^2 - Re^2) along the boresight.
    """
    r = np.linalg.norm(env.r_BN_N, axis=1)
    dist = np.sqrt(np.maximum(r ** 2 - 6378136.3 ** 2, 0.0))[:, None, None]
    return env.r_BN_N[:, None, :] + dist * limb_dirs


def solve_experiment_pointing(cfg: MissionConfig,
                              env: EnvironmentResult,
                              n_azimuth: int = 72,
                              n_roll: int = 72,
                              array_normals: np.ndarray | None = None,
                              array_weights: np.ndarray | None = None) -> PointingResult:
    """Find, for every sample, a legal experiment attitude (if one exists).

    When several attitudes are legal we pick the one that puts the most power
    into the solar array -- pointing and power are coupled, and there is no
    reason to spend the spare roll freedom on nothing.

    ``array_normals`` (K,3) and ``array_weights`` (K,) describe the array in
    body coordinates; if omitted, feasibility is still computed and the power
    fraction is reported as zero.
    """
    sensors = cfg.spacecraft.sensors
    found = sensors.found_camera
    lost = sensors.lost_camera
    tracker = sensors.star_tracker

    sun_excl_found = math.radians(float(found.sun_exclusion_deg))
    # +z carries both LOST and the star tracker; take the tighter keep-out.
    sun_excl_z = math.radians(min(float(lost.sun_exclusion_deg),
                                  float(tracker.sun_exclusion_deg)))
    earth_excl_z = math.radians(min(float(lost.earth_exclusion_deg),
                                    float(tracker.earth_exclusion_deg)))

    n_samples = env.n_samples
    sun_hat = env.sun_unit()                 # (N,3)
    nadir = env.nadir_unit()                 # (N,3)
    rho = env.earth_angular_radius()         # (N,3)

    limb_dirs = _sunlit_limb_directions(env, n_azimuth)      # (N,A,3)
    tangent = _tangent_points(env, limb_dirs)                # (N,A,3)

    # A limb point is usable only if it is actually lit: the outward surface
    # normal at the tangent point must face the Sun. Require a few degrees of
    # margin so we are not imaging the terminator itself.
    surface_normal = unit(tangent)
    sun_from_tangent = unit(env.r_sun_N[:, None, :] - tangent)
    lit = np.sum(surface_normal * sun_from_tangent, axis=-1) > math.sin(math.radians(5.0))

    # FOUND must keep the Sun outside its own exclusion half-cone.
    found_sun_angle = np.arccos(np.clip(
        np.sum(limb_dirs * sun_hat[:, None, :], axis=-1), -1, 1))
    found_ok = lit & (found_sun_angle > sun_excl_found)

    # Roll about +x sweeps +z around a circle perpendicular to the boresight.
    rolls = np.linspace(0.0, 2 * math.pi, n_roll, endpoint=False)

    feasible = np.zeros(n_samples, dtype=bool)
    reject = np.full(n_samples, REJECT_NO_SUNLIT_LIMB, dtype=np.int8)
    best_dcm = np.tile(np.eye(3), (n_samples, 1, 1))
    best_x = np.tile(np.array([1.0, 0.0, 0.0]), (n_samples, 1))
    best_z = np.tile(np.array([0.0, 0.0, 1.0]), (n_samples, 1))
    best_roll = np.zeros(n_samples)
    best_power = np.zeros(n_samples)

    has_array = array_normals is not None and array_weights is not None
    if has_array:
        array_normals = np.asarray(array_normals, dtype=float)
        array_weights = np.asarray(array_weights, dtype=float)

    any_lit = lit.any(axis=1)
    reject[any_lit] = REJECT_SUN_IN_FOUND
    any_found_ok = found_ok.any(axis=1)
    reject[any_found_ok] = REJECT_NO_ROLL

    # Earth is a disc of angular radius rho about nadir, so +z must stay at
    # least earth_excl_z clear of the disc *edge*.
    min_earth_angle = rho + earth_excl_z                     # (N,)

    cos_roll = np.cos(rolls)[None, :, None]                  # (1,R,1)
    sin_roll = np.sin(rolls)[None, :, None]

    # Chunk over samples so the (M, A, R, 3) intermediates stay small enough to
    # live in cache-friendly memory while still being one numpy call each.
    chunk = max(1, int(400_000 / max(1, n_azimuth * n_roll)))
    for start in range(0, n_samples, chunk):
        stop = min(n_samples, start + chunk)
        m = stop - start
        x_hat = limb_dirs[start:stop]                        # (M,A,3)
        flat_x = x_hat.reshape(-1, 3)                        # (M*A,3)
        u, v = orthonormal_basis(flat_x)                     # (M*A,3) each

        # +z over the roll sweep, for every candidate boresight.
        z_all = cos_roll * u[:, None, :] + sin_roll * v[:, None, :]   # (M*A,R,3)

        nadir_c = np.repeat(nadir[start:stop], n_azimuth, axis=0)     # (M*A,3)
        sun_c = np.repeat(sun_hat[start:stop], n_azimuth, axis=0)

        earth_dot = np.einsum("ard,ad->ar", z_all, nadir_c)
        sun_dot = np.einsum("ard,ad->ar", z_all, sun_c)
        earth_angle = np.arccos(np.clip(earth_dot, -1, 1))
        sun_angle = np.arccos(np.clip(sun_dot, -1, 1))

        min_earth_c = np.repeat(min_earth_angle[start:stop], n_azimuth)[:, None]
        ok = (earth_angle > min_earth_c) & (sun_angle > sun_excl_z)
        ok &= found_ok[start:stop].reshape(-1, 1)

        if has_array:
            y_all = np.cross(z_all, x_hat.reshape(-1, 1, 3))          # (M*A,R,3)
            # Body->inertial: a body vector n maps to n_x*x + n_y*y + n_z*z.
            normals_N = (array_normals[None, None, :, 0, None] * x_hat.reshape(-1, 1, 1, 3)
                         + array_normals[None, None, :, 1, None] * y_all[:, :, None, :]
                         + array_normals[None, None, :, 2, None] * z_all[:, :, None, :])
            cosines = np.clip(np.einsum("arkd,ad->ark", normals_N, sun_c), 0, None)
            score = np.einsum("ark,k->ar", cosines, array_weights)     # (M*A,R)
        else:
            score = np.zeros_like(earth_angle)

        score = np.where(ok, score, -np.inf)
        score = score.reshape(m, n_azimuth * n_roll)
        best_flat = np.argmax(score, axis=1)
        best_val = score[np.arange(m), best_flat]
        good = np.isfinite(best_val)
        if not good.any():
            continue

        a_index = best_flat // n_roll
        r_index = best_flat % n_roll
        rows = np.arange(m)
        chosen_x = x_hat[rows, a_index]                                # (M,3)
        chosen_z = z_all.reshape(m, n_azimuth, n_roll, 3)[rows, a_index, r_index]
        chosen_y = np.cross(chosen_z, chosen_x)

        idx = np.arange(start, stop)[good]
        feasible[idx] = True
        reject[idx] = REJECT_OK
        best_x[idx] = chosen_x[good]
        best_z[idx] = chosen_z[good]
        best_roll[idx] = rolls[r_index[good]]
        best_power[idx] = best_val[good]
        best_dcm[idx] = np.stack([chosen_x[good], chosen_y[good], chosen_z[good]],
                                 axis=1)

    return PointingResult(
        feasible=feasible,
        dcm_BN=best_dcm,
        x_axis_N=best_x,
        z_axis_N=best_z,
        roll_used=best_roll,
        array_power_frac=best_power,
        reject_reason=reject,
    )


def sun_pointing_attitude(env: EnvironmentResult,
                          array_normals: np.ndarray,
                          array_weights: np.ndarray,
                          n_trial: int = 180) -> tuple[np.ndarray, np.ndarray]:
    """Best power-generating attitude, ignoring payload constraints.

    Used for standby/charging mode. The array is a fixed set of body-frame
    normals, so we search the single rotation that maximises total output:
    align the "effective" array normal with the Sun, then sweep the remaining
    roll about the Sun line to catch multi-panel geometries whose optimum is
    not simply the weighted-mean normal.
    """
    normals = np.asarray(array_normals, dtype=float)
    weights = np.asarray(array_weights, dtype=float)
    sun_hat = env.sun_unit()
    n_samples = env.n_samples

    # Candidate body directions to align with the Sun: sample the sphere and
    # score the array's total cosine output. This is attitude-independent, so
    # it is solved once and reused for every sample.
    phi = np.linspace(0, math.pi, 60)
    theta = np.linspace(0, 2 * math.pi, 120, endpoint=False)
    pp, tt = np.meshgrid(phi, theta, indexing="ij")
    dirs = np.stack([np.sin(pp) * np.cos(tt),
                     np.sin(pp) * np.sin(tt),
                     np.cos(pp)], axis=-1).reshape(-1, 3)
    output = np.clip(dirs @ normals.T, 0, None) @ weights
    best_body_dir = dirs[int(np.argmax(output))]
    best_fraction = float(np.max(output))

    # Build a DCM that maps best_body_dir onto the Sun direction.
    dcm = np.zeros((n_samples, 3, 3))
    for i in range(n_samples):
        rot = _rotation_between(best_body_dir, sun_hat[i])
        dcm[i] = rot.T
    return dcm, np.full(n_samples, best_fraction)


def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation matrix taking unit vector ``a`` to unit vector ``b``."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-12:
        if c > 0:
            return np.eye(3)
        # Antiparallel: a 180 deg turn about any perpendicular axis. Note that
        # -I is *not* usable here -- it has determinant -1, so it is a
        # reflection rather than a rotation and would flip the frame handedness.
        seed = np.array([1.0, 0.0, 0.0])
        if abs(a[0]) > 0.9:
            seed = np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, seed)
        axis /= np.linalg.norm(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]],
                   [v[2], 0, -v[0]],
                   [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def body_vectors_to_inertial(dcm_BN: np.ndarray, body_vec: np.ndarray) -> np.ndarray:
    """Rotate a fixed body-frame vector into inertial for every sample."""
    return np.einsum("nji,j->ni", dcm_BN, np.asarray(body_vec, dtype=float))


def angle_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.arccos(np.clip(np.sum(unit(a) * unit(b), axis=-1), -1, 1))
