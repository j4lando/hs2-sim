"""Figure orchestration for the HS-2 analysis.

The figures themselves live next door -- ``overview`` for the per-run summary
charts, ``exclusion_plots`` for the exclusion-angle trade, ``timeline`` for the
battery power and charge timeline, ``style`` for the shared palette. This
module only decides what gets drawn and in what order, and is the one place
that selects the matplotlib backend.
"""

from __future__ import annotations

import pathlib

from ..config import MissionConfig
from ..conops import ConopsResult
from ..environment import EnvironmentResult
from . import exclusion_plots, overview, timeline


def make_all(cfg: MissionConfig, env: EnvironmentResult,
             results: dict, out_dir: pathlib.Path,
             timelines: dict[str, ConopsResult] | None = None) -> None:
    """Draw every figure the analysis produces into ``out_dir``.

    ``timelines`` maps array geometry name to the scheduler timeline flown for
    it. They are far too large to survive a trip through ``summary.json``, so
    they are passed in directly; without them every figure except the battery
    timeline is still drawn.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(exist_ok=True)

    overview.ground_track(cfg, env, out_dir, plt)
    overview.face_illumination(results, out_dir, plt)
    overview.array_trade(results, out_dir, plt)
    overview.temperature(cfg, results, out_dir, plt)
    overview.payload_rate(results, out_dir, plt)

    if "exclusion_sweep" in results:
        sweep = results["exclusion_sweep"]
        exclusion_plots.margin_curve(sweep, out_dir, plt)
        grids = sweep.get("uncertainty_grids") or []
        if grids:
            # One figure per ADCS uncertainty level, on shared colour scales so
            # they can actually be compared side by side -- per-figure
            # autoscaling would make a collapsing grid look unchanged.
            limits = exclusion_plots.shared_limits(grids)
            for grid in grids:
                exclusion_plots.heatmaps(grid, out_dir, plt,
                                         filename=grid["figure_name"],
                                         limits=limits)
        else:
            exclusion_plots.heatmaps(sweep, out_dir, plt)

    # Last, because it is the only figure that needs a full-rate scheduler
    # timeline handed in: if the caller did not supply one, or the timeline
    # disagrees with the summary, nothing above it is lost.
    if timelines:
        # Every geometry gets its own set of files. The trade between them is
        # the whole point of running three, and an orbit-by-orbit timeline is
        # where a geometry that survives on averages but browns out in a
        # particular orbit shows itself -- which is also why the axis ranges
        # are held common across all three.
        period_min = float(results["orbit"]["orbit_period_min"])
        ylim, soc_ylim = timeline.shared_ranges(cfg, env, timelines)
        for name, flown in timelines.items():
            timeline.battery_power(cfg, env, flown, out_dir, plt,
                                   geometry_name=name, period_min=period_min,
                                   ylim=ylim, soc_ylim=soc_ylim)
