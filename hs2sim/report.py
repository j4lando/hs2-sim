"""Turn the results dictionary into a readable Markdown report."""

from __future__ import annotations

import pathlib
from typing import Any

from .config import MissionConfig


def _fmt(value: Any, spec: str = ".2f") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return str(value)


def write_report(cfg: MissionConfig, results: dict, path: pathlib.Path) -> None:
    lines: list[str] = []
    add = lines.append

    orbit = results["orbit"]
    add("# HS-2 operations simulation results\n")
    add(f"Propagated with Basilisk for {_fmt(orbit['duration_days'], '.1f')} days "
        f"at a {_fmt(orbit['time_step_s'], '.0f')} s step "
        f"({_fmt(orbit['orbits'], '.0f')} orbits).\n")

    add("## Orbit and environment\n")
    add("| Quantity | Value |")
    add("| --- | --- |")
    add(f"| Mean altitude | {_fmt(orbit['mean_altitude_km'], '.1f')} km |")
    add(f"| Orbit period | {_fmt(orbit['orbit_period_min'], '.2f')} min |")
    add(f"| Eclipse fraction | {_fmt(orbit['eclipse_fraction'] * 100, '.1f')} % |")
    add(f"| Beta angle (mean/min/max) | "
        f"{_fmt(orbit['beta_angle_deg_mean'], '.1f')} / "
        f"{_fmt(orbit['beta_angle_deg_min'], '.1f')} / "
        f"{_fmt(orbit['beta_angle_deg_max'], '.1f')} deg |")
    add(f"| Earth angular radius | "
        f"{_fmt(orbit['earth_angular_radius_deg'], '.1f')} deg |")
    add(f"| Mean field strength | {_fmt(orbit['b_field_nt_mean'], '.0f')} nT |\n")

    # -- comms --------------------------------------------------------------
    comms_res = results["comms"]
    agg = comms_res["aggregate"]
    add("## Communications\n")
    add(f"- **{_fmt(agg['passes_per_day'], '.1f')} passes per day** across "
        f"{len(comms_res['per_station'])} Leaf Space locations.")
    add(f"- {_fmt(agg['total_contact_min_per_day'], '.0f')} minutes of contact "
        f"per day; mean pass {_fmt(agg['mean_pass_duration_min'], '.1f')} min, "
        f"longest {_fmt(agg['max_pass_duration_min'], '.1f')} min.")
    add(f"- Deliverable **{_fmt(agg['downlink_mb_per_day'], '.0f')} MB/day** of "
        f"information (after rate-1/2 FEC).")
    add(f"- Spacecraft EIRP {_fmt(comms_res['eirp_dbw'], '.1f')} dBW against a "
        f"{_fmt(comms_res['ground_gt_db_per_k'], '.1f')} dB/K station.")
    add(f"- Link margin at 10 deg elevation: "
        f"{_fmt(comms_res['link_margin_10deg_1695km_at_9k6'], '.1f')} dB at 9.6 kbps, "
        f"{_fmt(comms_res['link_margin_10deg_1695km_at_256k'], '.1f')} dB at 256 kbps.")
    add(f"- With the budget's worst-case -10 dB antenna pointing loss: "
        f"{_fmt(comms_res['link_margin_worst_case_pointing_at_9k6'], '.1f')} dB "
        f"at 9.6 kbps.\n")

    add("| Station | Passes/day | Mean duration (min) | Contact (min/day) |")
    add("| --- | --- | --- | --- |")
    for row in comms_res["per_station"]:
        add(f"| {row['station']} | {_fmt(row['passes_per_day'], '.2f')} | "
            f"{_fmt(row['mean_duration_min'], '.1f')} | "
            f"{_fmt(row['contact_min_per_day'], '.1f')} |")
    add("")

    # -- power modes --------------------------------------------------------
    add("## Power draw by mode\n")
    add("Rebuilt from peak power x quantity x duty cycle.\n")
    add("| Mode | Load (W) |")
    add("| --- | --- |")
    for mode, value in results["power_modes"]["mode_loads_w"].items():
        add(f"| {mode} | {_fmt(value, '.2f')} |")
    add("")
    add("Heater duty cycle sensitivity (the heater number is not trusted):\n")
    add("| Heater duty | Experiment mode load (W) |")
    add("| --- | --- |")
    for name, table in results["power_modes"]["heater_sensitivity"].items():
        add(f"| {name.replace('duty_', '').replace('pct', ' %')} | "
            f"{_fmt(table['experiment'], '.2f')} |")
    add("")

    # -- geometries ---------------------------------------------------------
    add("## Solar array geometry trade\n")
    add("| Geometry | Peak (W) | Standby orbit-avg (W) | Capacity factor | "
        "Experiment-mode avg (W) |")
    add("| --- | --- | --- | --- | --- |")
    for name, entry in results["geometries"].items():
        standby = entry["power_standby"]
        experiment = entry["power_experiment"]
        add(f"| {name} | {_fmt(entry['peak_total_w'], '.1f')} | "
            f"{_fmt(standby['orbit_average_w'], '.2f')} | "
            f"{_fmt(standby['capacity_factor'], '.3f')} | "
            f"{_fmt(experiment['orbit_average_w'], '.2f')} |")
    add("")

    add("### Per-panel incidence (sun-pointing standby attitude)\n")
    add("| Geometry | Panel | Peak (W) | Mean incidence | Illuminated | "
        "Mean output (W) |")
    add("| --- | --- | --- | --- | --- | --- |")
    for name, entry in results["geometries"].items():
        for panel, data in entry["power_standby"].get("per_panel", {}).items():
            add(f"| {name} | {panel} | {_fmt(data['peak_w'], '.1f')} | "
                f"{_fmt(data['mean_incidence_deg'], '.1f')} deg | "
                f"{_fmt(data['fraction_of_time_illuminated'] * 100, '.0f')} % | "
                f"{_fmt(data['mean_power_w'], '.2f')} |")
    add("")

    add("### Experiment-mode pointing feasibility\n")
    add("| Geometry | Feasible | No sunlit limb | Sun in FOUND | No legal roll |")
    add("| --- | --- | --- | --- | --- |")
    for name, entry in results["geometries"].items():
        rej = entry["reject_reasons"]
        add(f"| {name} | {_fmt(entry['experiment_feasible_fraction'] * 100, '.1f')} % | "
            f"{_fmt(rej['no_sunlit_limb'] * 100, '.1f')} % | "
            f"{_fmt(rej['sun_in_found_fov'] * 100, '.1f')} % | "
            f"{_fmt(rej['no_legal_roll'] * 100, '.1f')} % |")
    add("")

    # -- thermal ------------------------------------------------------------
    first = next(iter(results["geometries"].values()))
    add("## Surface illumination (thermal inputs)\n")
    add(f"Flown attitude from the CONOPS scheduler, geometry "
        f"`{next(iter(results['geometries']))}`.\n")
    add("| Face | Area (m^2) | Sunlit | Mean solar (W/m^2) | Albedo | Earth IR | "
        "Total | Peak solar | Longest dark (min) |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for face, data in first["thermal"].items():
        add(f"| {face} | {_fmt(data['area_m2'], '.3f')} | "
            f"{_fmt(data['sunlit_fraction'] * 100, '.0f')} % | "
            f"{_fmt(data['mean_solar_flux_w_m2'], '.0f')} | "
            f"{_fmt(data['mean_albedo_flux_w_m2'], '.0f')} | "
            f"{_fmt(data['mean_ir_flux_w_m2'], '.0f')} | "
            f"{_fmt(data['mean_total_flux_w_m2'], '.0f')} | "
            f"{_fmt(data['peak_solar_flux_w_m2'], '.0f')} | "
            f"{_fmt(data['longest_dark_min'], '.1f')} |")
    eclipse = first["eclipse"]
    add("")
    add(f"Eclipse: {_fmt(eclipse['eclipse_fraction'] * 100, '.1f')} % of the "
        f"orbit, longest {_fmt(eclipse['max_eclipse_min'], '.1f')} min.\n")

    # -- single node thermal -------------------------------------------------
    if "single_node_thermal" in first:
        add("## Single-node temperature\n")
        add("Whole spacecraft treated as one isothermal node "
            "(instantaneous internal conduction):\n")
        add("```")
        add("C dT/dt = Q_solar + Q_albedo + Q_earthIR + Q_internal "
            "- P_electrical - eps*sigma*A*T^4")
        add("```")
        add("")
        if "dissipation" in results:
            d = results["dissipation"]
            add("**Where the electrical power goes.** Everything drawn becomes "
                "heat except what physically leaves the vehicle:\n")
            add("| Subsystem | Leaves as | Non-heat power | Heat fraction |")
            add("| --- | --- | --- | --- |")
            add(f"| COMM (radio TX) | RF wave | "
                f"{_fmt(d['rf_radiated_w'], '.2f')} W | "
                f"**{_fmt(d['radio_tx_heat_fraction'] * 100, '.1f')} %** |")
            add(f"| COMM (radio RX) | nothing | 0 W | 100.0 % |")
            add(f"| ADCS (magnetorquers) | mechanical work | "
                f"{_fmt(d['mtq_mechanical_w'] * 1e9, '.3f')} nW | "
                f"**{_fmt(d['mtq_heat_fraction'] * 100, '.4f')} %** |")
            add(f"| Everything else | nothing | 0 W | 100.0 % |")
            add("")
            add("The transmitter is the only meaningful exception. Of its "
                f"{_fmt(d['radio_tx_input_w'], '.2f')} W input, the link "
                "budget's own numbers (2 W at the PA, -3 dB return loss, "
                f"-1 dB circuit loss) leave only {_fmt(d['rf_radiated_w'], '.2f')} W "
                "actually radiating away -- so the radio is, thermally, almost "
                "a pure heater.\n")
            add("Magnetorquers are resistive coils. The mechanical power they "
                "deliver is torque x body rate, which at this vehicle's "
                f"{_fmt(d['mean_torque_unm'], '.1f')} uN m and "
                f"{_fmt(d['mean_rate_dps'], '.4f')} deg/s is about "
                f"{_fmt(d['mtq_mechanical_w'] * 1e9, '.3f')} nW -- roughly one "
                "part in a billion of their electrical draw. Unlike reaction "
                "wheels they store no useful kinetic energy, and the coil's "
                "field energy returns to the bus on de-energisation. Treating "
                "ADCS as 100 % dissipative is correct to nine decimal places.\n")

        add("| Geometry | Mean | Min | Max | Swing | Time constant | "
            "Battery margin (cold/hot) |")
        add("| --- | --- | --- | --- | --- | --- | --- |")
        for name, entry in results["geometries"].items():
            t = entry["single_node_thermal"]
            add(f"| {name} | {_fmt(t['mean_c'], '.1f')} C | "
                f"{_fmt(t['min_c'], '.1f')} C | {_fmt(t['max_c'], '.1f')} C | "
                f"{_fmt(t['swing_c'], '.1f')} C | "
                f"{_fmt(t['time_constant_min'], '.0f')} min | "
                f"{_fmt(t['battery_margin_cold_c'], '+.1f')} / "
                f"{_fmt(t['battery_margin_hot_c'], '+.1f')} C |")
        add("")
        node = first["single_node_thermal"]
        add(f"Radiating area {_fmt(node['radiating_area_m2'], '.3f')} m^2 at an "
            f"effective emissivity of {_fmt(node['effective_emissivity'], '.2f')}; "
            f"thermal capacitance {_fmt(node['thermal_capacitance_j_k'], '.0f')} J/K. "
            f"Mean absorbed environmental load "
            f"{_fmt(node['mean_absorbed_env_w'], '.1f')} W against "
            f"{_fmt(node['mean_internal_heat_w'], '.1f')} W of internal "
            f"dissipation.\n")
        add("The thermal time constant is comparable to the orbit period, which "
            "is why the swing is far smaller than the instantaneous radiative "
            "equilibrium would suggest: the vehicle's own mass averages the "
            "eclipse cycle. A single-node model cannot see gradients, so the "
            "deployed wing will in reality run hotter in sunlight and colder in "
            "eclipse than these numbers, and the battery -- usually the most "
            "temperature-sensitive item -- sits inside the bus where swings are "
            "smaller. Treat this as the bulk average, not a component "
            "prediction.\n")

    # -- ADCS ---------------------------------------------------------------
    adcs_res = results["adcs"]
    add("## ADCS: magnetorquer limits\n")
    add(f"- Dipole per axis: {adcs_res['dipole_am2']} A m^2.")
    add(f"- Field {_fmt(adcs_res['b_field_nt_min'], '.0f')}-"
        f"{_fmt(adcs_res['b_field_nt_max'], '.0f')} nT "
        f"(mean {_fmt(adcs_res['b_field_nt_mean'], '.0f')} nT).")
    add(f"- Control torque: mean "
        f"{_fmt(adcs_res['torque_nm_mean'] * 1e6, '.2f')} uN m, "
        f"minimum {_fmt(adcs_res['torque_nm_min'] * 1e6, '.2f')} uN m.\n")

    add("| Slew | Best (min) | Median (min) | 10th percentile field (min) |")
    add("| --- | --- | --- | --- |")
    for name, row in adcs_res["slew_times"].items():
        add(f"| {name} | {_fmt(row['best_s'] / 60, '.1f')} | "
            f"{_fmt(row['median_s'] / 60, '.1f')} | "
            f"{_fmt(row['p10_s'] / 60, '.1f')} |")
    add("")

    dist = adcs_res["disturbances"]
    add(f"Disturbance torques: gravity gradient "
        f"{_fmt(dist['gravity_gradient_nm_mean'] * 1e6, '.3f')} uN m, "
        f"residual dipole {_fmt(dist['residual_dipole_nm_mean'] * 1e6, '.3f')} uN m, "
        f"aero {_fmt(dist['aero_nm_mean'] * 1e6, '.3f')} uN m. "
        f"Authority margin {_fmt(dist['authority_margin_mean'], '.1f')}x on average, "
        f"{_fmt(dist['authority_margin_worst'], '.2f')}x worst case.\n")
    momentum = adcs_res["momentum_management"]
    add(f"Momentum management needs the torquers energised roughly "
        f"{_fmt(momentum['duty_cycle'] * 100, '.1f')} % of each orbit.")
    detumble = adcs_res["detumble"]
    add(f"Detumble from {_fmt(detumble['initial_rate_dps'], '.0f')} deg/s: "
        f"about {_fmt(detumble['detumble_hours'], '.1f')} hours.\n")

    # -- payload ------------------------------------------------------------
    limits = results["payload_limits"]
    data = results["data_budget"]
    add("## Payload throughput\n")
    add(f"- Compressed image: {limits['image_bytes_compressed']:,} B "
        f"(raw {limits['image_bytes_raw']:,} B).")
    add(f"- USB 2.0 ceiling: {_fmt(limits['usb2_max_experiments_per_s'], '.1f')} "
        f"experiments/s, i.e. "
        f"{_fmt(limits['usb2_max_experiments_per_day'], ',.0f')} per day.")
    add(f"- Downlink-limited ceiling: "
        f"{_fmt(data['max_experiments_per_day_downlink_limited'], ',.0f')} "
        f"experiments/day.\n")

    if "binding_constraints" in results:
        add("### What actually limits the image count\n")
        add("Time in experiment mode is a multiplier on cadence rather than a "
            "ceiling of its own, and it is already folded into the USB column "
            "-- that column is the most images the cameras could produce if "
            "run flat out for exactly the time a legal attitude exists. "
            "Storage and downlink are genuine rate-independent ceilings. The "
            "smallest of the three binds.\n")
        add("| Geometry | Time in experiment mode | USB 2.0 | Storage | "
            "Downlink | Binding constraint | Max images/day | Cadence needed |")
        add("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for name, row in results["binding_constraints"].items():
            add(f"| {name} | "
                f"{_fmt(row['experiment_time_fraction'] * 100, '.1f')} % "
                f"({_fmt(row['experiment_seconds_per_day'] / 3600, '.1f')} h/day) | "
                f"{_fmt(row['ceiling_usb2'], ',.0f')} | "
                f"{_fmt(row['ceiling_storage'], ',.0f')} | "
                f"{_fmt(row['ceiling_downlink'], ',.0f')} | "
                f"{row['binding_constraint']} | "
                f"**{_fmt(row['binding_value_images_per_day'], ',.0f')}** | "
                f"{_fmt(row['required_rate_hz'], '.2f')} Hz |")
        add("")
        cadences = ", ".join(
            f"{name} needs {_fmt(row['required_rate_hz'], '.1f')} Hz"
            for name, row in results["binding_constraints"].items())
        add("Two things follow. First, downlink capacity is **not** the "
            "constraint on science volume, and it is not close: only two debug "
            "images come down per day, so what is actually transmitted is "
            "numerical data plus housekeeping, orders of magnitude below what "
            "the Leaf Space contacts can carry. Sizing the radio against image "
            "volume would be sizing against the wrong thing. Second, energy and "
            "attitude feasibility decide how hard the cameras have to be driven "
            "to reach whichever ceiling binds: " + cadences + ". A geometry "
            "with less time in experiment mode has to run its cameras faster "
            "to collect the same science.\n")

    add("### Achieved cadence from the CONOPS scheduler\n")
    add("| Geometry | Requested (Hz) | Experiments/day | Images/day | "
        "Min SOC | Downlink (MB/day) | Backlog growth (MB/day) |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for name, entry in results["geometries"].items():
        for row in entry["payload_rate_sweep"]:
            add(f"| {name} | {_fmt(row['requested_rate_hz'], '.2f')} | "
                f"{_fmt(row['experiments_per_day'], ',.0f')} | "
                f"{_fmt(row['images_per_day'], ',.0f')} | "
                f"{_fmt(row['min_soc'] * 100, '.0f')} % | "
                f"{_fmt(row['downlinked_mb_per_day'], '.1f')} | "
                f"{_fmt(row['backlog_growth_mb_per_day'], '+.2f')} |")
    add("")

    # -- CONOPS -------------------------------------------------------------
    add("## CONOPS mode split (baseline 0.2 Hz)\n")
    add("| Geometry | Standby | Experiment | Downlink | Slew | Slews/day | "
        "Energy margin (W) | Peak tracking rate |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, entry in results["geometries"].items():
        c = entry["conops_baseline"]
        add(f"| {name} | {_fmt(c['frac_standby'] * 100, '.1f')} % | "
            f"{_fmt(c['frac_experiment'] * 100, '.1f')} % | "
            f"{_fmt(c['frac_downlink'] * 100, '.2f')} % | "
            f"{_fmt(c['frac_slew'] * 100, '.1f')} % | "
            f"{_fmt(c['slews_per_day'], '.0f')} | "
            f"{_fmt(c['energy_margin_w'], '.2f')} | "
            f"{_fmt(c['max_tracking_rate_dps'], '.3f')} deg/s |")
    add("")
    add("Peak tracking rate is how fast the target attitude moves while "
        "following a limb or a ground station. Compare it against the rate the "
        "magnetorquers can sustain: at the mean control torque above, spinning "
        "up to 0.1 deg/s about the stiff axis takes on the order of a minute, "
        "so tracking is not the binding constraint -- the discrete slews "
        "between modes are.\n")

    path.write_text("\n".join(lines), encoding="utf-8")
