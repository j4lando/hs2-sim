"""Per-face illumination -- the input a thermal model actually needs.

This is deliberately *not* a thermal model. It answers the question asked --
"how much sunlight exposure does the surface of the satellite experience on
average" -- by reporting, for each of the six body faces:

  * the fraction of time the face sees the Sun at all,
  * the mean cosine of the solar incidence angle,
  * the resulting mean absorbed solar flux in W/m^2 and W.

Two other LEO heat inputs are included because at 415 km they are the same
order as direct sunlight and a thermal engineer will immediately ask for them:
Earth albedo (reflected sunlight, only on the dayside) and Earth infrared
(always on, roughly isotropic from the disc). Both use the standard flat-plate
view factor to a spherical planet.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from .config import MissionConfig
from .environment import EnvironmentResult, R_EARTH

# Body face definitions: name -> (outward normal, area key)
FACES = {
    "+x": np.array([1.0, 0.0, 0.0]),
    "-x": np.array([-1.0, 0.0, 0.0]),
    "+y": np.array([0.0, 1.0, 0.0]),
    "-y": np.array([0.0, -1.0, 0.0]),
    "+z": np.array([0.0, 0.0, 1.0]),
    "-z": np.array([0.0, 0.0, -1.0]),
}


def face_areas(cfg: MissionConfig) -> dict[str, float]:
    d = cfg.spacecraft.bus.dimensions_m
    x, y, z = float(d.x), float(d.y), float(d.z)
    return {
        "+x": y * z, "-x": y * z,
        "+y": x * z, "-y": x * z,
        "+z": x * y, "-z": x * y,
    }


@dataclasses.dataclass
class FaceThermal:
    name: str
    area_m2: float
    sunlit_fraction: float          # fraction of mission time with any direct sun
    mean_cosine: float              # time-mean of max(0, n.s) including eclipse
    mean_solar_flux_w_m2: float
    mean_albedo_flux_w_m2: float
    mean_ir_flux_w_m2: float
    mean_total_flux_w_m2: float
    peak_solar_flux_w_m2: float
    mean_solar_power_w: float
    longest_dark_s: float           # longest continuous interval with no direct sun


def _view_factor_table(rho_grid: np.ndarray, n_theta: int = 361,
                       n_gamma: int = 200, n_phi: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """Tabulate the plate-to-planet view factor by direct quadrature.

    The planet fills a cone of half-angle ``rho`` about nadir. For a plate
    whose normal sits at angle ``theta`` from nadir, the view factor is

        F = (1/pi) * int_cone  max(0, omega . n)  dOmega

    which is the exact result for a uniformly radiating disc source -- the
    standard assumption behind published Earth IR and albedo loads. Evaluating
    it numerically avoids the error-prone partial-view closed form, and a
    sanity check falls straight out: at theta = 0 the integral reduces to
    sin^2(rho), which is the textbook nadir-facing value.

    Returns (theta_grid, table) with table shape (len(rho_grid), n_theta).
    """
    theta = np.linspace(0.0, math.pi, n_theta)
    gamma = np.linspace(0.0, 1.0, n_gamma)          # scaled, expanded per rho
    phi = np.linspace(0.0, 2 * math.pi, n_phi, endpoint=False)
    cos_phi = np.cos(phi)
    d_phi = 2 * math.pi / n_phi

    table = np.zeros((len(rho_grid), n_theta))
    for r_index, rho in enumerate(rho_grid):
        g = gamma * rho
        d_gamma = rho / (n_gamma - 1)
        sin_g, cos_g = np.sin(g), np.cos(g)
        # omega . n  =  sin(gamma) cos(phi) sin(theta) + cos(gamma) cos(theta)
        term_a = np.einsum("g,p->gp", sin_g, cos_phi)      # (G,P)
        for t_index, th in enumerate(theta):
            dot = term_a * math.sin(th) + cos_g[:, None] * math.cos(th)
            integrand = np.clip(dot, 0.0, None) * sin_g[:, None]
            # Trapezoid in gamma, rectangle in phi.
            weights = np.full(n_gamma, d_gamma)
            weights[0] *= 0.5
            weights[-1] *= 0.5
            table[r_index, t_index] = (integrand.sum(axis=1) * d_phi) @ weights / math.pi
    return theta, table


def _view_factor_to_earth(env: EnvironmentResult, normals_N: np.ndarray) -> np.ndarray:
    """Flat-plate view factor from each face to Earth, per sample and face.

    normals_N : (N, F, 3) inertial face normals.
    """
    r = np.linalg.norm(env.r_BN_N, axis=1)                 # (N,)
    rho = np.arcsin(np.clip(R_EARTH / r, -1.0, 1.0))       # (N,)
    nadir = env.nadir_unit()
    cos_theta = np.clip(np.einsum("nfi,ni->nf", normals_N, nadir), -1.0, 1.0)
    theta = np.arccos(cos_theta)

    # rho barely moves on a near-circular orbit, but interpolate over it anyway
    # so the model stays honest for eccentric cases.
    rho_grid = (np.linspace(rho.min(), rho.max(), 5) if np.ptp(rho) > 1e-6
                else np.array([float(rho.mean())]))
    theta_grid, table = _view_factor_table(rho_grid)

    if len(rho_grid) == 1:
        return np.clip(np.interp(theta, theta_grid, table[0]), 0.0, 1.0)

    # Bilinear: interpolate in theta for each bracketing rho, then blend.
    idx = np.clip(np.searchsorted(rho_grid, rho) - 1, 0, len(rho_grid) - 2)
    lo = rho_grid[idx]
    hi = rho_grid[idx + 1]
    frac = ((rho - lo) / (hi - lo))[:, None]
    low_vals = np.stack([np.interp(theta[i], theta_grid, table[idx[i]])
                         for i in range(len(theta))])
    high_vals = np.stack([np.interp(theta[i], theta_grid, table[idx[i] + 1])
                          for i in range(len(theta))])
    return np.clip(low_vals * (1 - frac) + high_vals * frac, 0.0, 1.0)


def analyse(cfg: MissionConfig,
            env: EnvironmentResult,
            dcm_BN: np.ndarray) -> dict[str, FaceThermal]:
    """Per-face illumination statistics for an attitude history."""
    solar_constant = float(cfg.env.solar_constant_w_m2)
    albedo_coeff = float(cfg.env.earth_albedo)
    earth_ir = float(cfg.env.earth_ir_w_m2)
    areas = face_areas(cfg)
    sun_hat = env.sun_unit()
    nadir = env.nadir_unit()

    names = list(FACES)
    body_normals = np.stack([FACES[n] for n in names])          # (F,3)
    # Inertial normals for every sample and face.
    normals_N = np.einsum("nji,fj->nfi", dcm_BN, body_normals)  # (N,F,3)

    cos_sun = np.clip(np.einsum("nfi,ni->nf", normals_N, sun_hat), 0.0, None)
    lit = cos_sun * env.shadow_factor[:, None]                  # (N,F)
    solar_flux = lit * solar_constant

    view = _view_factor_to_earth(env, normals_N)                # (N,F)
    ir_flux = view * earth_ir

    # Albedo is only reflected where the sub-satellite point is in daylight.
    sun_over_nadir = np.clip(np.einsum("ni,ni->n", -nadir, sun_hat), 0.0, None)
    albedo_flux = view * solar_constant * albedo_coeff * sun_over_nadir[:, None]

    results: dict[str, FaceThermal] = {}
    for f, name in enumerate(names):
        has_sun = solar_flux[:, f] > 0.0
        results[name] = FaceThermal(
            name=name,
            area_m2=areas[name],
            sunlit_fraction=float(np.mean(has_sun)),
            mean_cosine=float(np.mean(lit[:, f])),
            mean_solar_flux_w_m2=float(np.mean(solar_flux[:, f])),
            mean_albedo_flux_w_m2=float(np.mean(albedo_flux[:, f])),
            mean_ir_flux_w_m2=float(np.mean(ir_flux[:, f])),
            mean_total_flux_w_m2=float(np.mean(solar_flux[:, f]
                                               + albedo_flux[:, f]
                                               + ir_flux[:, f])),
            peak_solar_flux_w_m2=float(np.max(solar_flux[:, f])),
            mean_solar_power_w=float(np.mean(solar_flux[:, f]) * areas[name]),
            longest_dark_s=_longest_run(~has_sun) * env.dt_s,
        )
    return results


def _longest_run(mask: np.ndarray) -> int:
    """Length of the longest run of True values."""
    if not mask.any():
        return 0
    best = run = 0
    for value in mask:
        run = run + 1 if value else 0
        best = max(best, run)
    return best


def eclipse_statistics(env: EnvironmentResult) -> dict[str, float]:
    """Eclipse duty cycle and worst-case duration -- the survival heating case."""
    eclipsed = env.shadow_factor < 0.5
    runs = []
    run = 0
    for value in eclipsed:
        if value:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    return {
        "eclipse_fraction": float(np.mean(eclipsed)),
        "max_eclipse_min": (max(runs) * env.dt_s / 60.0) if runs else 0.0,
        "mean_eclipse_min": (float(np.mean(runs)) * env.dt_s / 60.0) if runs else 0.0,
        "eclipses_counted": len(runs),
    }
