"""Attitude geometry: what the spacecraft is allowed to point at, and when.

The interesting question for HS-2 is not "can we point", it is "does a legal
attitude exist at all at this instant". Experiment mode has to satisfy four
constraints simultaneously:

  * FOUND (+x, 74 deg full FOV) must be looking at a **sunlit** limb of Earth.
  * FOUND must keep the Sun more than 70 deg off its boresight.
  * LOST and the star tracker (both +z, 40 deg half-cone keep-out) must have
    neither Earth nor Sun inside that keep-out.
  * The Sun must never enter any exclusion cone.

Every one of those cones is enforced with a **pointing margin** on top of the
quoted angle. What the solver returns is a commanded attitude; the true
boresight is somewhere within the combined control and knowledge error of it,
in an unknown direction. An attitude sitting exactly on the star tracker's
40 deg Sun boundary is a coin flip, not a legal attitude, so the cones are
padded by ``adcs.pointing_margin_deg`` and the legal set shrinks from all
sides. See ``solve_experiment_pointing`` for what is deliberately *not* padded.

Because +x and +z are orthogonal, fixing the FOUND boresight still leaves one
degree of freedom: the roll about +x. So the feasibility test is

    for each candidate limb azimuth  ->  is there a roll angle that clears
    Earth and Sun out of the +z keep-out, with the pointing margin to spare?

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
    pointing_margin_deg: float = 0.0   # buffer the keep-outs were padded with


REJECT_OK = 0
REJECT_NO_SUNLIT_LIMB = 1     # the whole visible limb is in darkness
REJECT_SUN_IN_FOUND = 2       # every sunlit limb violates FOUND's Sun keep-out
REJECT_NO_ROLL = 3            # no roll clears Earth+Sun from the +z keep-out
REJECT_FOV_MARGIN = 4         # the buffer has eaten FOUND's whole field of view


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
                              array_weights: np.ndarray | None = None,
                              power_tolerance: float = 0.95,
                              pointing_margin_deg: float | None = None
                              ) -> PointingResult:
    """Find, for every sample, a legal experiment attitude (if one exists).

    When several attitudes are legal we pick the one that puts the most power
    into the solar array -- pointing and power are coupled, and there is no
    reason to spend the spare roll freedom on nothing.

    ``array_normals`` (K,3) and ``array_weights`` (K,) describe the array in
    body coordinates; if omitted, feasibility is still computed and the power
    fraction is reported as zero.

    ``pointing_margin_deg`` pads every keep-out. The attitude this function
    returns is a *commanded* attitude; the true boresight sits somewhere within
    the combined control and knowledge error of it, in an unknown direction. An
    attitude that puts the Sun exactly on the star tracker's 40 deg boundary is
    therefore a 50/50 bet, not a legal attitude. Padding the cones by the
    pointing error is what makes the answer flyable. Defaults to
    ``adcs.pointing_margin_deg(cfg)``; pass 0.0 to get the unbuffered geometric
    answer.

    The buffer works in both directions, as it must: a keep-**out** cone grows
    by the margin, and the keep-**in** field of view shrinks by it. FOUND's
    usable FOV is ``fov_full/2 - margin`` and the limb has to sit inside that.
    In this geometry the shrink is not what binds -- the solver places the
    boresight exactly on the limb, so the limb sits at 0 deg off-axis with the
    whole 37 deg half-FOV to spare -- but it is a real wall once the margin
    reaches 37 deg, and it is enforced rather than assumed away.

    Not padded, deliberately:

    * **The terminator margin** in the sunlit test. That margin is about not
      imaging the day/night boundary itself; near the limb the line of sight
      grazes the surface, so boresight error maps to along-track motion of the
      aim point at a rate that has nothing to do with the cone geometry.
      Padding it by the pointing error would look rigorous and mean nothing.
    """
    from .adcs import pointing_margin_deg as _default_margin

    sensors = cfg.spacecraft.sensors
    found = sensors.found_camera
    lost = sensors.lost_camera
    tracker = sensors.star_tracker

    if pointing_margin_deg is None:
        pointing_margin_deg = _default_margin(cfg)
    margin = math.radians(float(pointing_margin_deg))

    sun_excl_found = math.radians(float(found.sun_exclusion_deg)) + margin

    # Keep-IN constraint, so the margin shrinks it instead of growing it. The
    # boresight is placed on the limb cone, which puts the limb at 0 deg
    # off-axis, so what this actually tests is whether any field of view
    # survives the buffer at all. That reduces to a scalar precondition -- but
    # it is a real one: at margin >= fov_full/2 the vehicle cannot guarantee
    # the limb is in frame no matter where it is told to look.
    fov_half_found = math.radians(float(found.fov_full_deg)) / 2.0
    limb_offset_from_boresight = 0.0
    # Strict: at margin == fov_half the surviving field of view is a single
    # point of zero angular extent. That is not a field of view, and treating
    # it as one would let the wall sit one grid step too far out.
    fov_margin_ok = (fov_half_found - margin) > limb_offset_from_boresight
    # +z carries both LOST and the star tracker; take the tighter keep-out.
    sun_excl_z = math.radians(min(float(lost.sun_exclusion_deg),
                                  float(tracker.sun_exclusion_deg))) + margin
    earth_excl_z = math.radians(min(float(lost.earth_exclusion_deg),
                                    float(tracker.earth_exclusion_deg))) + margin

    n_samples = env.n_samples

    if not fov_margin_ok:
        # Nothing downstream can rescue this: the buffer is wider than the
        # half-FOV, so no commanded attitude guarantees the limb is imaged.
        return PointingResult(
            feasible=np.zeros(n_samples, dtype=bool),
            dcm_BN=np.tile(np.eye(3), (n_samples, 1, 1)),
            x_axis_N=np.tile(np.array([1.0, 0.0, 0.0]), (n_samples, 1)),
            z_axis_N=np.tile(np.array([0.0, 0.0, 1.0]), (n_samples, 1)),
            roll_used=np.zeros(n_samples),
            array_power_frac=np.zeros(n_samples),
            reject_reason=np.full(n_samples, REJECT_FOV_MARGIN, dtype=np.int8),
            pointing_margin_deg=float(pointing_margin_deg),
        )

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

    # Carried across chunks so continuity holds at chunk boundaries too.
    prev_x: np.ndarray | None = None
    prev_z: np.ndarray | None = None

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

        score = np.where(ok, score, -np.inf).reshape(m, n_azimuth * n_roll)
        x_grid = np.repeat(x_hat, n_roll, axis=1).reshape(m, n_azimuth * n_roll, 3)
        z_grid = z_all.reshape(m, n_azimuth * n_roll, 3)

        # Select sequentially so the attitude profile is temporally coherent.
        # Optimising each sample independently produces a globally optimal but
        # unflyable answer: consecutive samples can pick limb points on
        # opposite sides of the Earth, implying an instantaneous 100 deg
        # reorientation. Instead, among candidates within `power_tolerance` of
        # the best available power, take the one closest to the attitude we are
        # already holding. Feasibility -- the thing the reject codes report --
        # is unaffected; only the choice among legal attitudes changes.
        for local in range(m):
            row = score[local]
            best_val = row.max()
            if not np.isfinite(best_val):
                continue
            i = start + local
            if best_val <= 0:
                near_best = np.flatnonzero(np.isfinite(row))
            else:
                near_best = np.flatnonzero(row >= best_val * power_tolerance)

            if prev_x is None:
                pick = near_best[int(np.argmax(row[near_best]))]
            else:
                alignment = (x_grid[local, near_best] @ prev_x
                             + z_grid[local, near_best] @ prev_z)
                pick = near_best[int(np.argmax(alignment))]

            chosen_x = x_grid[local, pick]
            chosen_z = z_grid[local, pick]
            feasible[i] = True
            reject[i] = REJECT_OK
            best_x[i] = chosen_x
            best_z[i] = chosen_z
            best_roll[i] = rolls[pick % n_roll]
            best_power[i] = row[pick]
            best_dcm[i] = np.vstack([chosen_x, np.cross(chosen_z, chosen_x),
                                     chosen_z])
            prev_x, prev_z = chosen_x, chosen_z

    return PointingResult(
        feasible=feasible,
        dcm_BN=best_dcm,
        x_axis_N=best_x,
        z_axis_N=best_z,
        roll_used=best_roll,
        array_power_frac=best_power,
        reject_reason=reject,
        pointing_margin_deg=float(pointing_margin_deg),
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

    # Refine off the grid. For a fixed set of illuminated panels the objective
    # sum_k w_k (d . n_k) is linear in d, so the exact optimum is the
    # power-weighted sum of those normals. Iterate in case the refinement
    # changes which panels are lit.
    for _ in range(8):
        active = (normals @ best_body_dir) > 0
        if not active.any():
            break
        candidate = (weights[active, None] * normals[active]).sum(axis=0)
        norm = np.linalg.norm(candidate)
        if norm < 1e-12:
            break
        candidate /= norm
        if np.clip(normals @ candidate, 0, None) @ weights <= \
                np.clip(normals @ best_body_dir, 0, None) @ weights + 1e-12:
            break
        best_body_dir = candidate
    best_fraction = float(np.clip(normals @ best_body_dir, 0, None) @ weights)

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
