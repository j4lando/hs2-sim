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

**Mission totals**, under it and independent of which orbit is selected:
observing time for the whole run and per day, experiments and images for the
whole run, the median observation length, frames reduced on board, frames
purged, the reduction backlog still waiting at the end, and the peak the store
reached. Time and counts are both there because the payload cadence is a free
parameter — the counts scale with it and the observing time does not.

**Stat tiles** for the selected orbit: minimum SOC, observing minutes, images
this orbit, images to date against the mission total, downlinked MB, eclipse
minutes, and the fraction of the orbit spent in experiment and in slew.

**Flight view** is the [Vizard](VIZARD.md) scene rebuilt in the page — see
below.

The charts, one measure each — no chart carries two y scales:

- **Power (W)** — generation, the load the flown mode draws, and the balance
  the battery sees.
- **State of charge (%)** — against the mode-entry thresholds the run was
  scheduled on, from `hs2sim/energy.py`.
- **On-board image store (GB)** — three curves, not one: the total resident,
  the part awaiting reduction, and the part reduced and awaiting its 48-hour
  purge. Frames never leave over the link, so what governs this is the OBC's
  reduction cadence against the capture rate — see [IMAGE_STORE.md](IMAGE_STORE.md).
  The axis follows the data rather than the capacity line, because the store
  runs at a fraction of a percent of capacity and including it would flatten
  the curves onto the axis; the note states both figures and whether the
  reduction backlog is growing, and the capacity line is drawn only when it is
  near the data.
- **Downlink backlog (MB)** — data queued for the next contact, and cumulative
  bytes sent.
- **Achievable link rate (kbit/s)** — what the budget closes at the current
  range; zero when no station is up.
- **Mode** — the flown mode as a colour band, the same strip that sits under
  every chart above, on the same encoding the PNG timeline uses.

Eclipse is a shaded band behind every chart.

## The flight view

`hs2sim/output/globe.py`. The same scene `output/vizard.py` exports — Earth
turning under the orbit, the terminator, the Leaf Space sites, the vehicle
flying the attitude the scheduler chose — drawn into the page instead of into
Vizard, so it sits next to the charts. Vizard proper is still the better tool
and [VIZARD.md](VIZARD.md) still applies; this is the version that needs
nothing installed.

It is a hand-rolled orthographic projection onto a 2D canvas: no WebGL, no
libraries, so the page stays one file that opens from disk. Orthographic on
purpose — the orbit stays a true ellipse on screen, so what the eye measures
off the picture is what the simulation computed.

Drawn per frame: the body triad (**+x** FOUND, **+y**, **+z** LOST and star
tracker), FOUND's line of sight out to where it meets the Earth, the link to
whichever station is up, and the orbit track split into the part in front of
the globe and the part behind it. The vehicle and the Sun marker are drawn
either side of the Earth according to which side they are on, so the globe
occludes them when it should.

**Play** walks the orbit and rolls into the next one at the end; drag to orbit
the camera, scroll to zoom, **Reset view** returns to a viewpoint derived from
the orbit plane itself. Hovering any chart drives the scene to that instant, so
the cursor and the picture always agree.

The scene is sampled at 72 points per orbit rather than the charts' 220 —
attitude is nine numbers a sample, and this is a view rather than a
measurement. Positions, Sun directions and the planet rotation are shared
across geometries because they are properties of the orbit; only the attitude
differs.

## How the data gets there

Each orbit is resampled onto one common grid of 220 points spanning a nominal
orbit. That is what lets the charts share an x axis, and it keeps the page to a
couple of MB rather than the tens the raw 5 s history would cost. Samples
outside an orbit's real span come back as gaps rather than interpolated values
— the partial orbits at either end of the run genuinely were not propagated
there, and drawing a line across would invent a vehicle.
