#!/usr/bin/env python3
"""Re-render the report and the exclusion figure from ``results/summary.json``.

The simulation is the expensive part; the write-up is not. This exists so
report wording and derived statistics can be iterated on without re-running a
propagation, and so a summary produced by an older build can be re-read by the
current analysis code.

It recomputes anything derived (``exclusion_sweep.character``) rather than
trusting what is stored, so the output matches what a fresh run would produce.

    python regen_report.py

Only the report and the exclusion heatmap are regenerated. The other figures
need the propagated environment, so re-run ``run_analysis.py`` for those.
"""

from __future__ import annotations

import json

from hs2sim import exclusion, report
from hs2sim.config import MissionConfig, RESULTS_DIR


def main() -> int:
    with open(RESULTS_DIR / "summary.json", "r", encoding="utf-8") as handle:
        results = json.load(handle)

    cfg = MissionConfig()

    sweep = results.get("exclusion_sweep")
    if sweep is not None:
        sweep["character"] = exclusion.characterise(sweep)
        baseline = sweep.get("baseline", {})
        if "lost_deg" in baseline and "found_deg" in baseline:
            baseline.update(exclusion.sensitivity(
                sweep, baseline["lost_deg"], baseline["found_deg"]))
        with open(RESULTS_DIR / "summary.json", "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2)

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from hs2sim import plots
        plots._exclusion_heatmaps(sweep, RESULTS_DIR, plt)
        print(f"wrote {RESULTS_DIR / 'exclusion_sweep.png'}")

    report.write_report(cfg, results, RESULTS_DIR / "report.md")
    print(f"wrote {RESULTS_DIR / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
