"""Solar array generation, load modelling and battery state of charge.

Array output uses the cosine law on each panel independently:

    P = sum_k  peak_k * max(0, n_k . s)  * shadow * mppt * degradation

where ``n_k`` is the panel normal rotated into the inertial frame by the
current attitude and ``s`` is the Sun direction. ``peak_k`` is the user-supplied
"no cosine losses" number, so all that is added here is geometry, eclipse and a
small MPPT/harness efficiency.

Body-mounted panels are additionally shadowed by the bus whenever the Sun is
behind the panel plane -- that falls out of the ``max(0, ...)`` -- and the
deployable wing is treated as unobstructed, which is the point of deploying it.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from .config import AttrDict, MissionConfig
from .environment import EnvironmentResult


@dataclasses.dataclass
class ArrayGeometry:
    """A solar array option flattened into normals and peak powers."""

    name: str
    description: str
    normals: np.ndarray      # (K,3) body frame unit normals
    peak_w: np.ndarray       # (K,) watts at normal incidence
    panel_names: list[str]

    @property
    def peak_total_w(self) -> float:
        return float(np.sum(self.peak_w))


def load_array_geometry(name: str, option: AttrDict) -> ArrayGeometry:
    normals = []
    peaks = []
    names = []
    for panel in option.panels:
        n = np.asarray(panel.normal, dtype=float)
        normals.append(n / np.linalg.norm(n))
        peaks.append(float(panel.peak_w))
        names.append(str(panel.name))
    return ArrayGeometry(
        name=name,
        description=str(option.get("description", "")).strip(),
        normals=np.asarray(normals),
        peak_w=np.asarray(peaks),
        panel_names=names,
    )


def all_array_geometries(cfg: MissionConfig) -> list[ArrayGeometry]:
    return [load_array_geometry(name, option) for name, option in cfg.array_options()]


def generation_w(cfg: MissionConfig,
                 env: EnvironmentResult,
                 array: ArrayGeometry,
                 dcm_BN: np.ndarray) -> np.ndarray:
    """Instantaneous array output for a given attitude history.

    ``dcm_BN`` is (N,3,3) mapping inertial to body. Panel normals are body
    vectors, so the inertial normal is ``dcm_BN.T @ n``.
    """
    sun_hat = env.sun_unit()                              # (N,3)
    settings = cfg.spacecraft.solar_array
    efficiency = float(settings.mppt_efficiency) * float(settings.degradation)

    # normals_N[n,k,:] = dcm_BN[n].T @ normals[k]
    normals_N = np.einsum("nji,kj->nki", dcm_BN, array.normals)
    cosines = np.clip(np.einsum("nki,ni->nk", normals_N, sun_hat), 0.0, None)
    raw = cosines @ array.peak_w                          # (N,)
    return raw * env.shadow_factor * efficiency


def per_panel_cosine(cfg: MissionConfig,
                     env: EnvironmentResult,
                     array: ArrayGeometry,
                     dcm_BN: np.ndarray) -> np.ndarray:
    """(N,K) cosine incidence factor per panel, including eclipse."""
    sun_hat = env.sun_unit()
    normals_N = np.einsum("nji,kj->nki", dcm_BN, array.normals)
    cosines = np.clip(np.einsum("nki,ni->nk", normals_N, sun_hat), 0.0, None)
    return cosines * env.shadow_factor[:, None]


# ---------------------------------------------------------------------------
# Loads
# ---------------------------------------------------------------------------

def component_power_w(cfg: MissionConfig, component: str) -> float:
    """Peak power x quantity x margin for one component."""
    spec = cfg.power.components[component]
    margin = 1.0 + float(cfg.power.margin)
    return float(spec.peak_w) * int(spec.qty) * margin


def mode_power_w(cfg: MissionConfig, mode: str, heater_duty: float | None = None) -> float:
    """Average electrical load in a CONOPS mode, watts.

    Built from peak power x qty x duty cycle -- the only budget numbers the
    user flagged as trustworthy -- rather than from the spreadsheet's
    pre-computed mode totals.
    """
    duty_map = cfg.power.modes[mode]
    heater_duty = (float(cfg.power.heater_duty_cycle)
                   if heater_duty is None else float(heater_duty))
    total = 0.0
    for component, duty in duty_map.items():
        d = heater_duty if duty == "heater_duty" else float(duty)
        total += component_power_w(cfg, component) * d
    return total


def mode_power_table(cfg: MissionConfig, heater_duty: float | None = None) -> dict[str, float]:
    return {mode: mode_power_w(cfg, mode, heater_duty)
            for mode in cfg.power.modes}


def subsystem_breakdown(cfg: MissionConfig, mode: str,
                        heater_duty: float | None = None) -> dict[str, float]:
    """Mode load split by subsystem, for reporting against the budget."""
    duty_map = cfg.power.modes[mode]
    heater_duty = (float(cfg.power.heater_duty_cycle)
                   if heater_duty is None else float(heater_duty))
    out: dict[str, float] = {}
    for component, duty in duty_map.items():
        d = heater_duty if duty == "heater_duty" else float(duty)
        subsystem = str(cfg.power.components[component].subsystem)
        out[subsystem] = out.get(subsystem, 0.0) + component_power_w(cfg, component) * d
    return out


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class BatteryHistory:
    soc: np.ndarray             # (N,) state of charge, 0-1
    net_w: np.ndarray           # (N,) generation minus load
    depleted: np.ndarray        # (N,) bool, hit the DoD floor
    min_soc: float
    end_soc: float
    energy_balance_wh_per_day: float


def integrate_battery(cfg: MissionConfig,
                      env: EnvironmentResult,
                      generation: np.ndarray,
                      load: np.ndarray) -> BatteryHistory:
    """Walk the battery forward in time.

    Charging is derated by the round-trip efficiency; discharging is not, which
    is the conservative convention. The SOC floor is the depth-of-discharge
    limit, and the ``depleted`` flag records where the CONOPS scheduler would
    have had to shed load.
    """
    battery = cfg.spacecraft.battery
    capacity_wh = float(battery.capacity_wh)
    floor = 1.0 - float(battery.depth_of_discharge_limit)
    efficiency = float(battery.round_trip_efficiency)
    dt_h = env.dt_s / 3600.0

    net = generation - load
    soc = np.empty(env.n_samples)
    depleted = np.zeros(env.n_samples, dtype=bool)
    level = float(battery.initial_soc) * capacity_wh

    for i in range(env.n_samples):
        delta = net[i] * dt_h
        if delta > 0:
            delta *= efficiency
        level = min(capacity_wh, level + delta)
        if level < floor * capacity_wh:
            level = floor * capacity_wh
            depleted[i] = True
        soc[i] = level / capacity_wh

    return BatteryHistory(
        soc=soc,
        net_w=net,
        depleted=depleted,
        min_soc=float(np.min(soc)),
        end_soc=float(soc[-1]),
        energy_balance_wh_per_day=float(np.mean(net) * 24.0),
    )


def orbit_average_generation(cfg: MissionConfig,
                             env: EnvironmentResult,
                             array: ArrayGeometry,
                             dcm_BN: np.ndarray) -> dict[str, float]:
    """Summary statistics for one array geometry under one attitude profile."""
    gen = generation_w(cfg, env, array, dcm_BN)
    cosines = per_panel_cosine(cfg, env, array, dcm_BN)
    sunlit = env.shadow_factor > 0.5
    return {
        "peak_capability_w": array.peak_total_w,
        "orbit_average_w": float(np.mean(gen)),
        "sunlit_average_w": float(np.mean(gen[sunlit])) if sunlit.any() else 0.0,
        "peak_achieved_w": float(np.max(gen)),
        "capacity_factor": float(np.mean(gen) / array.peak_total_w),
        "mean_incidence_deg": float(np.degrees(np.arccos(np.clip(
            np.mean(cosines[sunlit]) if sunlit.any() else 0.0, 0, 1)))),
        "energy_wh_per_day": float(np.mean(gen) * 24.0),
    }
