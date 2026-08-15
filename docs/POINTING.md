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

## Result

At the production 15 s step, images per day:

| | before | after |
|---|---|---|
| A_2panel_90 | 554 | 649 |
| B_3panel_90 | 4,734 | 5,995 |
| C_2panel_135_plus_body | 7,178 | **14,338** |

C now flies 41.5 % of the mission in experiment mode against a 50.6 % ceiling —
**82 % of the available pointing opportunity** — with slew down from 33 % to
12 % of the time and 45 slews a day instead of 118. It beats B by 2.4×, which is
the ordering its array power implies.

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
