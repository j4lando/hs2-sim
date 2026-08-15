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

## What to read off it

The number that matters is not how full the disc is — on a run of a few days it
is a fraction of a percent — but **whether the unprocessed population is
growing**, which the chart's note states directly. A backlog growing at *N*
frames a day divides 195,312 frames of capacity into the time before imaging
has to stop. That is the constraint the reduction cadence really imposes, and
it arrives long before the flash does.
