"""The battery power and state-of-charge timeline, one orbit per panel pair.

This is the only figure that needs a full-rate scheduler timeline rather than
the summary dictionary, so it is kept apart from the figures that read
``results`` and can be regenerated from ``summary.json``.
"""

from __future__ import annotations

import pathlib
import re

import numpy as np

from ..config import MissionConfig
from ..conops import MODE_NAMES, ConopsResult
from ..environment import EnvironmentResult
from .style import (BASELINE, INK, INK_MUTED, INK_SECONDARY, LIMIT_LINE,
                    MODE_WASH, MODE_WASH_ALPHA, SUNLIT_TRACK, WASH_TOP)

# One orbit per pair of panels; this many orbits per figure before starting a
# new file. Panel heights are in inches -- power gets the bulk, charge rides
# underneath it on the same x axis.
ORBITS_PER_FIGURE = 6
POWER_PANEL_IN = 1.35
SOC_PANEL_IN = 0.62


def runs(values: np.ndarray) -> list[tuple[int, int, object]]:
    """Contiguous runs of equal value as ``(start, stop_exclusive, value)``."""
    if values.size == 0:
        return []
    change = np.flatnonzero(values[1:] != values[:-1]) + 1
    edges = np.concatenate(([0], change, [values.size]))
    return [(int(a), int(b), values[a]) for a, b in zip(edges[:-1], edges[1:])]


def orbit_segments(env: EnvironmentResult,
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


def _slug(name: str) -> str:
    """Filename-safe form of a geometry name."""
    return re.sub(r"[^0-9A-Za-z_-]+", "_", name).strip("_") or "geometry"


def _series(cfg: MissionConfig, env: EnvironmentResult,
            flown: ConopsResult) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Net power, power the battery actually took, and SOC in percent.

    The second is differenced from the SOC history rather than taken from the
    balance, so it carries the model's clamps: round-trip losses on charge, the
    array shunted at a full battery, and the discharge floor.
    """
    battery = cfg.spacecraft.battery
    capacity_wh = float(battery.capacity_wh)
    level_wh = flown.soc * capacity_wh
    previous = np.concatenate(([float(battery.initial_soc) * capacity_wh],
                               level_wh[:-1]))
    return (flown.generation_w - flown.load_w,
            (level_wh - previous) * 3600.0 / env.dt_s,
            flown.soc * 100.0)


def floor_percent(cfg: MissionConfig) -> float:
    """SOC the scheduler is not allowed to discharge below."""
    return (1.0 - float(cfg.spacecraft.battery.depth_of_discharge_limit)) * 100.0


def shared_ranges(cfg: MissionConfig, env: EnvironmentResult,
                  timelines: dict[str, ConopsResult]
                  ) -> tuple[tuple[float, float], tuple[float, float]]:
    """Power and charge y ranges spanning every geometry.

    Letting each geometry autoscale to its own data would redraw a starved
    timeline to fill its axis and make it look like a healthy one -- and
    comparing the geometries is the whole reason three of them are drawn.
    """
    lows, highs, soc_lows, soc_highs = [], [], [], []
    thresholds: list[float] = []
    for flown in timelines.values():
        net_w, battery_w, soc_pct = _series(cfg, env, flown)
        lows.append(float(min(net_w.min(), battery_w.min())))
        highs.append(float(max(net_w.max(), battery_w.max())))
        soc_lows.append(float(soc_pct.min()))
        soc_highs.append(float(soc_pct.max()))
        if flown.budget is not None:
            thresholds += [flown.budget.soc_safe * 100.0,
                           flown.budget.soc_standby * 100.0,
                           flown.budget.soc_experiment * 100.0]
    return (_power_ylim(min(lows), max(highs)),
            _soc_ylim(min(soc_lows), max(soc_highs), floor_percent(cfg),
                      thresholds=thresholds))


def _power_ylim(low: float, high: float) -> tuple[float, float]:
    """Headroom is lopsided on purpose: the top of the power panel's range is
    where the eclipse strip lives, and the curve must stay clear of it."""
    span = max(high - low, 1.0)
    return (low - 0.06 * span, high + 0.14 * span)


def _soc_ylim(low: float, high: float, floor_pct: float,
              thresholds: list[float] | None = None) -> tuple[float, float]:
    """The floor, the mode-entry thresholds and full charge are always in
    frame, even when the vehicle never approaches them: how much margin is
    being held is the point of the panel, and a range cropped to the curve
    would hide it."""
    # A threshold above a full battery is unreachable by definition. Letting it
    # set the range would stretch the axis to 200 % and flatten the curve that
    # the panel exists to show; the legend still reports its value.
    in_frame = [v for v in (thresholds or []) if 0.0 <= v <= 100.0]
    low = min([low, floor_pct] + in_frame)
    high = max([high, 100.0] + in_frame)
    span = max(high - low, 1.0)
    return (low - 0.12 * span, high + 0.12 * span)


def battery_power(cfg: MissionConfig, env: EnvironmentResult,
                  flown: ConopsResult, out_dir: pathlib.Path, plt,
                  geometry_name: str, period_min: float,
                  ylim: tuple[float, float] | None = None,
                  soc_ylim: tuple[float, float] | None = None
                  ) -> list[pathlib.Path]:
    """Battery power and charge against time, one orbit per panel pair.

    Each orbit gets a tall power panel over a short state-of-charge panel on
    the same x axis. Power and charge are different quantities, so they get
    different axes rather than being crushed onto one with two scales; stacking
    them keeps the flow and the level readable against each other anyway.

    The power panel carries two curves, both in watts:

    * the power balance, generation minus load, which is what the battery is
      being asked to absorb or supply;
    * what the battery actually took, differenced from the SOC history. It
      departs from the balance wherever the model clamps -- round-trip losses
      on charge, the array shunted at a full battery, the discharge floor -- so
      the gap between the two is exactly where stored energy is not the thing
      limiting the vehicle.

    The charge panel carries SOC against the configured discharge floor, which
    is what the two power curves integrate to and the constraint the scheduler
    is actually flying against.

    Orbits share their axis ranges, so a feature can be read down the column
    across successive orbits rather than only within one. Pass ``ylim`` and
    ``soc_ylim`` -- from `shared_ranges` -- to hold those ranges across several
    geometries as well; without them each call scales to its own data.

    Files are written as ``battery_power_<geometry>_NN.png``, and their paths
    returned.
    """
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.ticker import MaxNLocator

    dt = env.dt_s
    segments = orbit_segments(env, period_min * 60.0)
    if not segments:
        return []

    net_w, battery_w, soc_pct = _series(cfg, env, flown)
    floor_pct = floor_percent(cfg)
    # The thresholds the scheduler actually flew, drawn where the SOC curve can
    # be read against them: each band is an activity the vehicle could afford.
    entries = []
    if flown.budget is not None:
        entries = [("safe entry", flown.budget.soc_safe * 100.0),
                   ("downlink affordable", flown.budget.soc_standby * 100.0),
                   ("experiment affordable",
                    flown.budget.soc_experiment * 100.0)]

    eclipsed = env.shadow_factor < 0.5      # same umbra test as the summary
    mode_names = np.array([MODE_NAMES.get(int(m), "") for m in flown.mode])

    # One y range per quantity for every axis in every figure, so orbits are
    # comparable down the column.
    if ylim is None:
        ylim = _power_ylim(float(min(net_w.min(), battery_w.min())),
                           float(max(net_w.max(), battery_w.max())))
    if soc_ylim is None:
        soc_ylim = _soc_ylim(float(soc_pct.min()), float(soc_pct.max()),
                             floor_pct,
                             thresholds=[v for _, v in entries])

    modes_seen = [name for name in MODE_WASH if np.any(mode_names == name)]
    handles = [Patch(facecolor=MODE_WASH[name], alpha=MODE_WASH_ALPHA,
                     edgecolor="none", label=name)
               for name in modes_seen]
    handles += [
        Line2D([], [], color=MODE_WASH["downlink"], marker="v", ms=5, ls="none",
               label="downlink contact"),
        Patch(facecolor=INK_SECONDARY, edgecolor="none",
              label="eclipse (band at top)"),
        Line2D([], [], color=INK, lw=1.3, label="generation - load"),
        Line2D([], [], color=INK_SECONDARY, lw=1.1, ls=(0, (4, 2)),
               label="into battery (after losses and limits)"),
        # The charge curve itself needs no legend entry -- it is the only
        # series in its panel and the panel's axis label names it.
        Line2D([], [], color=LIMIT_LINE, lw=1.0, ls="--",
               label=f"cell floor ({floor_pct:.0f} % SOC)"),
    ]
    if entries:
        handles.append(
            Line2D([], [], color=INK_MUTED, lw=0.9, ls=(0, (1, 2)),
                   label="mode entry: " + ", ".join(
                       f"{name} {value:.0f} %" for name, value in entries)))

    written: list[pathlib.Path] = []
    numbered = list(enumerate(segments, start=1))
    chunks = [numbered[i:i + ORBITS_PER_FIGURE]
              for i in range(0, len(numbered), ORBITS_PER_FIGURE)]
    for chunk_index, chunk in enumerate(chunks, start=1):
        # Chrome is budgeted in inches, not in fractions, so a short final
        # figure gets the same title and legend band as a full one instead of
        # scaling them up with the page. The top band holds the figure title
        # and, below it, the first orbit's own header, so it is deeper than the
        # title alone needs.
        title_in, legend_in, xlabel_in = 0.62, 0.9, 0.42
        group_in = POWER_PANEL_IN + SOC_PANEL_IN
        gap_in = 0.24 * group_in
        height = (len(chunk) * group_in + (len(chunk) - 1) * gap_in
                  + title_in + legend_in + xlabel_in + 0.12)
        fig = plt.figure(figsize=(11, height))
        # One outer cell per orbit, split into a power panel and a charge panel
        # that share the orbit's x axis. The nesting is what lets the two
        # panels of one orbit sit tight against each other while consecutive
        # orbits stay visibly apart -- a single flat grid would have to space
        # them all the same, and the pairing would stop reading as a pairing.
        outer = fig.add_gridspec(
            len(chunk), 1, hspace=gap_in / group_in,
            left=0.075, right=0.985,
            top=1.0 - (title_in + 0.06) / height,
            bottom=(legend_in + xlabel_in) / height)

        power_axes, soc_axes = [], []
        for row, (cell, (orbit_number, (start, stop, t_ref))) in enumerate(
                zip(outer, chunk)):
            inner = cell.subgridspec(
                2, 1, height_ratios=[POWER_PANEL_IN, SOC_PANEL_IN], hspace=0.12)
            # Power panels share a y range with each other and charge panels
            # with each other; the two quantities never share an axis.
            ax = fig.add_subplot(inner[0],
                                 sharex=power_axes[0] if power_axes else None,
                                 sharey=power_axes[0] if power_axes else None)
            ax_soc = fig.add_subplot(inner[1], sharex=ax,
                                     sharey=soc_axes[0] if soc_axes else None)
            power_axes.append(ax)
            soc_axes.append(ax_soc)

            minutes = (env.t_s[start:stop] - t_ref) / 60.0
            # Spans are drawn to the far edge of the last sample they cover,
            # so consecutive spans meet instead of leaving a gap of a sample.
            edge = np.concatenate((minutes, [minutes[-1] + dt / 60.0]))

            # Mode washes and the terminator hairlines run through both panels,
            # so a charge feature can be attributed without looking away.
            for a, b, name in runs(mode_names[start:stop]):
                colour = MODE_WASH.get(str(name))
                if colour is None:
                    continue
                ax.axvspan(edge[a], edge[b], ymin=0.0, ymax=WASH_TOP,
                           facecolor=colour, alpha=MODE_WASH_ALPHA, lw=0,
                           zorder=0)
                # Lighter in the charge panel: it is a fraction of the height,
                # so the same alpha there reads as a much heavier block and
                # swamps the curve.
                ax_soc.axvspan(edge[a], edge[b], facecolor=colour,
                               alpha=0.6 * MODE_WASH_ALPHA, lw=0, zorder=0)
                if name == "downlink":
                    # A contact clears the backlog in seconds -- the downlink
                    # budget is enormously over-provisioned -- so a truthful
                    # wash for one is often a single sample, which is sub-pixel
                    # on a 90-minute axis and reads as "it never downlinked".
                    # Mark the contact so it can be found, and leave the wash
                    # itself honest about how long it actually lasted.
                    ax.plot(0.5 * (edge[a] + edge[b]), WASH_TOP - 0.05,
                            marker="v", ms=5, color=MODE_WASH["downlink"],
                            transform=ax.get_xaxis_transform(), zorder=7,
                            clip_on=False)

            # Eclipse rides in its own strip above the washes on the power
            # panel, and drops a hairline through both at each terminator
            # crossing so a dip can be tied to it by eye. The strip is laid
            # down as a full-width track first, so an unfilled stretch reads as
            # "sunlit" rather than as somewhere the shading simply ran out.
            ax.axvspan(edge[0], edge[-1], ymin=WASH_TOP, ymax=1.0,
                       facecolor=SUNLIT_TRACK, lw=0, zorder=5)
            for a, b, dark in runs(eclipsed[start:stop]):
                if not dark:
                    continue
                ax.axvspan(edge[a], edge[b], ymin=WASH_TOP, ymax=1.0,
                           facecolor=INK_SECONDARY, lw=0, zorder=6)
                for boundary in (edge[a], edge[b]):
                    for axis in (ax, ax_soc):
                        axis.axvline(boundary, color=INK_MUTED, lw=0.6,
                                     ls=(0, (2, 3)), zorder=1)

            ax.axhline(0.0, color=BASELINE, lw=0.9, zorder=2)
            ax.plot(minutes, battery_w[start:stop], color=INK_SECONDARY,
                    lw=1.1, ls=(0, (4, 2)), zorder=3)
            ax.plot(minutes, net_w[start:stop], color=INK, lw=1.3, zorder=4)

            ax_soc.axhline(floor_pct, color=LIMIT_LINE, ls="--", lw=1.0,
                           zorder=2)
            for _, value in entries:
                ax_soc.axhline(value, color=INK_MUTED, ls=(0, (1, 2)), lw=0.9,
                               zorder=2)
            ax_soc.plot(minutes, soc_pct[start:stop], color=INK, lw=1.3,
                        zorder=4)

            # The orbit's minimum SOC is the number the design is actually
            # judged on, so it goes in the header rather than being left to be
            # read off the curve.
            hours = env.t_s[start] / 3600.0
            ax.set_title(f"orbit {orbit_number}   t = {hours:.2f} h   "
                         f"min SOC {soc_pct[start:stop].min():.1f} %",
                         loc="left", fontsize=8, color=INK_SECONDARY, pad=3)
            ax.set_ylim(*ylim)
            ax_soc.set_ylim(*soc_ylim)
            # Pinned tick counts: the panels are short, and letting the locator
            # choose would give the last, shorter figure a different ladder
            # from the full ones and break the read-down-the-column comparison.
            ax.yaxis.set_major_locator(MaxNLocator(nbins=4, steps=[1, 2, 5, 10]))
            ax_soc.yaxis.set_major_locator(
                MaxNLocator(nbins=3, steps=[1, 2, 5, 10]))
            ax.set_ylabel("power (W)", fontsize=8, color=INK_SECONDARY)
            ax_soc.set_ylabel("SOC (%)", fontsize=8, color=INK_SECONDARY)
            for axis in (ax, ax_soc):
                axis.grid(axis="y", alpha=0.25, lw=0.6)
                axis.tick_params(labelsize=8, colors=INK_MUTED)
                for spine in ("top", "right"):
                    axis.spines[spine].set_visible(False)
            ax.tick_params(labelbottom=False)
            if row != len(chunk) - 1:
                ax_soc.tick_params(labelbottom=False)

        power_axes[0].set_xlim(0.0, period_min)
        soc_axes[-1].set_xlabel("Minutes since ascending node", fontsize=9)
        first, last = chunk[0][0], chunk[-1][0]
        fig.suptitle(f"Battery power and state of charge over the CONOPS "
                     f"timeline -- {geometry_name}, orbits {first}-{last} of "
                     f"{len(segments)}", fontsize=11,
                     y=1.0 - 0.28 / height)
        # Anchored to the top of its reserved band rather than to the page, so
        # it sits under the x label instead of at the far bottom edge.
        fig.legend(handles=handles, loc="upper center",
                   bbox_to_anchor=(0.5, legend_in / height), ncol=4,
                   fontsize=8, frameon=False)
        name = out_dir / f"battery_power_{_slug(geometry_name)}_{chunk_index:02d}.png"
        fig.savefig(name, dpi=140)
        plt.close(fig)
        written.append(name)
    return written
