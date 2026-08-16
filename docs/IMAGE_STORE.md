# The image store

`hs2sim/storage.py`, driven by the scheduler in `hs2sim/conops.py` and drawn on
the **On-board image store** chart of
[the dashboard](DASHBOARD.md).

Imagery is the only thing on HS-2 that is produced far faster than it leaves.
An experiment's numerical product is 122 bytes and goes down the S-band link;
the two frames it came from are 640 kB each and never do. So the frames sit on
the payload's 128 GB of flash, and what happens to them there is its own model.

## The three populations

At any instant the store holds

| | what it is |
|---|---|
| **unprocessed** | captured, waiting its turn through the OBC's reduction pipeline |
| **processed** | reduced, waiting out its retention before deletion |
| *(purged)* | gone |

and the chart draws all three, because the total alone hides which of the two
is growing.

## The two rates

**Reduction** runs at a fixed cadence: one FOUND (Earth) frame and one LOST
(star) frame every `payload.processing_period_s` — 3 minutes, so 960 frames a
day. It is a queue being worked off on a clock, not a per-image cost, so it
does not speed up when the backlog grows.

**Retention**: reducing a frame does not free its space. A processed frame is
purged `payload.processed_retention_h` later — 48 hours. Deletion is scheduled
rather than aged: a frame processed at step *i* is purged at step
*i + retention*, so the history of what was processed when *is* the deletion
schedule.

Reduction is paused in **safe** mode, where only survival loads run. The purge
is not — it is a clock, and it keeps running.

## Why this is in the scheduler and not a report

Because the capture rate can exceed the reduction cadence, and it does: at
0.2 Hz the payload can generate frames faster than 960/day by a wide margin, so
the unprocessed population grows at the difference between the two rates. That
is a real operational limit and it needs somewhere to bite.

So `ImageStore` is stepped by `conops.simulate` inside its own loop, and the
scheduler will not enter experiment mode with no room to write
(`ImageStore.has_room`). Turning to the limb to write frames there is nowhere
to put would be worse than not turning at all. A model that let the store run
past 128 GB would be showing a mission taking images it could not store.

`offer()` returns how much imagery was actually taken, so a capture that
straddles the moment the store fills is truncated rather than granted;
`dropped_images` counts what was refused, and the run logs a warning if it is
ever non-zero.

The gate has hysteresis, for the same reason experiment mode's SOC gate does.
A full store does not stay full: processed frames age out of retention and free
a trickle of space. A gate that let the vehicle start observing on a trickle
would have it turn to the limb, fill that space in seconds and turn back —
paying two multi-minute slews for a fraction of a minute of imaging. Measured
before the fix, at 0.5 Hz on geometry C, the median observation collapsed to
**0.8 minutes** and slews rose to **82 a day**. So starting an observation
requires room to sustain one for at least as long as the worst-case manoeuvre
into it takes (`EnergyBudget.worst_slew_s`, from the same budget the SOC
thresholds come from), while an observation already under way runs until the
store is genuinely full.

## What to read off it

The number that matters is not how full the disc is at any instant but
**whether the unprocessed population is growing**, which the chart's note states
directly. A backlog growing at *N* frames a day divides 195,312 frames of
capacity into the time before imaging has to stop.

At the configured 0.5 Hz that is not a distant limit. Measured over 8 days:

| | backlog growth | store after 8 days |
|---|---|---|
| A_2panel_90 | +640 frames/day | 4.8 GB |
| B_3panel_90 | +15,460 frames/day | 82.3 GB |
| C_2panel_135_plus_body | +24,000 frames/day | **full on day 7** |

The reduction cadence gets through 960 frames a day. Geometry C captures
between twenty and forty times that, so the 128 GB is not really 128 GB of
margin — it is about a week of buffer, after which the mission is limited by
how fast the OBC can reduce rather than by pointing or power. Lowering
`analysis.payload_rate_hz`, raising the reduction cadence, or shortening the
48-hour retention are the three levers, and the first is the only free one.
