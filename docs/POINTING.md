# Where the images actually go

Why one array geometry out-images another, what the camera exclusion angles buy,
and why the daily image count used to swing by a factor of several.

All the numbers below come from the production code path — `solve_experiment_pointing`
then `conops.simulate` — on an analytic ISS-like orbit (415 km, 51.64°) with J2
nodal regression and a Sun moving along the ecliptic, at the 15 s step the real
run uses. Basilisk was not available in the environment they were measured in,
so treat them as the shape of the effect rather than flight numbers, and
regenerate `results/` to get the real ones.

## Feasibility is the same for every geometry

The first thing to be clear about: **whether a legal experiment attitude exists
does not depend on the solar array.** It is set by the four keep-outs in
`hs2sim/geometry.py`, which involve the cameras, the Earth and the Sun and
nothing else. Measured, all three geometries sit at 50.6 % feasible to three
figures.

So a geometry cannot win by having more opportunity. It can only win by
*converting* more of the opportunity it shares, and that is a question about
power and about slewing.

## The gap between legal and flown

Feasible windows are long — median 46 min, against 46 min gaps. The vehicle was
capturing a fraction of them:

| | legal | flown as experiment | in slew |
|---|---|---|---|
| A_2panel_90 | 50.2 % | 1.6 % | 13.5 % |
| B_3panel_90 | 50.2 % | 13.7 % | 43.9 % |
| C_2panel_135_plus_body | 50.2 % | 20.8 % | 33.0 % |

C at 118 slews a day, one every twelve minutes, with EXPERIMENT runs lasting a
median of three minutes inside a 46-minute window. Something was ending the
observation over and over.

Two things were, and neither is the vehicle.

### 1. The plan chased the power optimum across the Earth

Among legal attitudes the solver picked the one giving the most array power,
using continuity only to break ties *within* the near-optimal set. That fails in
two ways at once:

- As the vehicle moves, the power optimum itself crosses to the other side of
  the Earth, and the whole near-optimal set crosses with it — so the "nearest"
  member of that set is still most of a turn away.
- A constrained optimum sits **on** a constraint boundary. The attitude picked
  for its power is the one about to go illegal.

Measured: the commanded attitude moved more than the scheduler's 5° slew
threshold on **28 % of consecutive samples**, sometimes by 180°.

A magnetorquer-only 3U needs minutes to turn. A plan that repoints every couple
of minutes is one the vehicle can only ever be slewing toward.

The selector now applies two filters before power decides — *reachable* (within
the slew threshold of the attitude already planned, so the scheduler charges it
as a tracking rate rather than a fresh manoeuvre) and *durable* (far enough
inside every keep-out to still be legal a minute from now). Neither filter is
allowed to empty the candidate set; if nothing is both, the requirement is
dropped in that order and a genuine repoint is planned to the best-powered
durable attitude, nearest first, so a forced turn is at least a short one.

**Feasibility is untouched by any of this** — every candidate considered has
already passed all four keep-outs. Only the choice among legal attitudes
changes, and there is a test asserting exactly that.

### 2. The search grid was coarser than a tracking step

The headline run searched 48 limb azimuths: a 7.5° step, against a 5° slew
threshold. So when the held attitude went illegal, the *nearest legal
neighbour on the grid* was already further away than a slew threshold, and got
charged as a manoeuvre. Those slews are an artefact of the search, not of the
spacecraft.

At 96 azimuths the step is 3.8°, inside the threshold, and the plan can follow
the limb continuously. Feasibility barely moves between 24 and 144 azimuths
(under one point), which is exactly why this was easy to miss — the quantity the
grid is nominally chosen for is insensitive to it, and the image count is not.

The two effects are independent; isolated at a 30 s step:

| | A | B | C |
|---|---|---|---|
| grid 24, old selector | 552 | 2,429 | 5,138 |
| grid 96, old selector | 912 | 4,181 | 7,051 |
| grid 96, new selector | 413 | 4,078 | **11,338** |

## Entering and leaving an observation are different decisions

A third thing was ending observations early: the SOC test was the same on the
way in and the way out. Starting a science block needs the whole worst-case
block funded up front — that is what the 84 % entry threshold is for — but
*staying* in one only needs enough charge left to afford a contact and the
recovery from it, which is exactly what the 54 % standby threshold already
means. With one level doing both jobs the scheduler chattered on it: drop out,
turn to the Sun, charge a few tenths of a percent, turn back, and pay two
multi-minute slews for a minute of imaging.

Experiment mode now enters at the experiment threshold and leaves at the
standby one. Isolated at 0.2 Hz over 3 days:

| | without hysteresis | with hysteresis |
|---|---|---|
| A_2panel_90 | 1.8 %, 612 img/day, 33 slews/day | 1.7 %, 602, 30 |
| B_3panel_90 | 15.1 %, 5,234 img/day, 75 slews/day | **20.0 %, 6,922, 59** |
| C_2panel_135_plus_body | 41.1 %, 14,194 img/day, 49 slews/day | 41.1 %, 14,194, 49 |

It helps precisely the geometry that was chattering. B's mean SOC sits right on
the entry level, so B was crossing it constantly — it gains 32 % more images and
sheds a fifth of its slews. C never approaches the level, so the band is never
consulted and C is unchanged to the digit; A is gated on *entry*, spending most
of its time below the threshold, so hysteresis cannot help it. Dropping out at
the standby level is safe by construction, because that level is the safe
reserve plus a whole worst-case contact.

The image store gate needed the same treatment, for the same reason — see
[IMAGE_STORE.md](IMAGE_STORE.md).

## Three gates that delete a manoeuvre rather than shorten it

Every remaining slew was censused by what it was for and how long its
destination was then held. One pattern accounted for nearly all the waste:
**manoeuvres whose destination did not outlast the manoeuvre.** Repoints inside
a science window turned for 5.7 min and then held the new attitude for 1.0 min;
repoints for a contact turned for 3.2 min and held for 0.2 min. Every one of
them was pure loss.

Three gates, all of them cheap, all of them reading quantities the ephemeris
already knows:

1. **Do not turn for a contact that does not need turning for.** The link
   closes edge-on by 16.8 dB, so the repoint buys rate the mission has no use
   for — see [LINK_BUDGET.md](LINK_BUDGET.md). This deleted every comms
   manoeuvre.
2. **Do not begin a manoeuvre whose reason expires before it ends.** After
   pricing the slew against the real field, the scheduler asks how long the
   destination stays valid at the arrival time; if that is less than the turn
   itself, it declines and holds sun-pointing instead. For a contact, validity
   is how long the pass still needs pointing. For science it is *not* simply
   whether a legal attitude exists — feasibility can hold for a whole 45-minute
   window while the planned attitude inside it jumps every couple of minutes —
   so the window is cut wherever the plan itself steps by more than a tracking
   rate. What is left is how long that particular attitude survives.
3. **Reaching the entry level arms science for the rest of the orbit** (below).

Declined manoeuvres are counted as `slews_skipped`, so the gate cannot hide how
often it fires. The overrun guard that abandons a diverging slew is still
there behind it: the gate refuses what is foreseeably hopeless, the guard
catches what only reveals itself once under way, and both are tested.

Effect on the `expt->expt` churn, over 3 days:

| | before the gates | after |
|---|---|---|
| A_2panel_90 | 8 repoints, 42.5 min turning, held 0.8 min each | 1 |
| B_3panel_90 | 24 repoints, 131 min turning, held 1.0 min each | 3 |
| C_2panel_135_plus_body | 2 | 1 |

## Result

At the production 15 s step and the 0.2 Hz the rate sweep was built around,
images per day:

| | before | after |
|---|---|---|
| A_2panel_90 | 554 | 649 |
| B_3panel_90 | 4,734 | 5,995 |
| C_2panel_135_plus_body | 7,178 | **14,338** |

C now flies 41.5 % of the mission in experiment mode against a 50.6 % ceiling —
**82 % of the available pointing opportunity** — with slew down from 33 % to
12 % of the time and 45 slews a day instead of 118. It beats B by 2.4×, which is
the ordering its array power implies.

The configured cadence is now **0.5 Hz** (`analysis.payload_rate_hz`), where the
same 3-day run gives A 1,950, B 16,305 and C 33,695 images a day. Observing time
barely moves with the rate — C goes 41.1 % to 39.0 %, the payload drawing a
little more — which is why the summary now reports **time on target beside the
counts**: `experiment_hours_total`, `experiment_min_per_day`, and the median and
longest observation. The counts scale with whatever cadence the payload is run
at; the duration is what the CONOPS actually buys.

At 0.5 Hz the binding constraint stops being pointing or power and becomes the
on-board reduction cadence: C fills its 128 GB of flash on about day 7. That is
in [IMAGE_STORE.md](IMAGE_STORE.md).

### With all the gates in, at 0.5 Hz over 3 days

| geometry | peak W | observing | median block | images/day | slews/day | mean SOC |
|---|---|---|---|---|---|---|
| A_2panel_90 | 14.8 | 8.9 % | 22.8 min | 7,730 | 15 | 80.2 % |
| B_3panel_90 | 22.0 | 26.9 % | 26.8 min | 23,245 | 40 | 86.7 % |
| **C_2panel_135_plus_body** | 22.3 | **43.3 %** | 28.2 min | **37,420** | 37 | 97.6 % |
| D_2panel_135_minus_x* | 14.8 | 1.0 % | 12.2 min | 895 | 2 | 41.2 % |
| E_2panel_135_no_body | 14.8 | 16.5 % | 27.5 min | 14,260 | 21 | 81.1 % |

\* D's simulated columns above predate the panel-dihedral correction below
(90° between panels vs. the corrected 135°) and need a fresh
`run_analysis.py` pass; `peak_total_w` is unaffected.

The median observation is now 23–28 minutes against a 46-minute window, where
it started at 2.5–4 minutes. C converts 85 % of the pointing opportunity it
shares with every other geometry.

## What the two extra geometries show

**D — a single deployable wing on the -x face, folded to a 135° dihedral
between its 2 panels.** It is one mechanism, not two: one hinge/motor
deploys the whole wing, which then presents two panel faces 135° apart
(each 22.5° off the -x centerline) rather than one flat surface. Modelled
honestly on two different normals, the V can never put both panels at full
cosine at once, so its effective peak is 2 x 7.4 x cos 22.5° = 13.7 W against
A's 14.8 W from a single flat wing — closer to A than the shallower fold this
replaces, since 135° is a much gentler V than 90°. A dihedral buys tolerance
to Sun direction, and a vehicle that can point at the Sun has no use for
tolerance to Sun direction. It would be the right shape for a spinner or a
vehicle with no attitude control, and it is the wrong shape for this one.

**E — geometry C's wing without the body-mounted panel.** 14,260 images a day
against C's 37,420, so the 7.5 W body panel — a third more peak power — is
worth **2.6x the science**. That is the SOC entry threshold amplifying a modest
power difference into a large one, the same non-linearity that makes A and B so
sensitive.

E is also the cleanest available measurement of something else. A and E are the
same panel: one flat 14.8 W surface, differing only in which way it faces on
the body. In standby that is invisible, because the vehicle turns to face the
Sun either way. In *experiment* mode it is not, because the attitude is pinned
by the cameras: A's normal is -x, exactly opposite FOUND's boresight, so
whenever FOUND is on the limb the array is pointed as far from useful as it can
be. E's normal sits 45° off, and gets **nearly twice the images from the same
panel**. Where the array sits relative to the payload boresight is worth about
as much as adding a third panel.

## Why the daily count used to swing so wildly

Not the inclination, and not the beta angle.

Feasibility was measured across the **whole ±75° beta range** a 51.64° orbit
reaches, varying both RAAN and solar longitude:

```
beta   -74.8   -44.5   -12.1    +2.2   +25.4   +51.7   +74.8
feas%   54.7    51.5    50.3    50.8    50.6    49.4    51.8
```

**49.4 % to 54.7 % — it never collapses.** The mechanism is a near-exact
cancellation: at high |beta| the orbit is fully sunlit, so rejections for "no
sunlit limb" fall from 41 % to 3 %, while FOUND's Sun keep-out rises from 8 % to
45 %. The opportunity is essentially constant all year.

What does swing is **whether the battery clears the experiment-entry
threshold**, which the 200 % margin puts at 83.6 % SOC. That is a cliff, and a
geometry whose mean SOC sits near it produces a chaotic image count:

| | mean SOC | vs 83.6 % threshold | daily images |
|---|---|---|---|
| A_2panel_90 | 80.8 % | **below** | 270 – 1,002 |
| B_3panel_90 | 84.4 % | on it | 1,812 – 8,370 |
| C_2panel_135_plus_body | 97.8 % | clear | 14,052 – 14,850 (±3 %) |

A images only during brief excursions above a threshold it normally sits under,
so its daily count is decided by a few tenths of a percent of charge — that is
the "600 one day, 0 the next" behaviour. C sits clear of the gate and, with the
slew fixes above, is now steady to ±3 % day to day.

So the variance is a **power-threshold** effect, not an orbital-geometry one. If
a steadier cadence matters more than the reserve, `--soc-margin` is the knob;
lowering it moves the threshold down and takes the cliff out of A's and B's
operating range.

## What the exclusion angles buy

Swept one at a time on the real solver, at 96 azimuths:

**FOUND's Sun keep-out (+x, 70°) is the only one that binds.**

| FOUND Sun keep-out | 70° (baseline) | 60° | 50° | 40° | 30° |
|---|---|---|---|---|---|
| feasible | 50.9 % | 52.3 % | 54.2 % | 55.7 % | 56.6 % |

Relaxing it all the way to 30° recovers 5.7 points of the 7.6 that it costs.

**The +z Sun keep-out (LOST and star tracker, 40°) does nothing at all.**
Anywhere from 20° to 60° feasibility stays at 50.9 %, and the `no legal roll`
rejection is 0.0 % throughout: the roll freedom about the FOUND boresight always
finds somewhere legal to put +z. Tightening this cone is free; loosening it buys
nothing.

**The +z Earth keep-out (40°) has 30° of slack.** It first bites at 70° (0.5 %
rejected) and only hurts at 80° (6.7 %), which is the cliff `mission.yaml`
describes — at 90° there is no legal roll at all, because pointing FOUND at the
limb fixes +x about 70° off nadir and +z is perpendicular to it.

The ceiling on all of this is about **58 %**, even with a 30° FOUND cone,
because roughly 41 % of the time there is no sunlit limb to look at. That is
eclipse plus dark-limb geometry, and no optical requirement touches it.

The existing `--exclusion-sweep` explores the same trade over a 2D grid and
splits the +z cone into its Sun and Earth halves; read it for the shape, not for
absolute image counts, since it runs at a coarser search grid than the headline
(see the note in `config/mission.yaml`).
