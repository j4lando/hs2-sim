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


# ---------------------------------------------------------------------------
# Single-node (lumped) thermal model
# ---------------------------------------------------------------------------

STEFAN_BOLTZMANN = 5.670374419e-8


def dissipation_fractions(cfg: MissionConfig,
                          mean_torque_nm: float = 8.9e-6,
                          mean_body_rate_rad_s: float = 1.7e-3) -> dict[str, float]:
    """Fraction of each component's electrical input that becomes heat.

    Everything a spacecraft draws ends up as heat except the energy that
    physically leaves the vehicle. Two subsystems do that:

    * **COMM** radiates RF. Of the transmitter's electrical input, only the
      power that survives the PA, the impedance mismatch and the feed actually
      leaves as an electromagnetic wave; the rest is dissipated on board. Using
      the link budget's own numbers -- 2 W at the PA output, -3 dB return loss,
      -1 dB circuit loss -- the radiated fraction is small, so the radio is
      overwhelmingly a heater. The receiver radiates nothing at all.

    * **ADCS** does mechanical work. A magnetorquer is a resistive coil; the
      work it delivers is torque x body rate. At the torque this vehicle
      actually achieves that is of order 1e-8 W against watts of input, so the
      mechanical fraction is around a billionth. Magnetorquers are, thermally,
      pure resistors -- unlike reaction wheels, they store no useful kinetic
      energy, and the coil's field energy returns to the bus when it is
      de-energised.

    Returns a fraction in [0, 1] for each component in the power budget.
    """
    margin = 1.0 + float(cfg.power.margin)
    radio = cfg.radio

    # RF power that actually leaves the spacecraft, from the trusted link budget.
    radiated_w = (float(radio.tx_power_w)
                  * 10.0 ** (float(radio.return_loss_db) / 10.0)
                  * 10.0 ** (float(radio.circuit_loss_db) / 10.0))
    tx_input_w = float(cfg.power.components.radio_tx.peak_w) * margin
    tx_heat_fraction = max(0.0, 1.0 - radiated_w / tx_input_w)

    # Mechanical power delivered by the magnetorquers.
    mechanical_w = mean_torque_nm * mean_body_rate_rad_s
    fractions: dict[str, float] = {}
    for name, spec in cfg.power.components.items():
        input_w = float(spec.peak_w) * int(spec.qty) * margin
        if name == "radio_tx":
            fractions[name] = tx_heat_fraction
        elif name.startswith("mtq"):
            fractions[name] = max(0.0, 1.0 - mechanical_w / input_w)
        else:
            fractions[name] = 1.0
    fractions["_rf_radiated_w"] = radiated_w
    fractions["_mtq_mechanical_w"] = mechanical_w
    return fractions


def mode_heat_w(cfg: MissionConfig, mode: str,
                fractions: dict[str, float],
                heater_duty: float | None = None) -> float:
    """Electrical load in a mode that ends up as heat inside the spacecraft."""
    duty_map = cfg.power.modes[mode]
    margin = 1.0 + float(cfg.power.margin)
    heater_duty = (float(cfg.power.heater_duty_cycle)
                   if heater_duty is None else float(heater_duty))
    total = 0.0
    for component, duty in duty_map.items():
        d = heater_duty if duty == "heater_duty" else float(duty)
        spec = cfg.power.components[component]
        input_w = float(spec.peak_w) * int(spec.qty) * margin
        total += input_w * d * fractions[component]
    return total


@dataclasses.dataclass
class SingleNodeResult:
    temperature_k: np.ndarray
    equilibrium_k: np.ndarray       # zero-capacitance limit, for comparison
    absorbed_env_w: np.ndarray
    internal_heat_w: np.ndarray
    radiating_area_m2: float
    effective_emissivity: float
    thermal_capacitance_j_k: float
    stats: dict[str, float]


def single_node_temperature(cfg: MissionConfig,
                            env: EnvironmentResult,
                            dcm_BN: np.ndarray,
                            array_normals: np.ndarray,
                            array_peak_w: np.ndarray,
                            is_deployable: np.ndarray,
                            panel_count: np.ndarray,
                            generation_w: np.ndarray,
                            internal_heat_w: np.ndarray,
                            settle_fraction: float = 0.2) -> SingleNodeResult:
    """Integrate the lumped-capacitance energy balance.

        C dT/dt = Q_solar + Q_albedo + Q_IR + Q_internal - P_electrical - e s A T^4

    ``P_electrical`` is subtracted because power the cells export as electricity
    leaves the thermal node; it comes back as ``Q_internal`` once the loads
    dissipate it, so over an orbit the two nearly cancel and the residual is the
    RF actually radiated away.

    The first ``settle_fraction`` of the run is discarded from the statistics so
    the reported min/max/mean are not polluted by the initial transient.
    """
    thermal_cfg = cfg.spacecraft.thermal
    surfaces = thermal_cfg.surfaces
    alpha_bus = float(surfaces.bus.alpha)
    eps_bus = float(surfaces.bus.epsilon)
    alpha_cell = float(surfaces.solar_cell.alpha)
    eps_cell = float(surfaces.solar_cell.epsilon)
    alpha_back = float(surfaces.panel_back.alpha)
    eps_back = float(surfaces.panel_back.epsilon)

    solar_constant = float(cfg.env.solar_constant_w_m2)
    albedo_coeff = float(cfg.env.earth_albedo)
    earth_ir = float(cfg.env.earth_ir_w_m2)

    areas = face_areas(cfg)
    names = list(FACES)
    body_normals = np.stack([FACES[n] for n in names])
    normals_N = np.einsum("nji,fj->nfi", dcm_BN, body_normals)

    sun_hat = env.sun_unit()
    nadir = env.nadir_unit()
    cos_sun = np.clip(np.einsum("nfi,ni->nf", normals_N, sun_hat), 0.0, None)
    lit = cos_sun * env.shadow_factor[:, None]
    view = _view_factor_to_earth(env, normals_N)
    sun_over_nadir = np.clip(np.einsum("ni,ni->n", -nadir, sun_hat), 0.0, None)

    # Body faces. A face carrying cells (geometry C's +y) takes cell optics.
    # Membership is decided by the panel's `deployable` flag, not by comparing
    # normals: geometry A's wing points along -x, which coincides with a body
    # face direction without being one.
    cell_faces = set()
    for k, normal in enumerate(np.asarray(array_normals)):
        if is_deployable[k]:
            continue
        for f, name in enumerate(names):
            if np.dot(normal, body_normals[f]) > 0.999:
                cell_faces.add(name)

    absorbed = np.zeros(env.n_samples)
    radiating_area = 0.0
    emissivity_area = 0.0
    for f, name in enumerate(names):
        area = areas[name]
        on_cells = name in cell_faces
        alpha = alpha_cell if on_cells else alpha_bus
        eps = eps_cell if on_cells else eps_bus
        absorbed += alpha * area * solar_constant * lit[:, f]
        absorbed += alpha * area * view[:, f] * solar_constant * albedo_coeff * sun_over_nadir
        absorbed += eps * area * view[:, f] * earth_ir
        radiating_area += area
        emissivity_area += eps * area

    # Deployable wing: cells on the front, bare substrate on the back. Body
    # faces already counted above are excluded so nothing is double-counted.
    panel_area = float(thermal_cfg.panel_area_m2)
    for k, normal in enumerate(np.asarray(array_normals)):
        if not is_deployable[k]:
            continue  # body-mounted, already counted as a bus face
        wing_area = float(panel_count[k]) * panel_area
        front_N = np.einsum("nji,j->ni", dcm_BN, np.asarray(normal, dtype=float))
        for sign, alpha, eps in ((1.0, alpha_cell, eps_cell),
                                 (-1.0, alpha_back, eps_back)):
            face_N = sign * front_N
            cos_s = np.clip(np.einsum("ni,ni->n", face_N, sun_hat), 0.0, None)
            v = _view_factor_to_earth(env, face_N[:, None, :])[:, 0]
            absorbed += alpha * wing_area * solar_constant * cos_s * env.shadow_factor
            absorbed += (alpha * wing_area * v * solar_constant * albedo_coeff
                         * sun_over_nadir)
            absorbed += eps * wing_area * v * earth_ir
            radiating_area += wing_area
            emissivity_area += eps * wing_area

    effective_emissivity = emissivity_area / radiating_area
    capacitance = (float(cfg.spacecraft.bus.mass_kg)
                   * float(thermal_cfg.specific_heat_j_per_kg_k))

    # Net heat into the node. Electricity exported by the cells leaves here and
    # re-enters through internal_heat_w once the loads consume it.
    net_in = absorbed + internal_heat_w - generation_w
    sigma_ea = effective_emissivity * STEFAN_BOLTZMANN * radiating_area

    equilibrium = (np.clip(net_in, 1e-9, None) / sigma_ea) ** 0.25

    temperature = np.empty(env.n_samples)
    t_now = float(np.mean(equilibrium))
    dt = env.dt_s
    for i in range(env.n_samples):
        t_now += (net_in[i] - sigma_ea * t_now ** 4) * dt / capacitance
        t_now = max(t_now, 3.0)
        temperature[i] = t_now

    start = int(settle_fraction * env.n_samples)
    settled = temperature[start:]
    limits = thermal_cfg.limits_c
    stats = {
        "mean_c": float(np.mean(settled) - 273.15),
        "min_c": float(np.min(settled) - 273.15),
        "max_c": float(np.max(settled) - 273.15),
        "swing_c": float(np.max(settled) - np.min(settled)),
        "equilibrium_mean_c": float(np.mean(equilibrium[start:]) - 273.15),
        "equilibrium_min_c": float(np.min(equilibrium[start:]) - 273.15),
        "equilibrium_max_c": float(np.max(equilibrium[start:]) - 273.15),
        "mean_absorbed_env_w": float(np.mean(absorbed)),
        "mean_internal_heat_w": float(np.mean(internal_heat_w)),
        "mean_electrical_export_w": float(np.mean(generation_w)),
        "time_constant_min": float(
            capacitance / (4.0 * sigma_ea * float(np.mean(settled)) ** 3) / 60.0),
        "battery_margin_cold_c": float(np.min(settled) - 273.15
                                       - float(limits.battery_min)),
        "battery_margin_hot_c": float(float(limits.battery_max)
                                      - (np.max(settled) - 273.15)),
        "electronics_margin_cold_c": float(np.min(settled) - 273.15
                                           - float(limits.electronics_min)),
        "electronics_margin_hot_c": float(float(limits.electronics_max)
                                          - (np.max(settled) - 273.15)),
    }
    return SingleNodeResult(
        temperature_k=temperature,
        equilibrium_k=equilibrium,
        absorbed_env_w=absorbed,
        internal_heat_w=internal_heat_w,
        radiating_area_m2=radiating_area,
        effective_emissivity=effective_emissivity,
        thermal_capacitance_j_k=capacitance,
        stats=stats,
    )


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
