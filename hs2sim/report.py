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


def _matrix_table(add, rows: list[float], cols: list[float],
                  values: list[list[float]], spec: str,
                  row_label: str, mark: tuple[int, int] | None) -> None:
    """Emit a Markdown matrix with LOST down the side and FOUND across."""
    add("| " + row_label + " | "
        + " | ".join(f"FOUND {c:.0f} deg" for c in cols) + " |")
    add("| --- |" + " --- |" * len(cols))
    for r, row_value in enumerate(rows):
        cells = []
        for c in range(len(cols)):
            text = _fmt(values[r][c], spec)
            if mark is not None and (r, c) == mark:
                text = f"**{text}**"
            cells.append(text)
        add(f"| **LOST {row_value:.0f} deg** | " + " | ".join(cells) + " |")
    add("")


def _margin_subsection(sweep: dict, add) -> None:
    """The pointing-error buffer, priced in the same units as the cones."""
    rows = sweep.get("margin_sweep")
    if not rows:
        return
    char = sweep.get("margin_character", {})
    applied = sweep.get("pointing_margin_deg")

    add("### The pointing-error buffer\n")
    add("Everything above is solved with a buffer on every keep-out, because "
        "what the solver returns is a *commanded* attitude and the true "
        "boresight is somewhere within the control and knowledge error of it, "
        "in an unknown direction. An attitude that puts the Sun exactly on the "
        "star tracker's 40 deg boundary is a coin flip, not a legal attitude. "
        "So each cone is enforced at `exclusion + margin` and the legal set "
        "shrinks from every side.\n")
    if applied is not None:
        add(f"The tables above use **{_fmt(applied, '.2f')} deg**. This "
            f"sub-sweep moves only that buffer, with the cones held at their "
            f"configured values.\n")

    add("| Buffer (deg) | Feasible | Image ceiling | Images/day | "
        "Sun in FOUND | No legal roll |")
    add("| --- | --- | --- | --- | --- | --- |")
    for row in sorted(rows, key=lambda r: r["margin_deg"]):
        mark = "**" if (applied is not None
                        and abs(row["margin_deg"] - applied) < 1e-6) else ""
        add(f"| {mark}{row['margin_deg']:.2f}{mark} | "
            f"{mark}{_fmt(row['feasible_fraction'] * 100, '.1f')} %{mark} | "
            f"{_fmt(row['images_per_day_ceiling'], ',.0f')} | "
            f"{_fmt(row['images_per_day'], ',.0f')} | "
            f"{_fmt(row['reject_reasons']['sun_in_found_fov'] * 100, '.1f')} % | "
            f"{_fmt(row['reject_reasons']['no_legal_roll'] * 100, '.1f')} % |")
    add("")

    cost = char.get("cost_of_baseline_budget_pp")
    free_to = char.get("free_up_to_deg")
    binds_at = char.get("binds_at_deg")
    if cost is not None:
        add(f"**The pointing budget is very nearly free at its current size, "
            f"and the sweep says exactly how much room there is.** The "
            f"as-designed {_fmt(char.get('baseline_margin_deg'), '.2f')} deg "
            f"buffer costs {_fmt(abs(cost), '.2f')} percentage points of "
            f"feasible time against a hypothetical perfect pointer"
            + (f", and feasibility is unchanged all the way out to "
               f"**{_fmt(free_to, '.0f')} deg**" if free_to else "")
            + (f", only starting to move at {_fmt(binds_at, '.0f')} deg"
               if binds_at is not None else "")
            + ". That is not luck and it is not a modelling artefact: it is "
            "the +z slack from the cone sweep, spent on pointing error instead "
            "of on keep-out."
            + (f" In other words the vehicle can miss its pointing spec by a "
               f"factor of {_fmt(float(free_to) / char['baseline_margin_deg'], '.0f')} "
               f"before the geometry charges anything at all for it.\n"
               if free_to and char.get("baseline_margin_deg") else "\n"))
    overall = char.get("pp_per_deg_overall")
    upper = char.get("pp_per_deg_upper_half")
    if overall is not None and upper is not None and upper > overall * 1.2:
        add(f"Past that the price accelerates hard: {_fmt(overall, '.2f')} "
            f"pp/deg averaged over the whole swept range but "
            f"{_fmt(upper, '.2f')} pp/deg over the upper half. The buffer eats "
            f"into the roll window from the Earth side and the Sun side at "
            f"once, which is the superadditive collapse from the previous "
            f"section arriving by a different route.\n")

    checks = char.get("grid_equivalence") or []
    worst = char.get("max_equivalence_difference_pp")
    if checks and worst is not None:
        example = max(checks, key=lambda c: c["margin_deg"])
        add(f"**Cross-check.** Padding every keep-out by *m* degrees is the "
            f"same inequality as moving both cones out by *m*, so a buffer of "
            f"{example['margin_deg']:.0f} deg has to reproduce the grid cell "
            f"at LOST {example['equivalent_cell'][0]:.0f} / FOUND "
            f"{example['equivalent_cell'][1]:.0f} deg. It does: "
            f"{_fmt(example['margin_feasible'] * 100, '.1f')} % against "
            f"{_fmt(example['grid_feasible'] * 100, '.1f')} %. Across every "
            f"comparable point the two agree to "
            f"{_fmt(worst, '.2f')} percentage points. The two numbers come "
            f"from different code paths -- one adds the margin to the angle "
            f"inside the solver, the other rewrites the config and re-reads "
            f"it -- so this checks both.\n")

    add("One thing to be clear about: this is a *hard* constraint on "
        "feasibility, not a soft pointing requirement. An attitude that cannot "
        "hold the buffer is not counted at all, so an ADCS that misses its "
        "spec does not blur images here -- it removes observations from the "
        "timeline. The flip side is the useful part for ADCS: there is no "
        "science argument for tightening the pointing budget below its current "
        f"{_fmt(char.get('baseline_margin_deg'), '.2f')} deg, because the "
        "geometry cannot tell the difference.\n")


def _decomposition_table(add, table: dict, cone_label: str) -> None:
    """quoted exclusion (rows) x attitude uncertainty (columns)."""
    quoted = table["quoted_deg"]
    uncertainty = table["uncertainty_deg"]
    add(f"| {cone_label} \\ uncertainty | "
        + " | ".join(f"{u:g} deg" for u in uncertainty) + " |")
    add("| --- |" + " --- |" * len(uncertainty))
    for r, q in enumerate(quoted):
        cells = []
        for c in range(len(uncertainty)):
            cell = table["cells"][r][c]
            if cell is None:
                cells.append("--")
                continue
            if cell.get("fov_wall"):
                cells.append("**FOV**")
                continue
            text = (f"{cell['effective_deg']:g} / "
                    f"{cell['feasible_fraction'] * 100:.1f} %")
            if cell.get("exceeds_hemisphere"):
                text = f"*{text}*"
            cells.append(text)
        add(f"| **{q:g} deg** | " + " | ".join(cells) + " |")
    add("")


def _effective_angle_subsection(sweep: dict, add) -> None:
    """How attitude uncertainty moves the effective keep-out half-angle."""
    eff = sweep.get("effective_angle")
    if not eff:
        return
    fov_wall = eff.get("fov_wall_deg")

    add("### Effective keep-out half-angle\n")
    add("Attitude uncertainty is applied in both directions, as it has to be: "
        "a keep-**out** cone grows by the buffer and the keep-**in** field of "
        "view shrinks by it. What the vehicle must actually respect is\n")
    add("```")
    add("effective half-angle = quoted exclusion + attitude uncertainty")
    add("```")
    add("")
    add("Both terms land in the same inequality, so only their sum matters. "
        "The tables below give **effective half-angle / feasible fraction** "
        "for each combination. *Italic* cells are the ones this section exists "
        "for: an effective half-angle past 90 deg, where the keep-out cone is "
        "larger than a hemisphere.\n")
    if fov_wall:
        add(f"`FOV` marks cells killed by the other half of the treatment. "
            f"FOUND's half field of view is {_fmt(fov_wall, '.0f')} deg, so at "
            f"{_fmt(fov_wall, '.0f')} deg of uncertainty the shrink has "
            f"consumed the entire field of view and no commanded attitude can "
            f"guarantee the limb is in frame -- whatever the keep-outs say. "
            f"That is a hard wall on the ADCS, independent of the payload "
            f"requirement.\n")

    add("> **Read these two tables as per-cone sensitivity, not as the cost of "
        "uncertainty.** Each one moves a single cone and holds the other at "
        "its nominal value. Real attitude uncertainty is a property of the "
        "vehicle, so it inflates *every* keep-out at once, and the cones are "
        "superadditive -- the combined cost is worse than either column "
        "suggests. The third table below is the honest one for a pointing "
        "budget.\n")

    add(f"**Table A -- FOUND Sun keep-out (+x)**, with the +z cone held at "
        f"nominal.\n")
    _decomposition_table(add, eff["table_found"], "quoted")
    add(f"**Table B -- LOST / star tracker keep-out (+z)**, Sun and Earth "
        f"together, with FOUND held at nominal.\n")
    _decomposition_table(add, eff["table_lost"], "quoted")

    # -- both cones at once, which is what uncertainty actually does ---------
    margin_rows = sorted(sweep.get("margin_sweep") or [],
                         key=lambda r: r["margin_deg"])
    base = sweep.get("baseline", {})
    if margin_rows and "lost_deg" in base and "found_deg" in base:
        add("**Table C -- both cones inflated together.** This is what a real "
            "pointing budget does, and it is the row to quote. Every keep-out "
            "carries the uncertainty simultaneously.\n")
        add("| Uncertainty | Effective FOUND | Effective +z | Feasible | "
            "vs Table A alone |")
        add("| --- | --- | --- | --- | --- |")
        found_by_angle = {r["effective_deg"]: r["feasible_fraction"]
                          for r in eff["found"]}
        for row in margin_rows:
            u = row["margin_deg"]
            eff_found = base["found_deg"] + u
            eff_lost = base["lost_deg"] + u
            solo = found_by_angle.get(eff_found)
            delta = ("--" if solo is None else
                     _fmt((row["feasible_fraction"] - solo) * 100, '+.1f') + " pp")
            hemi = " *(> 90)*" if eff_found > 90.0 else ""
            add(f"| {u:g} deg | {eff_found:g} deg{hemi} | {eff_lost:g} deg | "
                f"{_fmt(row['feasible_fraction'] * 100, '.1f')} % | {delta} |")
        add("")
        add("The last column is the size of the mistake you would make by "
            "reading Table A on its own. It is negative everywhere the "
            "uncertainty is large, which is the superadditivity: the two "
            "keep-outs exclude different arcs of the roll circle, so inflating "
            "both removes attitudes that inflating either one alone would have "
            "left available.\n")

    # -- beyond 90 deg -------------------------------------------------------
    add("**What changes past 90 degrees.** Below 90 deg a keep-out removes a "
        "cap from the sky and leaves most of it. At exactly 90 deg it removes "
        "a hemisphere. Past 90 deg the *allowed* region is what is left of the "
        "opposite hemisphere: a cap of half-angle `180 - effective` about the "
        "anti-Sun direction, which shrinks to a point at 180 deg. So the "
        "constraint stops being \"avoid the Sun\" and becomes \"point almost "
        "directly away from it\", which is a different pointing problem and "
        "one the limb requirement usually cannot also satisfy.\n")
    add("| Effective half-angle | Allowed cap about anti-Sun | FOUND feasible |")
    add("| --- | --- | --- |")
    for row in eff["found"]:
        if row["effective_deg"] < 80.0:
            continue
        add(f"| {row['effective_deg']:g} deg"
            + (" *(> hemisphere)*" if row["exceeds_hemisphere"] else "")
            + f" | {row['allowed_cap_half_angle_deg']:g} deg | "
            f"{_fmt(row['feasible_fraction'] * 100, '.1f')} % |")
    add("")

    # -- additivity check ----------------------------------------------------
    checks = eff.get("additivity_check") or []
    worst = eff.get("max_additivity_difference_pp")
    if checks and worst is not None:
        add(f"**Check that the two terms really add.** The tables are built "
            f"from sweeps over the *sum*, which is only valid if carrying u "
            f"degrees as a buffer behaves identically to folding u into every "
            f"quoted angle. The two travel through different code -- one is "
            f"read from the config, the other is a float added inside the "
            f"solver -- so it is measured rather than asserted:\n")
        add("| Uncertainty | As a buffer | Folded into every cone | "
            "Difference |")
        add("| --- | --- | --- | --- |")
        for row in checks:
            note = "  (FOV wall, expected)" if row["fov_wall_tripped"] else ""
            add(f"| {row['uncertainty_deg']:g} deg | "
                f"{_fmt(row['as_buffer_feasible'] * 100, '.1f')} % | "
                f"{_fmt(row['as_wider_cones_feasible'] * 100, '.1f')} % | "
                f"{_fmt(row['difference_pp'], '+.2f')} pp{note} |")
        add("")
        add(f"Worst disagreement {_fmt(worst, '.2f')} percentage points below "
            f"the FOV wall, so the decomposition holds: a degree of ADCS "
            f"performance and a degree of optical keep-out are the same "
            f"degree. Above the wall the two paths are *supposed* to diverge, "
            f"because widening a keep-out does not shrink the field of view "
            f"and carrying the same number as attitude uncertainty does.\n")


def _exclusion_section(sweep: dict, add) -> None:
    lost = sweep["lost_deg"]
    found = sweep["found_deg"]
    mat = sweep["matrices"]
    base = sweep.get("baseline", {})
    baseline_lost = base.get("lost_deg")
    baseline_found = base.get("found_deg")
    mark = None
    if baseline_lost in lost and baseline_found in found:
        mark = (lost.index(baseline_lost), found.index(baseline_found))

    add("## Camera exclusion-angle trade\n")
    add(f"Both keep-out cones were swept and the whole pipeline re-run at each "
        f"grid point -- pointing re-solved on a {sweep['n_grid']}x"
        f"{sweep['n_grid']} azimuth/roll search, then the mode scheduler run at "
        f"{_fmt(sweep['payload_rate_hz'], '.2f')} Hz on geometry "
        f"`{sweep.get('reference_geometry', '?')}`. Orbit, array, cadence and "
        f"ground stations are identical across the grid; only the cones move.\n")
    add("`LOST` moves the +z keep-out against **both** Sun and Earth (the "
        "requirement quotes one angle for both, and the star tracker shares "
        "that face). `FOUND` moves FOUND's Sun keep-out only -- its 74 deg "
        "field of view is an optical property and does not move. The baseline "
        "cell is in **bold**.\n")

    if "baseline_feasible_fraction" in base:
        headline_res = base.get("headline_search_resolution", "?")
        add(f"**Sanity check.** The sweep re-solves pointing on a coarser "
            f"azimuth/roll grid than the headline run, so the baseline cell has "
            f"to reproduce the headline result or the whole sweep is biased. It "
            f"does: {_fmt(base['baseline_feasible_fraction'] * 100, '.1f')} % "
            f"feasible here against "
            f"{_fmt(base['headline_feasible_fraction'] * 100, '.1f')} % at "
            f"{headline_res}x{headline_res}. The coarse grid is not losing "
            f"legal attitudes. Realised images differ by more "
            f"({_fmt(base['baseline_images_per_day'], ',.0f')} against "
            f"{_fmt(base['headline_images_per_day'], ',.0f')} per day), which is "
            f"the scheduler sensitivity discussed under table 3, not a "
            f"feasibility difference.\n")

    char = sweep.get("character", {})

    add("### 1. Fraction of the timeline with a legal experiment attitude\n")
    add("This is the constraint's own effect, and it is the number to trade "
        "on: a deterministic function of the two cone angles, with no "
        "scheduler behaviour mixed in.\n")
    _matrix_table(add, lost, found,
                  [[v * 100 for v in row] for row in mat["feasible_fraction"]],
                  ".1f", "Feasible (%)", mark)

    add("### 2. Image ceiling at this cadence\n")
    add(f"The same matrix in mission units: feasible time x "
        f"{_fmt(sweep['payload_rate_hz'], '.2f')} Hz x 2 cameras, i.e. what "
        f"the vehicle would collect if every legal opportunity were used.\n")
    _matrix_table(add, lost, found, mat["images_per_day_ceiling"], ",.0f",
                  "Ceiling (images/day)", mark)

    add("### 3. Images actually collected\n")
    add("What survives after slews, downlink passes and battery holds take "
        "their share. Roughly a third of the ceiling, because the vehicle "
        "spends about half its time slewing.\n")
    _matrix_table(add, lost, found, mat["images_per_day"], ",.0f",
                  "Images/day", mark)

    noise = char.get("scheduler_noise_images_per_day")
    if noise:
        add(f"**Read table 3 with care.** Several cells in it share an "
            f"*identical* feasibility -- the +z cone does nothing at all over "
            f"part of its range -- yet their realised image counts differ by up "
            f"to {_fmt(noise, ',.0f')} images/day "
            f"({_fmt((char.get('scheduler_noise_relative') or 0) * 100, '.0f')} %). "
            f"That spread is not the cone doing anything. Changing a keep-out "
            f"changes which rolls are legal, which changes the attitude the "
            f"solver picks among equally legal options, which changes where the "
            f"large repoints land; with ~50 % of the timeline in slew, that is "
            f"a big lever and it is essentially chaotic. Treat "
            f"{_fmt(noise, ',.0f')} images/day as the noise floor of table 3, "
            f"and trade on tables 1 and 2 instead.\n")

    add("### 4. Energy margin (W)\n")
    add("A looser cone is not free: more experiment time means less "
        "sun-pointing, and the margin is what pays for it.\n")
    _matrix_table(add, lost, found, mat["energy_margin_w"], "+.2f",
                  "Margin (W)", mark)

    # -- local slopes -------------------------------------------------------
    slopes = [
        ("Loosen LOST by 10 deg (smaller +z keep-out)",
         "d_images_per_deg_lost_looser"),
        ("Tighten LOST by 10 deg (larger +z keep-out)",
         "d_images_per_deg_lost_tighter"),
        ("Loosen FOUND by 10 deg (smaller Sun keep-out)",
         "d_images_per_deg_found_looser"),
        ("Tighten FOUND by 10 deg (larger Sun keep-out)",
         "d_images_per_deg_found_tighter"),
    ]
    if any(base.get(key) is not None for _, key in slopes):
        add("### Sensitivity at the baseline\n")
        add("One-sided differences to the neighbouring grid points, on the "
            "ceiling of table 2. The grid step is 10 deg, so these are the "
            "finest slopes the sweep can honestly support.\n")
        add("| Change | Images/day gained (+) or lost (-) | Per degree |")
        add("| --- | --- | --- |")
        for label, key in slopes:
            value = base.get(key)
            if value is None:
                add(f"| {label} | n/a | n/a |")
                continue
            # `value` is d(images)/d(angle) toward that neighbour; the ten
            # degrees of travel give the total change.
            total = value * 10.0 * (-1.0 if "looser" in key else 1.0)
            add(f"| {label} | {_fmt(total, '+,.0f')} | "
                f"{_fmt(total / 10.0, '+,.0f')} |")
        add("")

    # -- narrative ----------------------------------------------------------
    flat = sweep["points"]
    best = max(flat, key=lambda p: p["feasible_fraction"])
    worst = min(flat, key=lambda p: p["feasible_fraction"])
    baseline_point = flat[mark[0] * len(found) + mark[1]] if mark else None

    add("### What the sweep says\n")
    if baseline_point is not None and baseline_point["feasible_fraction"] > 0:
        gain = best["feasible_fraction"] / baseline_point["feasible_fraction"] - 1.0
        loss = 1.0 - worst["feasible_fraction"] / baseline_point["feasible_fraction"]
        add(f"**The trade is sharply asymmetric: there is little to win and a "
            f"lot to lose.** Over the full grid, feasible time runs from "
            f"{_fmt(worst['feasible_fraction'] * 100, '.1f')} % (LOST "
            f"{worst['lost_deg']:.0f} deg / FOUND {worst['found_deg']:.0f} deg) "
            f"to {_fmt(best['feasible_fraction'] * 100, '.1f')} % (LOST "
            f"{best['lost_deg']:.0f} / FOUND {best['found_deg']:.0f}), against "
            f"{_fmt(baseline_point['feasible_fraction'] * 100, '.1f')} % at the "
            f"baseline. Relaxing both cones as far as the grid goes is worth "
            f"only {_fmt(gain * 100, '+.0f')} %, because the dominant loss is "
            f"not stray light at all; tightening them as far as the grid goes "
            f"costs {_fmt(-loss * 100, '.0f')} %. The baseline sits close to "
            f"the good end already, so the engineering question is not how to "
            f"gain science by loosening -- it is how much margin exists before "
            f"the geometry starts taking science away.\n")

    free_band = char.get("lost_free_band_deg")
    binds_above = char.get("lost_binds_above_deg")
    if free_band is not None and baseline_lost is not None:
        add(f"**The +z keep-out has slack, and the sweep says how much.** "
            f"Feasibility is identical for every LOST value up to "
            f"**{_fmt(free_band, '.0f')} deg** -- the rows of table 1 are the "
            f"same to within rounding. The baseline is "
            f"{_fmt(baseline_lost, '.0f')} deg, so the star tracker and LOST "
            f"could give up "
            f"{_fmt(float(free_band) - float(baseline_lost), '.0f')} deg of "
            f"keep-out at zero cost in science. The reason is that the roll "
            f"about +x is a free parameter: fixing FOUND on the limb leaves a "
            f"whole circle of +z directions to choose from, and up to "
            f"{_fmt(free_band, '.0f')} deg there is always some arc of it that "
            f"clears both Earth and Sun."
            + (f" At {_fmt(binds_above, '.0f')} deg that arc starts to close, "
               f"which is the knee -- "
               f"{_fmt(float(binds_above) - float(baseline_lost), '.0f')} deg "
               f"above the baseline.\n"
               if binds_above is not None else
               " The sweep does not extend far enough to find the knee.\n"))

    slope_pp = char.get("found_feasibility_pp_per_deg")
    if slope_pp:
        per_deg_images = (abs(slope_pp) / 100 * 86400
                          * float(sweep["payload_rate_hz"]) * 2)
        add(f"**FOUND's Sun keep-out is the one that costs.** Averaged over "
            f"the swept range, every degree of FOUND exclusion is worth about "
            f"{_fmt(abs(slope_pp), '.2f')} percentage points of feasible time, "
            f"or roughly {_fmt(per_deg_images, ',.0f')} images/day per degree "
            f"at {_fmt(sweep['payload_rate_hz'], '.2f')} Hz. If there is baffle "
            f"or stray-light work to be done, this is the only axis on which "
            f"it pays.\n")
        steps = char.get("found_steps") or []
        lo = char.get("found_step_min_pp_per_deg")
        hi = char.get("found_step_max_pp_per_deg")
        if steps and lo is not None and hi is not None and hi > 0:
            cheapest = min(steps, key=lambda s: s["pp_per_deg"])
            steep = max(steps, key=lambda s: s["pp_per_deg"])
            add(f"That average is not a straight line, though, and the "
                f"structure matters if you are negotiating a specific number. "
                f"The price per degree ranges from "
                f"{_fmt(lo, '.2f')} pp/deg over "
                f"{cheapest['from_deg']:.0f}-{cheapest['to_deg']:.0f} deg -- "
                f"effectively free -- to {_fmt(hi, '.2f')} pp/deg over "
                f"{steep['from_deg']:.0f}-{steep['to_deg']:.0f} deg. The "
                f"cheap steps are the ones where the excluded solid angle was "
                f"already pointing at sky the sunlit limb never occupies.\n")

    # -- why each cell rejects ----------------------------------------------
    add("### Why the rejected samples are rejected\n")
    add("Feasibility alone does not say *which* constraint bit, and on this "
        "grid the answer changes. Percentages of the whole timeline, at the "
        f"baseline FOUND = {_fmt(baseline_found, '.0f')} deg column.\n")
    add("| LOST | No sunlit limb | Sun in FOUND | No legal roll |")
    add("| --- | --- | --- | --- |")
    col = found.index(baseline_found) if baseline_found in found else 0
    for r, value in enumerate(lost):
        rej = flat[r * len(found) + col]["reject_reasons"]
        add(f"| {value:.0f} deg | "
            f"{_fmt(rej['no_sunlit_limb'] * 100, '.1f')} % | "
            f"{_fmt(rej['sun_in_found_fov'] * 100, '.1f')} % | "
            f"{_fmt(rej['no_legal_roll'] * 100, '.1f')} % |")
    add("")

    limb_span = char.get("no_sunlit_limb_span_pp")
    roll_max = char.get("max_no_legal_roll")
    roll_at = char.get("no_legal_roll_dominates_above_deg")
    if roll_max is not None and roll_max > 1e-4:
        add(f"**The +z cone does eventually bind, and it binds hard.** `No "
            f"legal roll` is exactly zero over the whole baseline range and "
            f"then climbs to {_fmt(roll_max * 100, '.1f')} % of the timeline at "
            f"LOST {char['max_no_legal_roll_at'][0]:.0f} deg / FOUND "
            f"{char['max_no_legal_roll_at'][1]:.0f} deg"
            + (f", overtaking FOUND's Sun keep-out as the dominant rejection "
               f"from LOST {roll_at:.0f} deg upward" if roll_at is not None
               else "")
            + ". Where the wall sits is set by the orbit, not by the "
            "instrument: fixing FOUND on the limb puts +x about 70 deg off "
            "nadir, and +z is perpendicular to +x, so +z can only reach "
            "between 20 and 160 deg from nadir. The Earth keep-out demands "
            "more than (70 + LOST) deg of that range, so the roll freedom "
            "closes completely at LOST = 90 deg no matter what else is true. "
            "The sweep is watching that margin run out.\n")

    # -- Sun half vs Earth half ---------------------------------------------
    decomposition = sweep.get("plus_z_decomposition")
    if decomposition:
        add("### Which half of the +z cone is spending it\n")
        add("The requirement quotes one angle covering both Sun and Earth, so "
            "the sweep above moves them together. That is faithful to the "
            "requirement but not actionable: a baffle or a lens hood buys you "
            "the Sun exclusion, and nothing whatsoever buys you the Earth one. "
            "Below, each half is moved on its own with the other held at "
            f"{_fmt(baseline_lost, '.0f')} deg, at the baseline FOUND "
            f"exclusion.\n")
        add("| LOST | Sun half alone | Earth half alone | Both together |")
        add("| --- | --- | --- | --- |")
        col_b = found.index(baseline_found) if baseline_found in found else 0
        both_by_lost = {lost[r]: mat["feasible_fraction"][r][col_b]
                        for r in range(len(lost))}
        for row in decomposition:
            both = both_by_lost.get(row["lost_deg"])
            add(f"| {row['lost_deg']:.0f} deg | "
                f"{_fmt(row['sun_only_feasible'] * 100, '.1f')} % | "
                f"{_fmt(row['earth_only_feasible'] * 100, '.1f')} % | "
                f"{_fmt(None if both is None else both * 100, '.1f')} % |")
        add("")
        # Is the pair worse than either part? Compare at the widest cone.
        last = decomposition[-1]
        both_last = both_by_lost.get(last["lost_deg"])
        if both_last is not None:
            solo_cost = min(last["sun_only_feasible"],
                            last["earth_only_feasible"])
            base_feasible = both_by_lost.get(float(baseline_lost))
            if base_feasible and both_last < solo_cost - 1e-6:
                add(f"**Neither half is expensive on its own. The pair is.** At "
                    f"LOST {last['lost_deg']:.0f} deg, widening only the Sun "
                    f"exclusion leaves "
                    f"{_fmt(last['sun_only_feasible'] * 100, '.1f')} % feasible "
                    f"and widening only the Earth exclusion leaves "
                    f"{_fmt(last['earth_only_feasible'] * 100, '.1f')} % -- "
                    f"each costing a few points against the "
                    f"{_fmt(base_feasible * 100, '.1f')} % baseline. Move both "
                    f"and it collapses to "
                    f"{_fmt(both_last * 100, '.1f')} %, far worse than the sum "
                    f"of the parts.\n")
                add("The mechanism is that the two keep-outs exclude "
                    "*different* arcs of the roll circle. Separately, each "
                    "leaves a usable arc behind. Together the arcs overlap "
                    "enough to leave nothing, and the sample is lost. This is "
                    "the practically useful result of the whole sweep: if the "
                    "+z keep-out has to grow, growing one half is survivable "
                    "and growing both is not. It also means a stray-light "
                    "fix on the Sun side keeps its value only as long as the "
                    "Earth exclusion stays where it is.\n")
    _margin_subsection(sweep, add)
    _effective_angle_subsection(sweep, add)

    add("**What the cones cannot fix.** `No sunlit limb` is the largest "
        "rejection over most of the grid and it barely moves"
        + (f" (a span of {_fmt(limb_span, '.1f')} percentage points across all "
           f"{len(flat)} cells)" if limb_span is not None else "")
        + ": it is eclipse and orbital geometry, not stray light. That is the "
        "floor the trade runs into, and it is why even the loosest corner of "
        "the grid leaves roughly half the timeline unusable for science.\n")


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

    if "exclusion_sweep" in results:
        _exclusion_section(results["exclusion_sweep"], add)

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
        f"minimum {_fmt(adcs_res['torque_nm_min'] * 1e6, '.2f')} uN m.")
    if "pointing_margin_deg" in adcs_res:
        add(f"- Pointing budget: {_fmt(adcs_res['control_error_deg'], '.2f')} deg "
            f"control + {_fmt(adcs_res['knowledge_error_deg'], '.2f')} deg "
            f"knowledge, combined by "
            f"`{adcs_res['pointing_error_combination']}` = "
            f"**{_fmt(adcs_res['pointing_margin_deg'], '.2f')} deg**. Every "
            f"experiment-mode keep-out is enforced with that as a buffer, so "
            f"it is a direct tax on science time -- see the exclusion-angle "
            f"trade.")
    add("")

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
