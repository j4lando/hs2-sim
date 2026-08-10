#!/usr/bin/env python3
"""Run the full HS-2 operations analysis and write results to ``results/``.

Usage:
    python run_analysis.py                  # full run
    python run_analysis.py --quick          # 1 day, coarse search, no sweeps
    python run_analysis.py --days 30        # override the propagation length

Outputs:
    results/summary.json      every number this script computed
    results/report.md         a readable narrative of the findings
    results/*.png             plots (only if matplotlib is available)
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import time

import numpy as np

from hs2sim import adcs, comms, conops, environment, geometry, power, thermal
from hs2sim.config import MissionConfig, RESULTS_DIR


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=float, default=None,
                        help="override propagation length in days")
    parser.add_argument("--step", type=float, default=None,
                        help="override time step in seconds")
    parser.add_argument("--quick", action="store_true",
                        help="short run with a coarse attitude search")
    parser.add_argument("--no-sweep", action="store_true",
                        help="skip the RAAN / beta-angle sweep")
    args = parser.parse_args()

    cfg = MissionConfig()
    if args.quick:
        cfg.mission.simulation.duration_days = 1.0
        cfg.mission.simulation.time_step_s = 15.0
    if args.days is not None:
        cfg.mission.simulation.duration_days = args.days
    if args.step is not None:
        cfg.mission.simulation.time_step_s = args.step

    n_az = 24 if args.quick else 48
    n_roll = 24 if args.quick else 48

    RESULTS_DIR.mkdir(exist_ok=True)
    results: dict[str, object] = {}

    if not environment.basilisk_available():
        print("ERROR: Basilisk is not importable in this interpreter.\n"
              "       Install it from https://avslab.github.io/basilisk/ "
              "and re-run.", file=sys.stderr)
        return 2

    # ---------------------------------------------------------------- orbit
    log(f"Propagating {cfg.sim.duration_days} day(s) at {cfg.sim.time_step_s} s "
        f"with Basilisk...")
    env = environment.propagate(cfg)
    orbit_summary = environment.summarise(env)
    results["orbit"] = orbit_summary
    log(f"  {env.n_samples} samples, {orbit_summary['orbits']:.1f} orbits, "
        f"period {orbit_summary['orbit_period_min']:.1f} min, "
        f"eclipse {orbit_summary['eclipse_fraction']*100:.1f} %")

    period_s = orbit_summary["orbit_period_min"] * 60.0

    # ------------------------------------------------------------- comms
    log("Analysing ground station access and the link budget...")
    passes = comms.analyse_passes(cfg, env)
    pass_stats = comms.pass_statistics(passes, env)
    results["comms"] = {
        "aggregate": pass_stats,
        "per_station": comms.per_station_statistics(passes, env),
        "link_margin_10deg_1695km_at_9k6": comms.link_margin_db(
            cfg, 1695.1e3, 9600.0),
        "link_margin_10deg_1695km_at_256k": comms.link_margin_db(
            cfg, 1695.1e3, 256000.0),
        "link_margin_worst_case_pointing_at_9k6": comms.link_margin_db(
            cfg, 1695.1e3, 9600.0, worst_case_pointing=True),
        "eirp_dbw": comms.eirp_dbw(cfg),
        "ground_gt_db_per_k": float(cfg.ground.network.gt_db_per_k),
    }
    log(f"  {pass_stats['passes_per_day']:.1f} passes/day, "
        f"{pass_stats['total_contact_min_per_day']:.0f} contact min/day, "
        f"{pass_stats['downlink_mb_per_day']:.1f} MB/day capacity")

    contact_s_per_day = pass_stats["total_contact_min_per_day"] * 60.0

    # -------------------------------------------------------------- ADCS
    log("Evaluating magnetorquer authority...")
    authority = adcs.torque_authority(cfg, env)
    slews = {f"{angle}deg": adcs.slew_time_profile(cfg, authority, angle)
             for angle in (10, 30, 60, 90, 180)}
    results["adcs"] = {
        "dipole_am2": adcs.dipole_vector(cfg).tolist(),
        "b_field_nt_mean": float(np.mean(authority.b_magnitude_nt)),
        "b_field_nt_min": float(np.min(authority.b_magnitude_nt)),
        "b_field_nt_max": float(np.max(authority.b_magnitude_nt)),
        "torque_nm_mean": authority.mean_max_torque_nm,
        "torque_nm_min": authority.min_max_torque_nm,
        "torque_nm_median": float(np.median(authority.max_torque_nm)),
        "slew_times": slews,
        "disturbances": adcs.disturbance_summary(cfg, env, authority),
        "detumble": adcs.detumble_time_s(cfg, env, authority),
        "momentum_management": adcs.momentum_dumping_per_orbit(
            cfg, env, authority, period_s),
    }
    log(f"  mean control torque {authority.mean_max_torque_nm*1e6:.2f} uN m, "
        f"90 deg slew ~{slews['90deg']['median_s']/60:.1f} min")

    # ------------------------------------------------ payload rate ceilings
    usb_fps = comms.usb2_max_fps(cfg)
    img_b = comms.image_bytes(cfg)
    results["payload_limits"] = {
        "image_bytes_compressed": img_b,
        "image_bytes_raw": img_b * 2,
        "usb2_max_experiments_per_s": usb_fps,
        "usb2_max_experiments_per_day": usb_fps * 86400.0,
    }

    # ------------------------------------------- per array geometry analysis
    log("Running per-geometry power, thermal, pointing and CONOPS analysis...")
    geometries = power.all_array_geometries(cfg)
    per_geometry: dict[str, object] = {}

    for array in geometries:
        log(f"  geometry {array.name} ({array.peak_total_w:.1f} W peak)")
        standby_dcm, standby_fraction = geometry.sun_pointing_attitude(
            env, array.normals, array.peak_w)

        t0 = time.time()
        pointing = geometry.solve_experiment_pointing(
            cfg, env, n_azimuth=n_az, n_roll=n_roll,
            array_normals=array.normals, array_weights=array.peak_w)
        log(f"    pointing search {time.time()-t0:.1f} s, "
            f"feasible {np.mean(pointing.feasible)*100:.1f} % of the time")

        entry: dict[str, object] = {
            "description": array.description,
            "peak_total_w": array.peak_total_w,
            "panels": array.panel_names,
            "standby_best_cosine_sum_w": float(standby_fraction[0]),
            "power_standby": power.orbit_average_generation(
                cfg, env, array, standby_dcm),
            "power_experiment": power.orbit_average_generation(
                cfg, env, array, pointing.dcm_BN),
            "experiment_feasible_fraction": float(np.mean(pointing.feasible)),
            "reject_reasons": {
                "no_sunlit_limb": float(np.mean(
                    pointing.reject_reason == geometry.REJECT_NO_SUNLIT_LIMB)),
                "sun_in_found_fov": float(np.mean(
                    pointing.reject_reason == geometry.REJECT_SUN_IN_FOUND)),
                "no_legal_roll": float(np.mean(
                    pointing.reject_reason == geometry.REJECT_NO_ROLL)),
            },
        }

        # Thermal uses the attitude actually flown, so run the scheduler first
        # at the baseline payload rate.
        baseline_rate = 0.2
        result = conops.simulate(cfg, env, array, pointing, standby_dcm,
                                 authority, baseline_rate, passes)
        entry["conops_baseline"] = conops.summarise(cfg, env, result)

        faces = thermal.analyse(cfg, env, result.dcm_BN)
        entry["thermal"] = {
            name: {
                "area_m2": face.area_m2,
                "sunlit_fraction": face.sunlit_fraction,
                "mean_cosine": face.mean_cosine,
                "mean_solar_flux_w_m2": face.mean_solar_flux_w_m2,
                "mean_albedo_flux_w_m2": face.mean_albedo_flux_w_m2,
                "mean_ir_flux_w_m2": face.mean_ir_flux_w_m2,
                "mean_total_flux_w_m2": face.mean_total_flux_w_m2,
                "peak_solar_flux_w_m2": face.peak_solar_flux_w_m2,
                "mean_solar_power_w": face.mean_solar_power_w,
                "longest_dark_min": face.longest_dark_s / 60.0,
            }
            for name, face in faces.items()
        }
        entry["eclipse"] = thermal.eclipse_statistics(env)

        # Payload rate sweep: where does the wall actually sit?
        sweep = []
        for rate in cfg.mission.analysis.payload_rate_hz_sweep:
            r = conops.simulate(cfg, env, array, pointing, standby_dcm,
                                authority, float(rate), passes)
            s = conops.summarise(cfg, env, r)
            s["requested_rate_hz"] = float(rate)
            sweep.append(s)
        entry["payload_rate_sweep"] = sweep
        per_geometry[array.name] = entry

    results["geometries"] = per_geometry

    # ------------------------------------------------------- data budget
    log("Closing the data budget...")
    downlink_capacity = pass_stats["downlink_bytes_per_day"]
    max_exp_downlink = comms.max_experiments_from_downlink(
        cfg, downlink_capacity, contact_s_per_day)
    results["data_budget"] = {
        "downlink_capacity_bytes_per_day": downlink_capacity,
        "max_experiments_per_day_downlink_limited": max_exp_downlink,
        "budget_at_17280_experiments": comms.data_budget(
            cfg, 17280.0, contact_s_per_day).__dict__,
        "budget_at_downlink_limit": comms.data_budget(
            cfg, max_exp_downlink, contact_s_per_day).__dict__,
    }

    # ------------------------------------------------- binding constraints
    # The direct answer to "how many images can I take". Each entry is the
    # ceiling that one subsystem alone would impose; the smallest one binds.
    log("Identifying the binding constraint on payload throughput...")
    images_per_experiment = int(cfg.payload.n_cameras)
    storage_experiments = (float(cfg.payload.storage_gb) * 1e9
                           / (images_per_experiment * img_b))
    constraint_rows = {}
    for name, entry in per_geometry.items():
        baseline = entry["conops_baseline"]
        exp_fraction = float(baseline["frac_experiment"])
        exp_seconds = exp_fraction * 86400.0
        constraint_rows[name] = {
            "experiment_time_fraction": exp_fraction,
            "experiment_seconds_per_day": exp_seconds,
            # Ceilings, expressed as images per day.
            "ceiling_usb2": usb_fps * exp_seconds * images_per_experiment,
            "ceiling_storage": storage_experiments * images_per_experiment,
            "ceiling_downlink": max_exp_downlink * images_per_experiment,
            "achieved_at_0p2hz": float(baseline["images_per_day"]),
            "energy_margin_w": float(baseline["energy_margin_w"]),
            "battery_limited": bool(baseline["battery_limited"]),
        }
        # Time in experiment mode is a multiplier on the cadence, not a ceiling
        # in its own right -- it is already folded into the USB figure, which
        # is the fastest the cameras could run for exactly that long. The
        # genuine rate-independent ceilings are storage and downlink.
        ceilings = {
            "USB 2.0 bus over the available experiment time":
                constraint_rows[name]["ceiling_usb2"],
            "on-board storage": constraint_rows[name]["ceiling_storage"],
            "downlink capacity": constraint_rows[name]["ceiling_downlink"],
        }
        binding = min(ceilings, key=ceilings.get)
        constraint_rows[name]["binding_constraint"] = binding
        constraint_rows[name]["binding_value_images_per_day"] = ceilings[binding]
        # Cadence you would have to command to reach that ceiling.
        constraint_rows[name]["required_rate_hz"] = (
            ceilings[binding] / images_per_experiment / exp_seconds
            if exp_seconds > 0 else float("inf"))
    results["binding_constraints"] = constraint_rows

    # --------------------------------------------------------- power modes
    results["power_modes"] = {
        "mode_loads_w": power.mode_power_table(cfg),
        "subsystem_breakdown": {mode: power.subsystem_breakdown(cfg, mode)
                                for mode in cfg.power.modes},
        "heater_sensitivity": {
            f"duty_{int(d*100)}pct": power.mode_power_table(cfg, heater_duty=d)
            for d in (0.0, 0.15, 0.30, 0.50)
        },
    }

    # ------------------------------------------------------- RAAN sweep
    if not args.no_sweep and not args.quick:
        log("Sweeping RAAN to cover the beta-angle range...")
        sweep_rows = []
        best_array = max(geometries, key=lambda a: a.peak_total_w)
        for raan in cfg.mission.analysis.raan_sweep_deg:
            sub = cfg.copy_with(**{"mission.orbit.raan_deg": float(raan)})
            sub.mission.simulation.duration_days = min(
                1.0, float(cfg.sim.duration_days))
            sub_env = environment.propagate(sub)
            sub_standby, _ = geometry.sun_pointing_attitude(
                sub_env, best_array.normals, best_array.peak_w)
            gen = power.orbit_average_generation(sub, sub_env, best_array, sub_standby)
            ecl = thermal.eclipse_statistics(sub_env)
            sweep_rows.append({
                "raan_deg": float(raan),
                "beta_deg": float(np.degrees(np.mean(np.abs(sub_env.beta_angle())))),
                "eclipse_fraction": ecl["eclipse_fraction"],
                "max_eclipse_min": ecl["max_eclipse_min"],
                "orbit_average_w": gen["orbit_average_w"],
            })
            log(f"  RAAN {raan:5.1f} deg -> beta {sweep_rows[-1]['beta_deg']:5.1f} deg, "
                f"eclipse {ecl['eclipse_fraction']*100:4.1f} %, "
                f"{gen['orbit_average_w']:.1f} W")
        results["raan_sweep"] = sweep_rows

    # ------------------------------------------------------------- write
    out_path = RESULTS_DIR / "summary.json"
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(to_jsonable(results), handle, indent=2)
    log(f"Wrote {out_path}")

    try:
        from hs2sim import report
        report.write_report(cfg, results, RESULTS_DIR / "report.md")
        log(f"Wrote {RESULTS_DIR / 'report.md'}")
    except Exception as exc:  # pragma: no cover
        log(f"Report generation skipped: {exc}")

    try:
        from hs2sim import plots
        plots.make_all(cfg, env, results, RESULTS_DIR)
        log("Wrote plots")
    except Exception as exc:  # pragma: no cover
        log(f"Plotting skipped: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
