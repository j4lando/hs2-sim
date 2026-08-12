"""Exclusion-angle trade study.

The keep-out cones are the requirement most directly under the payload team's
control, and they are the requirement that decides how much of the orbit has a
legal experiment attitude at all. At the baseline (40 deg on +z, 70 deg on
FOUND) the +z cone never binds and FOUND's Sun keep-out costs roughly 8 % of
the timeline, so the obvious question is what a tighter or looser cone is
actually worth in science.

This module answers it by re-solving the pointing problem on a grid of
(lost_deg, found_deg) and re-running the mode scheduler at each point, so the
answer is in units the mission cares about -- images per day -- rather than in
solid angle.

Two conventions, both deliberate:

* ``lost_deg`` moves the +z keep-out against **both** the Sun and Earth. The
  requirement quotes a single angle covering both ("may not have earth or the
  sun in their exclusion angle"), and the star tracker shares the face with
  LOST, so all four numbers move together.
* ``found_deg`` moves FOUND's **Sun** keep-out only. FOUND's field of view is a
  fixed optical property; its Sun exclusion is the thing a baffle changes.

Everything except the cones is held fixed: same orbit, same array geometry,
same payload cadence, same ground stations. Only the constraint changes, so
differences between grid points are attributable to the constraint alone.
"""

from __future__ import annotations

import time
from typing import Callable, Sequence

import numpy as np

from . import comms, conops, geometry, power
from .adcs import TorqueAuthority
from .config import MissionConfig
from .environment import EnvironmentResult

# Dotted config paths the sweep overrides. The +z group moves together for the
# reason given in the module docstring.
LOST_PATHS = (
    "spacecraft.sensors.lost_camera.sun_exclusion_deg",
    "spacecraft.sensors.lost_camera.earth_exclusion_deg",
    "spacecraft.sensors.star_tracker.sun_exclusion_deg",
    "spacecraft.sensors.star_tracker.earth_exclusion_deg",
)
FOUND_PATH = "spacecraft.sensors.found_camera.sun_exclusion_deg"


def _reject_fractions(pointing: geometry.PointingResult) -> dict[str, float]:
    return {
        "no_sunlit_limb": float(np.mean(
            pointing.reject_reason == geometry.REJECT_NO_SUNLIT_LIMB)),
        "sun_in_found_fov": float(np.mean(
            pointing.reject_reason == geometry.REJECT_SUN_IN_FOUND)),
        "no_legal_roll": float(np.mean(
            pointing.reject_reason == geometry.REJECT_NO_ROLL)),
    }


def sweep(cfg: MissionConfig,
          env: EnvironmentResult,
          array: power.ArrayGeometry,
          standby_dcm: np.ndarray,
          authority: TorqueAuthority,
          passes: Sequence[comms.Pass],
          lost_deg: Sequence[float],
          found_deg: Sequence[float],
          *,
          n_grid: int = 32,
          payload_rate_hz: float = 0.2,
          log: Callable[[str], None] | None = None) -> dict:
    """Re-solve pointing and re-run the scheduler over the exclusion grid.

    Returns a dict with the axis values, a flat list of per-point results, and
    matrices (indexed ``[lost][found]``) of the quantities worth plotting.
    """
    lost_values = [float(v) for v in lost_deg]
    found_values = [float(v) for v in found_deg]
    points: list[dict] = []

    n_total = len(lost_values) * len(found_values)
    started = time.time()

    for row, lost in enumerate(lost_values):
        for col, found in enumerate(found_values):
            overrides = {path: lost for path in LOST_PATHS}
            overrides[FOUND_PATH] = found
            trial = cfg.copy_with(**overrides)

            pointing = geometry.solve_experiment_pointing(
                trial, env, n_azimuth=n_grid, n_roll=n_grid,
                array_normals=array.normals, array_weights=array.peak_w)
            result = conops.simulate(trial, env, array, pointing, standby_dcm,
                                     authority, payload_rate_hz, passes)
            summary = conops.summarise(trial, env, result)

            feasible_fraction = float(np.mean(pointing.feasible))
            # What the cones alone allow: every legal opportunity used, nothing
            # lost to slewing, downlink or battery holds. This is a clean
            # function of the constraint, which the realised number is not --
            # see `characterise` for why that matters.
            ceiling = (feasible_fraction * 86400.0 * payload_rate_hz
                       * int(trial.payload.n_cameras))

            point = {
                "lost_deg": lost,
                "found_deg": found,
                "feasible_fraction": feasible_fraction,
                "images_per_day_ceiling": float(ceiling),
                "reject_reasons": _reject_fractions(pointing),
                "images_per_day": float(summary["images_per_day"]),
                "experiments_per_day": float(summary["experiments_per_day"]),
                "frac_experiment": float(summary["frac_experiment"]),
                "frac_standby": float(summary["frac_standby"]),
                "frac_slew": float(summary["frac_slew"]),
                "frac_downlink": float(summary["frac_downlink"]),
                "slews_per_day": float(summary["slews_per_day"]),
                "energy_margin_w": float(summary["energy_margin_w"]),
                "min_soc": float(summary["min_soc"]),
                "battery_limited": bool(summary["battery_limited"]),
            }
            points.append(point)

            if log is not None:
                done = len(points)
                elapsed = time.time() - started
                eta = elapsed / done * (n_total - done)
                log(f"    LOST {lost:.0f} deg / FOUND {found:.0f} deg: "
                    f"feasible {point['feasible_fraction']*100:5.1f} %, "
                    f"experiment {point['frac_experiment']*100:5.1f} %, "
                    f"{point['images_per_day']:,.0f} images/day "
                    f"[{done}/{n_total}, ETA {eta/60:.1f} min]")

    def matrix(key: str) -> list[list[float]]:
        return [[float(points[r * len(found_values) + c][key])
                 for c in range(len(found_values))]
                for r in range(len(lost_values))]

    return {
        "lost_deg": lost_values,
        "found_deg": found_values,
        "n_grid": int(n_grid),
        "payload_rate_hz": float(payload_rate_hz),
        "points": points,
        "matrices": {
            "feasible_fraction": matrix("feasible_fraction"),
            "images_per_day_ceiling": matrix("images_per_day_ceiling"),
            "images_per_day": matrix("images_per_day"),
            "frac_experiment": matrix("frac_experiment"),
            "energy_margin_w": matrix("energy_margin_w"),
            "slews_per_day": matrix("slews_per_day"),
        },
        "runtime_s": time.time() - started,
    }


def characterise(sweep_result: dict, feasibility_tol: float = 2e-3) -> dict:
    """Separate what the cones do from what the scheduler does.

    Two different things move ``images_per_day`` across this grid:

    * The constraint itself, which changes how much of the timeline has a legal
      attitude at all. That is ``feasible_fraction``, and it is a deterministic
      function of the cone angles.
    * The mode scheduler, which decides how much of that legal time survives
      slewing. Changing a keep-out changes which rolls are legal, which changes
      the attitude the solver picks, which changes where the big repoints land.
      The vehicle spends ~half its time slewing, so this is a large lever, and
      it is *not* attributable to the cone.

    The grid separates them for free: several cells share an identical
    feasibility (the +z cone does nothing over part of its range), so the
    spread in realised images across those cells measures the scheduler's own
    sensitivity. Differences smaller than that are noise, not trade space.
    """
    lost = sweep_result["lost_deg"]
    found = sweep_result["found_deg"]
    feasible = sweep_result["matrices"]["feasible_fraction"]
    images = sweep_result["matrices"]["images_per_day"]

    out: dict = {}

    # -- scheduler noise floor ------------------------------------------------
    groups: dict[int, list[float]] = {}
    for r in range(len(lost)):
        for c in range(len(found)):
            key = int(round(feasible[r][c] / feasibility_tol))
            groups.setdefault(key, []).append(images[r][c])
    spreads = [(max(v) - min(v), sum(v) / len(v))
               for v in groups.values() if len(v) > 1]
    if spreads:
        worst_abs, at_mean = max(spreads, key=lambda p: p[0])
        out["scheduler_noise_images_per_day"] = float(worst_abs)
        out["scheduler_noise_relative"] = float(worst_abs / at_mean) if at_mean else None
    else:
        out["scheduler_noise_images_per_day"] = None
        out["scheduler_noise_relative"] = None

    # -- FOUND: smooth and monotone ------------------------------------------
    # Mean slope across the FOUND axis, in percentage points of feasibility per
    # degree of Sun keep-out. Averaged over the LOST rows.
    if len(found) > 1:
        slopes = [(feasible[r][0] - feasible[r][-1]) * 100.0 / (found[-1] - found[0])
                  for r in range(len(lost))]
        out["found_feasibility_pp_per_deg"] = float(sum(slopes) / len(slopes))
        # The average hides structure: the price per degree is not uniform
        # along the axis, so carry the individual steps too.
        steps = []
        for c in range(len(found) - 1):
            per_row = [(feasible[r][c] - feasible[r][c + 1]) * 100.0
                       / (found[c + 1] - found[c]) for r in range(len(lost))]
            steps.append({
                "from_deg": found[c],
                "to_deg": found[c + 1],
                "pp_per_deg": float(sum(per_row) / len(per_row)),
            })
        out["found_steps"] = steps
        out["found_step_min_pp_per_deg"] = float(min(s["pp_per_deg"] for s in steps))
        out["found_step_max_pp_per_deg"] = float(max(s["pp_per_deg"] for s in steps))
        out["found_monotone"] = all(s["pp_per_deg"] >= -1e-9 for s in steps)
    out["found_feasible_span_pp"] = float(
        (max(feasible[r][0] for r in range(len(lost)))
         - min(feasible[r][-1] for r in range(len(lost)))) * 100.0)

    # -- LOST: a dead band, then a knee --------------------------------------
    # Report the largest +z keep-out that still matches the loosest row. Below
    # that the cone costs nothing at all, which is the actionable result: it is
    # margin available for free.
    reference = feasible[0]
    free_band = lost[0]
    for r in range(1, len(lost)):
        if all(abs(feasible[r][c] - reference[c]) <= feasibility_tol
               for c in range(len(found))):
            free_band = lost[r]
        else:
            break
    out["lost_free_band_deg"] = float(free_band)
    out["lost_binds_above_deg"] = (
        float(lost[lost.index(free_band) + 1])
        if lost.index(free_band) + 1 < len(lost) else None)
    out["lost_feasible_span_pp"] = float(
        (max(feasible[r][0] for r in range(len(lost)))
         - min(feasible[r][0] for r in range(len(lost)))) * 100.0)
    return out


def sensitivity(sweep_result: dict,
                baseline_lost: float,
                baseline_found: float) -> dict:
    """Local slopes about the baseline point, in images/day per degree.

    A trade study is only actionable if it says which knob to turn. These are
    one-sided differences to the neighbouring grid points, which is the honest
    resolution of the sweep -- the grid is 10 deg, so anything finer would be
    invented.

    The slopes are taken on the **ceiling** (feasibility x cadence), not on the
    realised image count. Realised images carry the scheduler sensitivity
    described in `characterise`, which at this grid spacing is comparable to
    the effect being measured; differencing it would report noise as a slope.
    """
    lost = sweep_result["lost_deg"]
    found = sweep_result["found_deg"]
    images = sweep_result["matrices"]["images_per_day_ceiling"]
    realised = sweep_result["matrices"]["images_per_day"]
    feasible = sweep_result["matrices"]["feasible_fraction"]

    if baseline_lost not in lost or baseline_found not in found:
        return {}
    r = lost.index(baseline_lost)
    c = found.index(baseline_found)

    out: dict[str, float | None] = {
        "baseline_images_per_day": realised[r][c],
        "baseline_images_per_day_ceiling": images[r][c],
        "baseline_feasible_fraction": feasible[r][c],
    }

    def slope(v0, v1, a0, a1):
        return None if a1 == a0 else (v1 - v0) / (a1 - a0)

    # "Looser" means a *smaller* keep-out for LOST (less sky excluded) and a
    # smaller Sun exclusion for FOUND. Both grids ascend, so the looser
    # neighbour is the previous index.
    out["d_images_per_deg_lost_looser"] = (
        slope(images[r][c], images[r - 1][c], lost[r], lost[r - 1])
        if r > 0 else None)
    out["d_images_per_deg_lost_tighter"] = (
        slope(images[r][c], images[r + 1][c], lost[r], lost[r + 1])
        if r + 1 < len(lost) else None)
    out["d_images_per_deg_found_looser"] = (
        slope(images[r][c], images[r][c - 1], found[c], found[c - 1])
        if c > 0 else None)
    out["d_images_per_deg_found_tighter"] = (
        slope(images[r][c], images[r][c + 1], found[c], found[c + 1])
        if c + 1 < len(found) else None)
    return out
