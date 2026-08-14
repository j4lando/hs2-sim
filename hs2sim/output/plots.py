"""Figures for the HS-2 analysis. Silently no-ops if matplotlib is absent."""

from __future__ import annotations

import pathlib

import numpy as np

from ..config import MissionConfig
from ..environment import EnvironmentResult


def make_all(cfg: MissionConfig, env: EnvironmentResult,
             results: dict, out_dir: pathlib.Path) -> None:
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
