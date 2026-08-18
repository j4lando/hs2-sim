#!/usr/bin/env python3
"""Run the HS-2 detumble / sun-acquisition Monte Carlo.

Starts the spacecraft in a random post-deployment tumble and flies it under
magnetorquer-only control with an IMU and a set of sun sensors, once for each
sun sensor geometry under trade. See docs/DETUMBLE.md for the algorithm and
the assumptions.

Usage:
    python run_detumble.py                    # 200 trials x 6 h, 3 geometries
    python run_detumble.py --quick            # 32 trials x 3 h, 4 RAAN cases
    python run_detumble.py --trials 500       # more trials, same cost per case
    python run_detumble.py --geometry six_faces
    python run_detumble.py --array A_2panel_90
    python run_detumble.py --no-albedo        # sensitivity: perfect sun sensors

Outputs:
    results/detumble_summary.json   every number this script computed
    results/detumble_*.png          figures (only if matplotlib is available)

Basilisk is required: the orbit, magnetic field, Sun and eclipse all come from
`hs2sim.environment.propagate`, exactly as in run_analysis.py. Only the
attitude dynamics are integrated here.
"""

from __future__ import annotations

import argparse
import json
import math
import time

import numpy as np

from hs2sim import detumble, environment
from hs2sim.config import MissionConfig, RESULTS_DIR


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        value = float(obj)
        return value if math.isfinite(value) else None
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trials", type=int, default=None,
                        help="Monte Carlo trials per geometry "
                             "(they run simultaneously, so this is nearly free)")
    parser.add_argument("--hours", type=float, default=None,
                        help="length of each trial in hours")
    parser.add_argument("--cases", type=int, default=None,
                        help="number of Basilisk propagations, at evenly "
                             "spaced RAANs -- this is the real cost knob")
    parser.add_argument("--geometry", action="append", default=None,
                        metavar="NAME",
                        help="only run this sun sensor geometry; repeatable")
    parser.add_argument("--array", default=None, metavar="OPTION",
                        help="solar array option to point and score against "
                             "(default: the one in config/detumble.yaml)")
    parser.add_argument("--quick", action="store_true",
                        help="short, coarse run for a smoke test")
    parser.add_argument("--no-albedo", action="store_true",
                        help="switch off Earth albedo on the sun sensors, to "
                             "separate the albedo error from everything else")
    parser.add_argument("--seed", type=int, default=None,
                        help="override the Monte Carlo seed")
    args = parser.parse_args()

    cfg = MissionConfig()
    if cfg.detumble is None:
        print("ERROR: config/detumble.yaml is missing.")
        return 1

    mc = cfg.detumble.monte_carlo
    n_trials = args.trials or (32 if args.quick else int(mc.trials))
    duration_s = (args.hours * 3600.0 if args.hours is not None
                  else (10800.0 if args.quick else float(mc.duration_s)))
    n_cases = args.cases or (4 if args.quick else
                             int(cfg.detumble.environment.n_raan_cases))
    array_option = args.array or str(mc.array_option)
    seed = args.seed if args.seed is not None else int(mc.seed)
    if args.no_albedo:
        cfg.detumble.environment.albedo.enabled = False

    names = args.geometry or [name for name, _ in cfg.sensor_geometries()]
    unknown = [n for n in names if n not in cfg.detumble.sensor_geometries]
    if unknown:
        print(f"ERROR: unknown sun sensor geometry {unknown}. "
              f"Known: {list(cfg.detumble.sensor_geometries)}")
        return 1

    if not environment.basilisk_available():
        print("ERROR: Basilisk is not importable in this interpreter.\n"
              "       Install it from https://avslab.github.io/basilisk/ "
              "-- it is not on PyPI.\n"
              "       The detumble sim takes its orbit, magnetic field, Sun "
              "and eclipse from it.")
        return 1

    RESULTS_DIR.mkdir(exist_ok=True)
    log(f"{n_trials} trials x {duration_s / 3600:.1f} h over {n_cases} "
        f"orbit cases, {len(names)} sun sensor geometries")
    log(f"array under test: {array_option}; "
        f"albedo {'off' if args.no_albedo else 'on'}")

    # One set of propagations, shared by every geometry, so the layouts are
    # compared over identical orbits, fields and eclipse timing.
    spread_s = float(cfg.detumble.environment.start_spread_s)
    log("propagating the environment with Basilisk")
    cases = detumble.propagate_cases(cfg, n_cases, duration_s + spread_s, log=log)
    env = detumble.build_environment_ensemble(
        cases, n_trials, duration_s, np.random.default_rng(seed))
    log(f"beta angle spanned: {env.beta_deg.min():.1f} to "
        f"{env.beta_deg.max():.1f} deg")

    results: dict = {
        "configuration": {
            "n_trials": n_trials,
            "duration_s": duration_s,
            "n_raan_cases": n_cases,
            "array_option": array_option,
            "albedo_enabled": not args.no_albedo,
            "seed": seed,
            "environment": environment.summarise(cases[0]),
        },
        "sky_coverage": {},
        "geometries": {},
    }

    for name, geometry in cfg.sensor_geometries():
        results["sky_coverage"][name] = detumble.sky_coverage(
            cfg, np.asarray(geometry.boresights, dtype=float))

    runs = {}
    for name in names:
        log(f"flying {name}")
        started = time.time()
        run = detumble.run_monte_carlo(cfg, name, env, duration_s=duration_s,
                                       array_option=array_option, seed=seed)
        runs[name] = run
        results["geometries"][name] = run.summary
        summary = run.summary
        log(f"  {time.time() - started:.0f} s: "
            f"detumbled {100 * summary['detumble_success_rate']:.0f} % "
            f"(median {summary['detumble_time_s_median'] / 60:.0f} min), "
            f"steady capture {summary['steady_capture_normalised_median']:.2f} "
            f"of the achievable maximum")

    out_path = RESULTS_DIR / "detumble_summary.json"
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(to_jsonable(results), handle, indent=2, sort_keys=True)
    log(f"wrote {out_path}")

    try:
        from hs2sim.output import detumble_plots
    except ImportError as exc:            # pragma: no cover - optional deps
        log(f"skipping figures: {exc}")
        return 0
    detumble_plots.make_all(runs, results, RESULTS_DIR, log=log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
