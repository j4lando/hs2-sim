# The interactive mission timeline

`results/mission_dashboard.html` — written by `run_analysis.py` alongside the
PNGs. One self-contained file: open it from disk, no server and no network.

## What it draws

A **geometry selector**, an **orbit scrubber** (slider, `‹` `›`, or the arrow
keys), and a stack of charts showing that one orbit. Every chart shares the
same x axis — minutes since the ascending node — so the same instant sits at
the same place in all of them, and hovering any chart drops a cursor through
all of them with a tooltip carrying every value at that moment.

**Whole mission** at the top is one bar per orbit spanning its SOC range, with
the current orbit highlighted. Click a bar to jump to it.

**Stat tiles** for the selected orbit: minimum SOC, images collected,
downlinked MB, eclipse minutes, the fraction of the orbit spent in experiment
and in slew, and the on-board store at end of run.

The charts, one measure each — no chart carries two y scales:

- **Power (W)** — generation, the load the flown mode draws, and the balance
  the battery sees.
- **State of charge (%)** — against the mode-entry thresholds the run was
  scheduled on, from `hs2sim/energy.py`.
- **On-board image store (GB)** — images the payload has written and never
  downlinked. The axis follows the data rather than the capacity line: the
  store runs at a fraction of a percent of capacity, so including capacity in
  the range would flatten the curve onto the axis. The note states both
  figures, and the capacity line is drawn only when it is near the data.
- **Downlink backlog (MB)** — data queued for the next contact, and cumulative
  bytes sent.
- **Achievable link rate (kbit/s)** — what the budget closes at the current
  range; zero when no station is up.
- **Mode** — the flown mode as a colour band, the same strip that sits under
  every chart above, on the same encoding the PNG timeline uses.

Eclipse is a shaded band behind every chart.

## How the data gets there

Each orbit is resampled onto one common grid of 220 points spanning a nominal
orbit. That is what lets the charts share an x axis, and it keeps the page to a
couple of MB rather than the tens the raw 5 s history would cost. Samples
outside an orbit's real span come back as gaps rather than interpolated values
— the partial orbits at either end of the run genuinely were not propagated
there, and drawing a line across would invent a vehicle.
