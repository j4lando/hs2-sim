#!/usr/bin/env python3
"""Re-render the exclusion figure from ``results/summary.json``.

The simulation is the expensive part; re-deriving the exclusion sweep is not.
This exists so the sweep's derived statistics can be iterated on without
re-running a propagation, and so a summary produced by an older build can be
re-read by the current analysis code.

It recomputes anything derived (``exclusion_sweep.character``) rather than
trusting what is stored, so the output matches what a fresh run would produce.

    python regen_report.py

Only the exclusion heatmap is regenerated. The other figures need the
propagated environment, so re-run ``run_analysis.py`` for those.
"""

from __future__ import annotations

import json

from hs2sim import adcs, exclusion
from hs2sim.config import MissionConfig, RESULTS_DIR


def main() -> int:
    with open(RESULTS_DIR / "summary.json", "r", encoding="utf-8") as handle:
        results = json.load(handle)

    cfg = MissionConfig()

    sweep = results.get("exclusion_sweep")
    if sweep is None:
        print("No exclusion_sweep in results/summary.json; nothing to do")
        return 1

    sweep["character"] = exclusion.characterise(sweep)
    if sweep.get("margin_sweep"):
        sweep["margin_character"] = exclusion.margin_characterise(
            sweep, adcs.pointing_margin_deg(cfg))
    baseline = sweep.get("baseline", {})
    if "lost_deg" in baseline and "found_deg" in baseline:
        baseline.update(exclusion.sensitivity(
            sweep, baseline["lost_deg"], baseline["found_deg"]))
    with open(RESULTS_DIR / "summary.json", "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from hs2sim.output import exclusion_plots
    exclusion_plots.heatmaps(sweep, RESULTS_DIR, plt)
    exclusion_plots.margin_curve(sweep, RESULTS_DIR, plt)
    print(f"wrote {RESULTS_DIR / 'exclusion_sweep.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
