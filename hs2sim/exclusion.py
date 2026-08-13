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

from . import adcs, comms, conops, geometry, power
from .adcs import TorqueAuthority
from .config import MissionConfig
from .environment import EnvironmentResult

# Dotted config paths the sweep overrides. The +z group moves together for the
# reason given in the module docstring.
LOST_SUN_PATHS = (
    "spacecraft.sensors.lost_camera.sun_exclusion_deg",
    "spacecraft.sensors.star_tracker.sun_exclusion_deg",
)
LOST_EARTH_PATHS = (
    "spacecraft.sensors.lost_camera.earth_exclusion_deg",
    "spacecraft.sensors.star_tracker.earth_exclusion_deg",
)
LOST_PATHS = LOST_SUN_PATHS + LOST_EARTH_PATHS
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
          pointing_margin_deg: float | None = None,
          log: Callable[[str], None] | None = None) -> dict:
    """Re-solve pointing and re-run the scheduler over the exclusion grid.

    Every cell is solved with the pointing margin applied, so the numbers are
    what the vehicle can actually fly rather than what the geometry would allow
    a perfect pointer. ``pointing_margin_deg`` defaults to the configured
    control + knowledge budget.

    Returns a dict with the axis values, a flat list of per-point results, and
    matrices (indexed ``[lost][found]``) of the quantities worth plotting.
    """
    if pointing_margin_deg is None:
        pointing_margin_deg = adcs.pointing_margin_deg(cfg)
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
                array_normals=array.normals, array_weights=array.peak_w,
                pointing_margin_deg=pointing_margin_deg)
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
        "pointing_margin_deg": float(pointing_margin_deg),
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


def plus_z_decomposition(cfg: MissionConfig,
                         env: EnvironmentResult,
                         array: power.ArrayGeometry,
                         lost_deg: Sequence[float],
                         *,
                         baseline_lost_deg: float,
                         n_grid: int = 32,
                         pointing_margin_deg: float | None = None,
                         log: Callable[[str], None] | None = None) -> list[dict]:
    """Split the +z keep-out into its Sun half and its Earth half.

    The main sweep moves both together, because that is how the requirement is
    written. But "the +z cone costs 28 points of feasibility at 80 deg" is not
    an actionable statement until you know *which* half is spending it -- a
    baffle helps the Sun exclusion, and nothing helps the Earth one.

    So each is moved on its own, with the other held at the baseline, at the
    baseline FOUND exclusion. Feasibility only: the scheduler is not run,
    because the question is about the constraint, not the timeline.
    """
    if pointing_margin_deg is None:
        pointing_margin_deg = adcs.pointing_margin_deg(cfg)
    rows: list[dict] = []
    for value in lost_deg:
        variants = {
            "sun_only": {p: float(value) for p in LOST_SUN_PATHS},
            "earth_only": {p: float(value) for p in LOST_EARTH_PATHS},
        }
        row: dict = {"lost_deg": float(value)}
        for name, overrides in variants.items():
            trial = cfg.copy_with(**overrides)
            pointing = geometry.solve_experiment_pointing(
                trial, env, n_azimuth=n_grid, n_roll=n_grid,
                array_normals=array.normals, array_weights=array.peak_w,
                pointing_margin_deg=pointing_margin_deg)
            row[f"{name}_feasible"] = float(np.mean(pointing.feasible))
            row[f"{name}_no_legal_roll"] = float(np.mean(
                pointing.reject_reason == geometry.REJECT_NO_ROLL))
        rows.append(row)
        if log is not None:
            log(f"    LOST {value:.0f} deg: Sun half alone "
                f"{row['sun_only_feasible']*100:.1f} % feasible, Earth half "
                f"alone {row['earth_only_feasible']*100:.1f} %")
    return rows


def margin_sweep(cfg: MissionConfig,
                 env: EnvironmentResult,
                 array: power.ArrayGeometry,
                 standby_dcm: np.ndarray,
                 authority: TorqueAuthority,
                 passes: Sequence[comms.Pass],
                 margins_deg: Sequence[float],
                 *,
                 n_grid: int = 32,
                 payload_rate_hz: float = 0.2,
                 log: Callable[[str], None] | None = None) -> list[dict]:
    """Feasibility and science as a function of the pointing-error buffer.

    The exclusion angles are a payload requirement; the pointing margin is an
    ADCS *performance* number, and it enters the same inequality. Ten degrees
    of extra keep-out and ten degrees of pointing error cost exactly the same
    thing, which makes this the natural companion to the cone sweep: it prices
    ADCS work in the same currency as optical work.

    The cones are held at their configured values throughout; only the buffer
    moves.
    """
    rows: list[dict] = []
    for value in margins_deg:
        pointing = geometry.solve_experiment_pointing(
            cfg, env, n_azimuth=n_grid, n_roll=n_grid,
            array_normals=array.normals, array_weights=array.peak_w,
            pointing_margin_deg=float(value))
        result = conops.simulate(cfg, env, array, pointing, standby_dcm,
                                 authority, payload_rate_hz, passes)
        summary = conops.summarise(cfg, env, result)
        rows.append({
            "margin_deg": float(value),
            "feasible_fraction": float(np.mean(pointing.feasible)),
            "images_per_day_ceiling": float(
                np.mean(pointing.feasible) * 86400.0 * payload_rate_hz
                * int(cfg.payload.n_cameras)),
            "images_per_day": float(summary["images_per_day"]),
            "frac_experiment": float(summary["frac_experiment"]),
            "energy_margin_w": float(summary["energy_margin_w"]),
            "reject_reasons": _reject_fractions(pointing),
        })
        if log is not None:
            log(f"    margin {value:.1f} deg: feasible "
                f"{rows[-1]['feasible_fraction']*100:.1f} %, "
                f"{rows[-1]['images_per_day']:,.0f} images/day")
    return rows


def margin_characterise(sweep_result: dict,
                        baseline_margin_deg: float) -> dict:
    """Price the pointing budget: feasibility lost per degree of error.

    Also cross-checks the buffer against the cone grid. Padding every keep-out
    by ``m`` degrees is, by construction, the same inequality as moving both
    cones out by ``m``, so a buffer of ``m`` must reproduce the grid cell at
    ``(baseline_lost + m, baseline_found + m)``. The two are computed by
    different code paths -- one adds ``m`` to the angle inside the solver, the
    other rewrites the config and re-reads it -- so agreement is a real check
    on both.
    """
    rows = sweep_result.get("margin_sweep") or []
    if len(rows) < 2:
        return {}
    ordered = sorted(rows, key=lambda r: r["margin_deg"])
    zero = ordered[0]
    out: dict = {
        "zero_margin_feasible_fraction": zero["feasible_fraction"],
        "zero_margin_deg": zero["margin_deg"],
    }
    at_baseline = next((r for r in ordered
                        if abs(r["margin_deg"] - baseline_margin_deg) < 1e-6),
                       None)
    if at_baseline is not None:
        out["baseline_margin_deg"] = at_baseline["margin_deg"]
        out["baseline_feasible_fraction"] = at_baseline["feasible_fraction"]
        out["baseline_images_per_day"] = at_baseline["images_per_day"]
        span = at_baseline["margin_deg"] - zero["margin_deg"]
        if span > 0:
            out["cost_of_baseline_budget_pp"] = float(
                (zero["feasible_fraction"]
                 - at_baseline["feasible_fraction"]) * 100.0)
            out["pp_per_deg_at_baseline"] = float(
                out["cost_of_baseline_budget_pp"] / span)
    # Slope over the whole swept range, and over the top half, so a knee shows.
    total_span = ordered[-1]["margin_deg"] - zero["margin_deg"]
    if total_span > 0:
        out["pp_per_deg_overall"] = float(
            (zero["feasible_fraction"] - ordered[-1]["feasible_fraction"])
            * 100.0 / total_span)
    mid = ordered[len(ordered) // 2]
    upper_span = ordered[-1]["margin_deg"] - mid["margin_deg"]
    if upper_span > 0:
        out["pp_per_deg_upper_half"] = float(
            (mid["feasible_fraction"] - ordered[-1]["feasible_fraction"])
            * 100.0 / upper_span)

    # Where does the buffer stop being free? Last margin still matching the
    # zero-margin answer, and the first that does not.
    free_to = ordered[0]["margin_deg"]
    binds_at = None
    for row in ordered[1:]:
        if abs(row["feasible_fraction"] - zero["feasible_fraction"]) <= 2e-3:
            free_to = row["margin_deg"]
        else:
            binds_at = row["margin_deg"]
            break
    out["free_up_to_deg"] = float(free_to)
    out["binds_at_deg"] = binds_at

    # -- cross-check against the cone grid -----------------------------------
    lost = sweep_result.get("lost_deg") or []
    found = sweep_result.get("found_deg") or []
    grid = (sweep_result.get("matrices") or {}).get("feasible_fraction")
    base = sweep_result.get("baseline") or {}
    # The grid cells are themselves solved with the configured buffer, so a
    # cell at (L, F) enforces (L + grid_margin, F + grid_margin). Forgetting
    # that shifts the comparison by the buffer and makes an exact identity look
    # like a 1-2 point disagreement.
    grid_margin = float(sweep_result.get("pointing_margin_deg") or 0.0)
    checks = []
    if grid and "lost_deg" in base and "found_deg" in base:
        for row in ordered:
            m = row["margin_deg"]
            want_lost = base["lost_deg"] + m - grid_margin
            want_found = base["found_deg"] + m - grid_margin
            if want_lost in lost and want_found in found:
                cell = grid[lost.index(want_lost)][found.index(want_found)]
                checks.append({
                    "margin_deg": m,
                    "equivalent_cell": [want_lost, want_found],
                    "margin_feasible": row["feasible_fraction"],
                    "grid_feasible": float(cell),
                    "difference_pp": float(
                        (row["feasible_fraction"] - cell) * 100.0),
                })
    out["grid_equivalence"] = checks
    if checks:
        out["max_equivalence_difference_pp"] = float(
            max(abs(c["difference_pp"]) for c in checks))
    return out


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

    # -- which constraint is actually doing the rejecting ---------------------
    # This changes across the grid, and that is the point of sweeping far
    # enough. Derived from `points` rather than a matrix so it works on a
    # sweep produced before these matrices existed.
    points = sweep_result.get("points") or []
    if points:
        for reason in ("no_sunlit_limb", "sun_in_found_fov", "no_legal_roll"):
            worst = max(points, key=lambda p: p["reject_reasons"][reason])
            least = min(points, key=lambda p: p["reject_reasons"][reason])
            out[f"max_{reason}"] = float(worst["reject_reasons"][reason])
            out[f"max_{reason}_at"] = [worst["lost_deg"], worst["found_deg"]]
            out[f"{reason}_span_pp"] = float(
                (worst["reject_reasons"][reason]
                 - least["reject_reasons"][reason]) * 100.0)
        # Where does the +z cone stop being a bystander and start being the
        # binding constraint? The first LOST value at which `no legal roll`
        # out-rejects `sun in FOUND` anywhere on the FOUND axis.
        roll_binds_at = None
        for value in lost:
            row = [p for p in points if p["lost_deg"] == value]
            if any(p["reject_reasons"]["no_legal_roll"]
                   > p["reject_reasons"]["sun_in_found_fov"] for p in row):
                roll_binds_at = float(value)
                break
        out["no_legal_roll_dominates_above_deg"] = roll_binds_at
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
