"""Figures for the HS-2 analysis. Silently no-ops if matplotlib is absent."""

from __future__ import annotations

import pathlib

import numpy as np

from ..config import MissionConfig
from ..conops import MODE_NAMES, ConopsResult
from ..environment import EnvironmentResult

# Background wash per flown mode. Blue, orange and aqua are the first three
# slots of the categorical palette -- the three that stay separable under
# colour-vision deficiency when every pair can appear together, which is the
# case here because the scheduler can put any two modes side by side. SLEW is
# deliberately neutral: it is a transition between identities rather than one
# of its own, and it abuts every other mode, so giving it a hue would put two
# saturated washes against each other at every mode change. SAFE takes the
# status-critical red.
MODE_WASH = {
    "safe": "#d03b3b",
    "standby": "#1baf7a",
    "slew": "#898781",
    "experiment": "#2a78d6",
    "downlink": "#eb6834",
}
MODE_WASH_ALPHA = 0.22
# The washes stop short of the top of the axes; the strip above them carries
# eclipse, which is a separate channel and must not be confused with a mode.
WASH_TOP = 0.94

INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
BASELINE = "#c3c2b7"

# One orbit per axis; this many axes per figure before starting a new file.
ORBITS_PER_FIGURE = 6


def make_all(cfg: MissionConfig, env: EnvironmentResult,
             results: dict, out_dir: pathlib.Path,
             timelines: dict[str, ConopsResult] | None = None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(exist_ok=True)

    # -- ground track with station visibility circles ------------------------
    fig, ax = plt.subplots(figsize=(11, 5.5))
    dcm = env.dcm_PN
    r_fixed = np.einsum("nij,nj->ni", dcm, env.r_BN_N)
    lat = np.degrees(np.arcsin(np.clip(r_fixed[:, 2]
                                       / np.linalg.norm(r_fixed, axis=1), -1, 1)))
    lon = np.degrees(np.arctan2(r_fixed[:, 1], r_fixed[:, 0]))
    jump = np.abs(np.diff(lon)) > 180
    lon_plot = lon.astype(float).copy()
    lon_plot[:-1][jump] = np.nan
    ax.plot(lon_plot, lat, lw=0.4, color="tab:blue", alpha=0.7, label="ground track")
    for station in cfg.stations():
        ax.plot(float(station.longitude_deg), float(station.latitude_deg),
                "r^", ms=7)
        ax.annotate(str(station.name).split(",")[0],
                    (float(station.longitude_deg), float(station.latitude_deg)),
                    fontsize=6, xytext=(3, 3), textcoords="offset points")
    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)
    ax.set_xlabel("Longitude (deg)")
    ax.set_ylabel("Latitude (deg)")
    ax.set_title("HS-2 ground track and Leaf Space stations "
                 "(station coordinates approximate)")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "ground_track.png", dpi=140)
    plt.close(fig)

    # -- per-face illumination ----------------------------------------------
    first_name = next(iter(results["geometries"]))
    thermal_data = results["geometries"][first_name]["thermal"]
    faces = list(thermal_data)
    solar = [thermal_data[f]["mean_solar_flux_w_m2"] for f in faces]
    albedo = [thermal_data[f]["mean_albedo_flux_w_m2"] for f in faces]
    ir = [thermal_data[f]["mean_ir_flux_w_m2"] for f in faces]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(faces))
    ax.bar(x, solar, label="direct solar", color="#e8a33d")
    ax.bar(x, albedo, bottom=solar, label="albedo", color="#7fb3d5")
    ax.bar(x, ir, bottom=np.array(solar) + np.array(albedo),
           label="Earth IR", color="#c0554e")
    ax.set_xticks(x)
    ax.set_xticklabels(faces)
    ax.set_ylabel("Mean absorbed flux (W/m$^2$)")
    ax.set_title(f"Time-averaged illumination per face ({first_name})")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "face_illumination.png", dpi=140)
    plt.close(fig)

    # -- array geometry comparison ------------------------------------------
    names = list(results["geometries"])
    peak = [results["geometries"][n]["peak_total_w"] for n in names]
    standby = [results["geometries"][n]["power_standby"]["orbit_average_w"]
               for n in names]
    experiment = [results["geometries"][n]["power_experiment"]["orbit_average_w"]
                  for n in names]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(names))
    width = 0.27
    ax.bar(x - width, peak, width, label="peak (no cosine loss)", color="#b0b0b0")
    ax.bar(x, standby, width, label="orbit avg, sun-pointing", color="#3d7ea8")
    ax.bar(x + width, experiment, width, label="orbit avg, experiment attitude",
           color="#4e9a51")
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=8)
    ax.set_ylabel("Power (W)")
    ax.set_title("Solar array geometry trade")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "array_trade.png", dpi=140)
    plt.close(fig)

    # -- single node temperature --------------------------------------------
    if "temperature_series_c" in results["geometries"][names[0]]:
        fig, ax = plt.subplots(figsize=(9, 4.5))
        for name in names:
            entry = results["geometries"][name]
            ax.plot(entry["temperature_series_t_h"], entry["temperature_series_c"],
                    lw=1.0, label=name)
        limits = cfg.spacecraft.thermal.limits_c
        ax.axhline(float(limits.battery_min), color="#3d5a80", ls="--", lw=1,
                   label="battery limits")
        ax.axhline(float(limits.battery_max), color="#3d5a80", ls="--", lw=1)
        ax.set_xlabel("Time (hours)")
        ax.set_ylabel("Bulk temperature (deg C)")
        ax.set_title("Single-node spacecraft temperature")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out_dir / "temperature.png", dpi=140)
        plt.close(fig)

    # -- payload rate wall ---------------------------------------------------
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    for name in names:
        sweep = results["geometries"][name]["payload_rate_sweep"]
        requested = [r["requested_rate_hz"] for r in sweep]
        achieved = [r["images_per_day"] for r in sweep]
        ax.plot(requested, achieved, "o-", label=name)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Requested experiment rate (Hz)")
    ax.set_ylabel("Images per day achieved")
    ax.set_title("Where the payload cadence saturates")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "payload_rate.png", dpi=140)
    plt.close(fig)

    # -- exclusion-angle trade -----------------------------------------------
    if "exclusion_sweep" in results:
        sweep = results["exclusion_sweep"]
        _margin_curve(sweep, out_dir, plt)
        grids = sweep.get("uncertainty_grids") or []
        if grids:
            # One figure per ADCS uncertainty level, on shared colour scales so
            # they can actually be compared side by side -- per-figure
            # autoscaling would make a collapsing grid look unchanged.
            limits = _shared_limits(grids)
            for grid in grids:
                _exclusion_heatmaps(grid, out_dir, plt,
                                    filename=grid["figure_name"],
                                    limits=limits)
        else:
            _exclusion_heatmaps(sweep, out_dir, plt)

    # -- battery power, one orbit per axis -----------------------------------
    # Last, because it is the only figure that needs a full-rate scheduler
    # timeline handed in: if the caller did not supply one, or the timeline
    # disagrees with the summary, nothing above it is lost.
    if timelines:
        # Draw the geometry that is actually flyable -- the one with the best
        # energy margin -- so the timeline shown is the one the mission would
        # fly. Same rule the exclusion sweep uses to pick its reference.
        def margin(name: str) -> float:
            return float(results["geometries"][name]["conops_baseline"]
                         ["energy_margin_w"])

        choice = max(timelines, key=margin)
        _battery_power(cfg, env, timelines[choice], out_dir, plt,
                       geometry_name=choice,
                       period_min=float(results["orbit"]["orbit_period_min"]))


def _runs(values: np.ndarray) -> list[tuple[int, int, object]]:
    """Contiguous runs of equal value as ``(start, stop_exclusive, value)``."""
    if values.size == 0:
        return []
    change = np.flatnonzero(values[1:] != values[:-1]) + 1
    edges = np.concatenate(([0], change, [values.size]))
    return [(int(a), int(b), values[a]) for a, b in zip(edges[:-1], edges[1:])]


def _orbit_segments(env: EnvironmentResult,
                    period_s: float) -> list[tuple[int, int, float]]:
    """Split the propagation at ascending-node crossings.

    Returns ``(start, stop_exclusive, t_ref)`` per orbit, where ``t_ref`` is the
    time the orbit began. The run almost never starts exactly on a node, so the
    leading fragment gets a back-dated reference: that keeps its phase aligned
    with the whole orbits drawn below it instead of shifting every feature by
    however far into an orbit the epoch happened to fall.
    """
    z = env.r_BN_N[:, 2]
    crossings = np.flatnonzero((z[:-1] < 0.0) & (z[1:] >= 0.0)) + 1
    if crossings.size < 2:
        return [(0, env.n_samples, float(env.t_s[0]))]
    edges = np.concatenate(([0], crossings, [env.n_samples]))
    segments = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b - a < 2:
            continue          # sub-sample sliver at either end
        t_ref = (float(env.t_s[crossings[0]]) - period_s if a == 0
                 else float(env.t_s[a]))
        segments.append((int(a), int(b), t_ref))
    return segments


def _battery_power(cfg: MissionConfig, env: EnvironmentResult,
                   timeline: ConopsResult, out_dir: pathlib.Path, plt,
                   geometry_name: str, period_min: float) -> list[pathlib.Path]:
    """Battery power against time, one orbit per axis, shaded by flown mode.

    Two curves, both in watts so they share the one y axis:

    * the power balance, generation minus load, which is what the battery is
      being asked to absorb or supply;
    * what the battery actually took, differenced from the SOC history. It
      departs from the balance wherever the model clamps -- round-trip losses
      on charge, the array shunted at a full battery, the discharge floor -- so
      the gap between the two is exactly where stored energy is not the thing
      limiting the vehicle.

    Orbits share both axis ranges, so a feature can be read down the column
    across successive orbits rather than only within one.
    """
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.ticker import MaxNLocator

    dt = env.dt_s
    period_s = period_min * 60.0
    segments = _orbit_segments(env, period_s)
    if not segments:
        return []

    net_w = timeline.generation_w - timeline.load_w

    battery = cfg.spacecraft.battery
    capacity_wh = float(battery.capacity_wh)
    level_wh = timeline.soc * capacity_wh
    previous = np.concatenate(([float(battery.initial_soc) * capacity_wh],
                               level_wh[:-1]))
    battery_w = (level_wh - previous) * 3600.0 / dt

    eclipsed = env.shadow_factor < 0.5      # same umbra test as the summary
    mode_names = np.array([MODE_NAMES.get(int(m), "") for m in timeline.mode])

    # One y range for every axis in every figure, so orbits are comparable.
    # The headroom is lopsided on purpose: the top of the range is where the
    # eclipse strip lives, and the curve must stay clear of it.
    low = float(min(net_w.min(), battery_w.min()))
    high = float(max(net_w.max(), battery_w.max()))
    span = max(high - low, 1.0)
    ylim = (low - 0.06 * span, high + 0.14 * span)

    modes_seen = [name for name in MODE_WASH if np.any(mode_names == name)]
    handles = [Patch(facecolor=MODE_WASH[name], alpha=MODE_WASH_ALPHA,
                     edgecolor="none", label=name)
               for name in modes_seen]
    handles += [
        Patch(facecolor=INK_SECONDARY, edgecolor="none",
              label="eclipse (band at top)"),
        Line2D([], [], color=INK, lw=1.3, label="generation - load"),
        Line2D([], [], color=INK_SECONDARY, lw=1.1, ls=(0, (4, 2)),
               label="into battery (after losses and limits)"),
    ]

    written: list[pathlib.Path] = []
    numbered = list(enumerate(segments, start=1))
    chunks = [numbered[i:i + ORBITS_PER_FIGURE]
              for i in range(0, len(numbered), ORBITS_PER_FIGURE)]
    for chunk_index, chunk in enumerate(chunks, start=1):
        # Chrome is budgeted in inches, not in fractions, so a short final
        # figure gets the same title and legend band as a full one instead of
        # scaling them up with the page.
        title_in, legend_in = 0.42, 0.8
        height = 1.55 * len(chunk) + title_in + legend_in + 0.3
        fig, axes = plt.subplots(len(chunk), 1, sharex=True, sharey=True,
                                 figsize=(11, height))
        axes = np.atleast_1d(axes)
        for ax, (orbit_number, (start, stop, t_ref)) in zip(axes, chunk):
            minutes = (env.t_s[start:stop] - t_ref) / 60.0
            # Spans are drawn to the far edge of the last sample they cover,
            # so consecutive spans meet instead of leaving a gap of a sample.
            edge = np.concatenate((minutes, [minutes[-1] + dt / 60.0]))

            for a, b, name in _runs(mode_names[start:stop]):
                colour = MODE_WASH.get(str(name))
                if colour is None:
                    continue
                ax.axvspan(edge[a], edge[b], ymin=0.0, ymax=WASH_TOP,
                           facecolor=colour, alpha=MODE_WASH_ALPHA, lw=0,
                           zorder=0)

            # Eclipse rides in its own strip above the washes, and drops a
            # hairline through the plot at each terminator crossing so a dip in
            # the curve can be tied to it by eye. The strip is laid down as a
            # full-width track first, so an unfilled stretch reads as "sunlit"
            # rather than as somewhere the shading simply ran out.
            ax.axvspan(edge[0], edge[-1], ymin=WASH_TOP, ymax=1.0,
                       facecolor="#e1e0d9", lw=0, zorder=5)
            for a, b, dark in _runs(eclipsed[start:stop]):
                if not dark:
                    continue
                ax.axvspan(edge[a], edge[b], ymin=WASH_TOP, ymax=1.0,
                           facecolor=INK_SECONDARY, lw=0, zorder=6)
                for boundary in (edge[a], edge[b]):
                    ax.axvline(boundary, color=INK_MUTED, lw=0.6,
                               ls=(0, (2, 3)), zorder=1)

            ax.axhline(0.0, color=BASELINE, lw=0.9, zorder=2)
            ax.plot(minutes, battery_w[start:stop], color=INK_SECONDARY,
                    lw=1.1, ls=(0, (4, 2)), zorder=3)
            ax.plot(minutes, net_w[start:stop], color=INK, lw=1.3, zorder=4)

            hours = env.t_s[start] / 3600.0
            ax.set_title(f"orbit {orbit_number}   t = {hours:.2f} h",
                         loc="left", fontsize=8, color=INK_SECONDARY, pad=3)
            ax.set_ylim(*ylim)
            # Pinned tick count: the rows are short, and letting the locator
            # choose would give the last, shorter figure a different ladder
            # from the full ones and break the read-down-the-column comparison.
            ax.yaxis.set_major_locator(MaxNLocator(nbins=4, steps=[1, 2, 5, 10]))
            ax.grid(axis="y", alpha=0.25, lw=0.6)
            ax.tick_params(labelsize=8, colors=INK_MUTED)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)

        axes[0].set_xlim(0.0, period_min)
        axes[-1].set_xlabel("Minutes since ascending node", fontsize=9)
        fig.supylabel("Battery power (W)   charge positive", fontsize=9)
        first, last = chunk[0][0], chunk[-1][0]
        fig.suptitle(f"Battery power over the CONOPS timeline -- "
                     f"{geometry_name}, orbits {first}-{last} of "
                     f"{len(segments)}", fontsize=11,
                     y=1.0 - 0.27 / height)
        # Anchored to the top of its reserved band rather than to the page, so
        # it sits under the x label instead of at the far bottom edge.
        fig.legend(handles=handles, loc="upper center",
                   bbox_to_anchor=(0.5, legend_in / height), ncol=4,
                   fontsize=8, frameon=False)
        fig.tight_layout(rect=(0.02, legend_in / height, 1.0,
                               1.0 - title_in / height))
        name = out_dir / f"battery_power_{chunk_index:02d}.png"
        fig.savefig(name, dpi=140)
        plt.close(fig)
        written.append(name)
    return written


def _shared_limits(grids: list[dict]) -> dict:
    """Common colour range per panel across a family of grids."""
    limits: dict[str, tuple[float, float]] = {}
    for key in ("feasible_fraction", "images_per_day_ceiling",
                "images_per_day", "energy_margin_w"):
        values = [v for g in grids for row in g["matrices"][key] for v in row]
        if values:
            limits[key] = (min(values), max(values))
    return limits


def _margin_curve(sweep: dict, out_dir: pathlib.Path, plt) -> None:
    """Feasibility against the pointing-error buffer."""
    rows = sorted(sweep.get("margin_sweep") or [], key=lambda r: r["margin_deg"])
    if len(rows) < 2:
        return
    margin = [r["margin_deg"] for r in rows]
    feasible = [r["feasible_fraction"] * 100 for r in rows]
    no_roll = [r["reject_reasons"]["no_legal_roll"] * 100 for r in rows]
    sun_found = [r["reject_reasons"]["sun_in_found_fov"] * 100 for r in rows]
    applied = sweep.get("pointing_margin_deg")

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.2))
    ax.plot(margin, feasible, "o-", color="#3d7ea8")
    ax.set_xlabel("Pointing-error buffer (deg)")
    ax.set_ylabel("Legal attitude exists (%)")
    ax.set_title("Cost of the pointing budget", fontsize=10)
    ax.grid(alpha=0.3)
    ax.set_ylim(bottom=0)

    # Stacked rejections: which constraint the buffer pushes samples into.
    ax2.stackplot(margin, sun_found, no_roll,
                  labels=["Sun in FOUND", "no legal roll"],
                  colors=["#e8a33d", "#c0554e"])
    ax2.set_xlabel("Pointing-error buffer (deg)")
    ax2.set_ylabel("Rejected timeline (%)")
    ax2.set_title("Which constraint the buffer trips", fontsize=10)
    ax2.legend(fontsize=8, loc="upper left")
    ax2.grid(alpha=0.3)

    if applied is not None:
        for axis in (ax, ax2):
            axis.axvline(applied, color="#4e9a51", ls="--", lw=1.2)
            axis.annotate(f"as designed\n{applied:.2f} deg", (applied, 0),
                          xytext=(4, 6), textcoords="offset points",
                          fontsize=7, color="#4e9a51")
    fig.tight_layout()
    fig.savefig(out_dir / "pointing_margin.png", dpi=140)
    plt.close(fig)


def _exclusion_heatmaps(sweep: dict, out_dir: pathlib.Path, plt,
                        filename: str = "exclusion_sweep.png",
                        limits: dict | None = None) -> None:
    lost = sweep["lost_deg"]
    found = sweep["found_deg"]
    mat = sweep["matrices"]
    base = sweep.get("baseline", {})

    # Panels 1 and 2 are the same quantity in different units and carry the
    # trade; panel 3 is what the scheduler actually delivers and is noisy (see
    # `exclusion.characterise`); panel 4 is what it costs.
    panels = [
        ("feasible_fraction", "Legal attitude exists (%)", 100.0, "{:.1f}", "viridis"),
        ("images_per_day_ceiling", "Image ceiling (images/day)", 1.0, "{:,.0f}",
         "viridis"),
        ("images_per_day", "Images actually collected (noisy)", 1.0, "{:,.0f}",
         "magma"),
        ("energy_margin_w", "Energy margin (W)", 1.0, "{:+.2f}", "coolwarm_r"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(11, 8.5))
    for ax, (key, title, scale, cell_fmt, cmap) in zip(axes.ravel(), panels):
        data = np.array(mat[key], dtype=float) * scale
        span = (limits or {}).get(key)
        im = ax.imshow(data, origin="lower", aspect="auto", cmap=cmap,
                       vmin=None if span is None else span[0] * scale,
                       vmax=None if span is None else span[1] * scale)
        margin = float(sweep.get("pointing_margin_deg") or 0.0)
        ax.set_xticks(np.arange(len(found)))
        ax.set_yticks(np.arange(len(lost)))
        if margin > 0:
            # Quoted angle with the effective half-angle it becomes once the
            # attitude uncertainty is added -- that is the number the geometry
            # actually enforces, and past 90 deg the cone exceeds a hemisphere.
            ax.set_xticklabels([f"{v:.0f}\n({v + margin:.0f})" for v in found],
                               fontsize=8)
            ax.set_yticklabels([f"{v:.0f}\n({v + margin:.0f})" for v in lost],
                               fontsize=8)
            ax.set_xlabel("FOUND Sun exclusion: quoted (effective) deg")
            ax.set_ylabel("LOST / star tracker: quoted (effective) deg")
        else:
            ax.set_xticklabels([f"{v:.0f}" for v in found])
            ax.set_yticklabels([f"{v:.0f}" for v in lost])
            ax.set_xlabel("FOUND Sun exclusion (deg)")
            ax.set_ylabel("LOST / star tracker exclusion (deg)")
        ax.set_title(title, fontsize=10)
        for r in range(len(lost)):
            for c in range(len(found)):
                # Pick the label colour off the cell's actual rendered
                # luminance. Using the normalised value instead breaks on
                # diverging maps, whose midpoint is the *lightest* colour.
                red, green, blue, _ = im.cmap(im.norm(data[r, c]))
                luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
                ax.text(c, r, cell_fmt.format(data[r, c]),
                        ha="center", va="center", fontsize=7,
                        color="white" if luminance < 0.5 else "black")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)

        # Ring the baseline cell.
        if base.get("lost_deg") in lost and base.get("found_deg") in found:
            r = lost.index(base["lost_deg"])
            c = found.index(base["found_deg"])
            ax.add_patch(plt.Rectangle((c - 0.5, r - 0.5), 1, 1, fill=False,
                                       edgecolor="#00ff88", lw=2.0))

    margin = float(sweep.get("pointing_margin_deg") or 0.0)
    fig.suptitle(
        f"Camera exclusion-angle trade  |  ADCS uncertainty "
        f"{margin:.2f} deg  |  {sweep.get('reference_geometry', '')}, "
        f"{sweep['payload_rate_hz']:.2f} Hz  |  green box is the baseline",
        fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out_dir / filename, dpi=140)
    plt.close(fig)
