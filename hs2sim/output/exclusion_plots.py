"""The camera exclusion-angle trade figures.

These read only the ``exclusion_sweep`` branch of the results dictionary, so
they can be regenerated from a saved ``summary.json`` without a propagation --
which is what ``regen_report.py`` does.
"""

from __future__ import annotations

import pathlib

import numpy as np


def shared_limits(grids: list[dict]) -> dict:
    """Common colour range per panel across a family of grids."""
    limits: dict[str, tuple[float, float]] = {}
    for key in ("feasible_fraction", "images_per_day_ceiling",
                "images_per_day", "energy_margin_w"):
        values = [v for g in grids for row in g["matrices"][key] for v in row]
        if values:
            limits[key] = (min(values), max(values))
    return limits


def margin_curve(sweep: dict, out_dir: pathlib.Path, plt) -> None:
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


def heatmaps(sweep: dict, out_dir: pathlib.Path, plt,
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
