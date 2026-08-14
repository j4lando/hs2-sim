# HS-2 operations simulation results

Propagated with Basilisk for 3.0 days at a 5 s step (47 orbits).

## Orbit and environment

| Quantity | Value |
| --- | --- |
| Mean altitude | 408.3 km |
| Orbit period | 92.75 min |
| Eclipse fraction | 38.9 % |
| Beta angle (mean/min/max) | 6.4 / 0.0 / 12.8 deg |
| Earth angular radius | 70.0 deg |
| Mean field strength | 35583 nT |

## Communications

- **61.3 passes per day** across 15 Leaf Space locations.
- 315 minutes of contact per day; mean pass 5.1 min, longest 6.6 min.
- Deliverable **1032 MB/day** of information (after rate-1/2 FEC).
- Spacecraft EIRP 1.0 dBW against a 12.8 dB/K station.
- Link margin at 10 deg elevation: 24.4 dB at 9.6 kbps, 10.2 dB at 256 kbps.
- With the budget's worst-case -10 dB antenna pointing loss: 17.4 dB at 9.6 kbps.

| Station | Passes/day | Mean duration (min) | Contact (min/day) |
| --- | --- | --- | --- |
| Madrid, Spain | 6.00 | 4.7 | 28.2 |
| Sofia, Bulgaria | 6.00 | 5.3 | 31.8 |
| Lomazzo, Italy | 5.33 | 5.7 | 30.6 |
| Spaceport Nova Scotia | 5.33 | 5.8 | 30.7 |
| Santa Maria, Azores | 4.67 | 4.8 | 22.2 |
| Vancouver, BC, Canada | 4.67 | 6.0 | 28.2 |
| Auckland, New Zealand | 4.67 | 4.8 | 22.2 |
| Dublin, Ireland | 4.33 | 5.5 | 23.6 |
| Vilnius, Lithuania | 4.00 | 5.3 | 21.3 |
| Perth, W. Australia | 4.00 | 4.8 | 19.1 |
| Adelaide, S. Australia | 4.00 | 5.0 | 20.2 |
| Shetland, Scotland | 3.00 | 3.1 | 9.3 |
| Colombo, Sri Lanka | 2.67 | 5.1 | 13.6 |
| Alcantara, Brazil | 2.67 | 5.2 | 13.9 |
| Reykjavik, Iceland | 0.00 | 0.0 | 0.0 |

## Power draw by mode

Rebuilt from peak power x quantity x duty cycle.

| Mode | Load (W) |
| --- | --- |
| safe | 5.94 |
| detumble | 7.10 |
| standby | 6.97 |
| slew | 11.59 |
| experiment | 11.32 |
| downlink | 20.61 |

Heater duty cycle sensitivity (the heater number is not trusted):

| Heater duty | Experiment mode load (W) |
| --- | --- |
| 0 % | 9.72 |
| 15 % | 10.52 |
| 30 % | 11.32 |
| 50 % | 12.39 |

## Solar array geometry trade

| Geometry | Peak (W) | Standby orbit-avg (W) | Capacity factor | Experiment-mode avg (W) |
| --- | --- | --- | --- | --- |
| A_2panel_90 | 14.8 | 8.24 | 0.557 | 4.32 |
| B_3panel_90 | 22.0 | 12.25 | 0.557 | 6.42 |
| C_2panel_135_plus_body | 22.3 | 11.57 | 0.519 | 8.93 |

### Per-panel incidence (sun-pointing standby attitude)

| Geometry | Panel | Peak (W) | Mean incidence | Illuminated | Mean output (W) |
| --- | --- | --- | --- | --- | --- |
| A_2panel_90 | deployable | 14.8 | 1.9 deg | 100 % | 9.04 |
| B_3panel_90 | deployable | 22.0 | 1.9 deg | 100 % | 13.44 |
| C_2panel_135_plus_body | deployable | 14.8 | 14.9 deg | 100 % | 8.74 |
| C_2panel_135_plus_body | body_plus_y | 7.5 | 30.3 deg | 100 % | 3.96 |

### Experiment-mode pointing feasibility

| Geometry | Feasible | No sunlit limb | Sun in FOUND | No legal roll |
| --- | --- | --- | --- | --- |
| A_2panel_90 | 50.1 % | 41.7 % | 8.2 % | 0.0 % |
| B_3panel_90 | 50.1 % | 41.7 % | 8.2 % | 0.0 % |
| C_2panel_135_plus_body | 50.1 % | 41.7 % | 8.2 % | 0.0 % |

## Camera exclusion-angle trade

Both keep-out cones were swept and the whole pipeline re-run at each grid point -- pointing re-solved on a 32x32 azimuth/roll search, then the mode scheduler run at 0.20 Hz on geometry `C_2panel_135_plus_body`. Orbit, array, cadence and ground stations are identical across the grid; only the cones move.

`LOST` moves the +z keep-out against **both** Sun and Earth (the requirement quotes one angle for both, and the star tracker shares that face). `FOUND` moves FOUND's Sun keep-out only -- its 74 deg field of view is an optical property and does not move. The baseline cell is in **bold**.

**Sanity check.** The sweep re-solves pointing on a coarser azimuth/roll grid than the headline run, so the baseline cell has to reproduce the headline result or the whole sweep is biased. It does: 49.3 % feasible here against 50.1 % at 48x48. The coarse grid is not losing legal attitudes. Realised images differ by more (5,217 against 5,522 per day), which is the scheduler sensitivity discussed under table 3, not a feasibility difference.

### 1. Fraction of the timeline with a legal experiment attitude

This is the constraint's own effect, and it is the number to trade on: a deterministic function of the two cone angles, with no scheduler behaviour mixed in.

| Feasible (%) | FOUND 50 deg | FOUND 60 deg | FOUND 70 deg | FOUND 80 deg | FOUND 90 deg |
| --- | --- | --- | --- | --- | --- |
| **LOST 20 deg** | 53.5 | 51.5 | 49.3 | 48.1 | 46.9 |
| **LOST 30 deg** | 53.5 | 51.5 | 49.3 | 48.1 | 46.9 |
| **LOST 40 deg** | 53.5 | 51.5 | **49.3** | 48.1 | 46.9 |
| **LOST 50 deg** | 53.5 | 51.5 | 49.3 | 48.1 | 46.9 |
| **LOST 60 deg** | 47.5 | 45.6 | 43.4 | 42.1 | 41.0 |
| **LOST 70 deg** | 35.1 | 33.1 | 30.9 | 29.7 | 28.5 |
| **LOST 80 deg** | 23.8 | 21.9 | 19.7 | 18.5 | 17.3 |

### 2. Image ceiling at this cadence

The same matrix in mission units: feasible time x 0.20 Hz x 2 cameras, i.e. what the vehicle would collect if every legal opportunity were used.

| Ceiling (images/day) | FOUND 50 deg | FOUND 60 deg | FOUND 70 deg | FOUND 80 deg | FOUND 90 deg |
| --- | --- | --- | --- | --- | --- |
| **LOST 20 deg** | 18,478 | 17,796 | 17,047 | 16,617 | 16,218 |
| **LOST 30 deg** | 18,478 | 17,796 | 17,047 | 16,617 | 16,218 |
| **LOST 40 deg** | 18,478 | 17,796 | **17,047** | 16,617 | 16,218 |
| **LOST 50 deg** | 18,478 | 17,796 | 17,047 | 16,617 | 16,218 |
| **LOST 60 deg** | 16,427 | 15,746 | 14,996 | 14,566 | 14,167 |
| **LOST 70 deg** | 12,120 | 11,439 | 10,690 | 10,260 | 9,860 |
| **LOST 80 deg** | 8,239 | 7,558 | 6,809 | 6,379 | 5,979 |

### 3. Images actually collected

What survives after slews, downlink passes and battery holds take their share. Roughly a third of the ceiling, because the vehicle spends about half its time slewing.

| Images/day | FOUND 50 deg | FOUND 60 deg | FOUND 70 deg | FOUND 80 deg | FOUND 90 deg |
| --- | --- | --- | --- | --- | --- |
| **LOST 20 deg** | 5,826 | 5,532 | 5,280 | 5,351 | 5,173 |
| **LOST 30 deg** | 5,862 | 5,649 | 5,309 | 4,832 | 4,689 |
| **LOST 40 deg** | 5,725 | 5,472 | **5,217** | 4,626 | 4,505 |
| **LOST 50 deg** | 6,205 | 5,757 | 5,417 | 4,883 | 4,705 |
| **LOST 60 deg** | 6,123 | 5,759 | 5,243 | 4,953 | 4,876 |
| **LOST 70 deg** | 3,652 | 4,021 | 3,743 | 3,611 | 3,507 |
| **LOST 80 deg** | 2,459 | 2,378 | 2,037 | 2,045 | 1,883 |

**Read table 3 with care.** Several cells in it share an *identical* feasibility -- the +z cone does nothing at all over part of its range -- yet their realised image counts differ by up to 725 images/day (15 %). That spread is not the cone doing anything. Changing a keep-out changes which rolls are legal, which changes the attitude the solver picks among equally legal options, which changes where the large repoints land; with ~50 % of the timeline in slew, that is a big lever and it is essentially chaotic. Treat 725 images/day as the noise floor of table 3, and trade on tables 1 and 2 instead.

### 4. Energy margin (W)

A looser cone is not free: more experiment time means less sun-pointing, and the margin is what pays for it.

| Margin (W) | FOUND 50 deg | FOUND 60 deg | FOUND 70 deg | FOUND 80 deg | FOUND 90 deg |
| --- | --- | --- | --- | --- | --- |
| **LOST 20 deg** | +0.82 | +0.93 | +1.14 | +1.19 | +1.33 |
| **LOST 30 deg** | +0.76 | +0.97 | +1.28 | +1.21 | +1.41 |
| **LOST 40 deg** | +0.71 | +0.93 | **+1.34** | +1.36 | +1.60 |
| **LOST 50 deg** | +0.65 | +0.87 | +1.22 | +1.19 | +1.40 |
| **LOST 60 deg** | +0.77 | +1.03 | +1.30 | +1.34 | +1.49 |
| **LOST 70 deg** | +1.15 | +1.36 | +1.68 | +1.78 | +1.85 |
| **LOST 80 deg** | +1.82 | +2.12 | +2.48 | +2.58 | +2.78 |

### Sensitivity at the baseline

One-sided differences to the neighbouring grid points, on the ceiling of table 2. The grid step is 10 deg, so these are the finest slopes the sweep can honestly support.

| Change | Images/day gained (+) or lost (-) | Per degree |
| --- | --- | --- |
| Loosen LOST by 10 deg (smaller +z keep-out) | +0 | +0 |
| Tighten LOST by 10 deg (larger +z keep-out) | +0 | +0 |
| Loosen FOUND by 10 deg (smaller Sun keep-out) | +749 | +75 |
| Tighten FOUND by 10 deg (larger Sun keep-out) | -430 | -43 |

### What the sweep says

**The trade is sharply asymmetric: there is little to win and a lot to lose.** Over the full grid, feasible time runs from 17.3 % (LOST 80 deg / FOUND 90 deg) to 53.5 % (LOST 20 / FOUND 50), against 49.3 % at the baseline. Relaxing both cones as far as the grid goes is worth only +8 %, because the dominant loss is not stray light at all; tightening them as far as the grid goes costs -65 %. The baseline sits close to the good end already, so the engineering question is not how to gain science by loosening -- it is how much margin exists before the geometry starts taking science away.

**The +z keep-out has slack, and the sweep says how much.** Feasibility is identical for every LOST value up to **50 deg** -- the rows of table 1 are the same to within rounding. The baseline is 40 deg, so the star tracker and LOST could give up 10 deg of keep-out at zero cost in science. The reason is that the roll about +x is a free parameter: fixing FOUND on the limb leaves a whole circle of +z directions to choose from, and up to 50 deg there is always some arc of it that clears both Earth and Sun. At 60 deg that arc starts to close, which is the knee -- 20 deg above the baseline.

**FOUND's Sun keep-out is the one that costs.** Averaged over the swept range, every degree of FOUND exclusion is worth about 0.16 percentage points of feasible time, or roughly 56 images/day per degree at 0.20 Hz. If there is baffle or stray-light work to be done, this is the only axis on which it pays.

That average is not a straight line, though, and the structure matters if you are negotiating a specific number. The price per degree ranges from 0.12 pp/deg over 80-90 deg -- effectively free -- to 0.22 pp/deg over 60-70 deg. The cheap steps are the ones where the excluded solid angle was already pointing at sky the sunlit limb never occupies.

### Why the rejected samples are rejected

Feasibility alone does not say *which* constraint bit, and on this grid the answer changes. Percentages of the whole timeline, at the baseline FOUND = 70 deg column.

| LOST | No sunlit limb | Sun in FOUND | No legal roll |
| --- | --- | --- | --- |
| 20 deg | 41.7 % | 9.0 % | 0.0 % |
| 30 deg | 41.7 % | 9.0 % | 0.0 % |
| 40 deg | 41.7 % | 9.0 % | 0.0 % |
| 50 deg | 41.7 % | 9.0 % | 0.0 % |
| 60 deg | 41.7 % | 9.0 % | 5.9 % |
| 70 deg | 41.7 % | 9.0 % | 18.4 % |
| 80 deg | 41.7 % | 9.0 % | 29.6 % |

**The +z cone does eventually bind, and it binds hard.** `No legal roll` is exactly zero over the whole baseline range and then climbs to 29.6 % of the timeline at LOST 80 deg / FOUND 50 deg, overtaking FOUND's Sun keep-out as the dominant rejection from LOST 60 deg upward. Where the wall sits is set by the orbit, not by the instrument: fixing FOUND on the limb puts +x about 70 deg off nadir, and +z is perpendicular to +x, so +z can only reach between 20 and 160 deg from nadir. The Earth keep-out demands more than (70 + LOST) deg of that range, so the roll freedom closes completely at LOST = 90 deg no matter what else is true. The sweep is watching that margin run out.

### Which half of the +z cone is spending it

The requirement quotes one angle covering both Sun and Earth, so the sweep above moves them together. That is faithful to the requirement but not actionable: a baffle or a lens hood buys you the Sun exclusion, and nothing whatsoever buys you the Earth one. Below, each half is moved on its own with the other held at 40 deg, at the baseline FOUND exclusion.

| LOST | Sun half alone | Earth half alone | Both together |
| --- | --- | --- | --- |
| 20 deg | 49.3 % | 49.3 % | 49.3 % |
| 30 deg | 49.3 % | 49.3 % | 49.3 % |
| 40 deg | 49.3 % | 49.3 % | 49.3 % |
| 50 deg | 49.3 % | 49.3 % | 49.3 % |
| 60 deg | 49.3 % | 49.3 % | 43.4 % |
| 70 deg | 48.8 % | 48.9 % | 30.9 % |
| 80 deg | 43.1 % | 43.6 % | 19.7 % |

**Neither half is expensive on its own. The pair is.** At LOST 80 deg, widening only the Sun exclusion leaves 43.1 % feasible and widening only the Earth exclusion leaves 43.6 % -- each costing a few points against the 49.3 % baseline. Move both and it collapses to 19.7 %, far worse than the sum of the parts.

The mechanism is that the two keep-outs exclude *different* arcs of the roll circle. Separately, each leaves a usable arc behind. Together the arcs overlap enough to leave nothing, and the sample is lost. This is the practically useful result of the whole sweep: if the +z keep-out has to grow, growing one half is survivable and growing both is not. It also means a stray-light fix on the Sun side keeps its value only as long as the Earth exclusion stays where it is.

### The pointing-error buffer

Everything above is solved with a buffer on every keep-out, because what the solver returns is a *commanded* attitude and the true boresight is somewhere within the control and knowledge error of it, in an unknown direction. An attitude that puts the Sun exactly on the star tracker's 40 deg boundary is a coin flip, not a legal attitude. So each cone is enforced at `exclusion + margin` and the legal set shrinks from every side.

The tables above use **1.10 deg**. This sub-sweep moves only that buffer, with the cones held at their configured values.

| Buffer (deg) | Feasible | Image ceiling | Images/day | Sun in FOUND | No legal roll |
| --- | --- | --- | --- | --- | --- |
| 0.00 | 49.4 % | 17,074 | 5,163 | 8.9 % | 0.0 % |
| 0.50 | 49.3 % | 17,047 | 5,352 | 9.0 % | 0.0 % |
| **1.10** | **49.3 %** | 17,047 | 5,217 | 9.0 % | 0.0 % |
| 2.00 | 49.3 % | 17,047 | 5,231 | 9.0 % | 0.0 % |
| 3.00 | 49.3 % | 17,047 | 5,143 | 9.0 % | 0.0 % |
| 5.00 | 49.3 % | 17,047 | 4,582 | 9.0 % | 0.0 % |
| 10.00 | 49.1 % | 16,966 | 5,562 | 9.2 % | 0.0 % |
| 11.10 | 48.1 % | 16,617 | 4,883 | 10.2 % | 0.0 % |
| 15.00 | 47.0 % | 16,259 | 4,581 | 11.2 % | 0.0 % |
| 20.00 | 43.1 % | 14,886 | 5,052 | 11.2 % | 4.0 % |
| 21.10 | 41.0 % | 14,167 | 4,876 | 11.4 % | 5.9 % |

**The pointing budget is very nearly free at its current size, and the sweep says exactly how much room there is.** The as-designed 1.10 deg buffer costs 0.08 percentage points of feasible time against a hypothetical perfect pointer, and feasibility is unchanged all the way out to **5 deg**, only starting to move at 10 deg. That is not luck and it is not a modelling artefact: it is the +z slack from the cone sweep, spent on pointing error instead of on keep-out. In other words the vehicle can miss its pointing spec by a factor of 5 before the geometry charges anything at all for it.

Past that the price accelerates hard: 0.40 pp/deg averaged over the whole swept range but 0.52 pp/deg over the upper half. The buffer eats into the roll window from the Earth side and the Sun side at once, which is the superadditive collapse from the previous section arriving by a different route.

**Cross-check.** Padding every keep-out by *m* degrees is the same inequality as moving both cones out by *m*, so a buffer of 21 deg has to reproduce the grid cell at LOST 60 / FOUND 90 deg. It does: 41.0 % against 41.0 %. Across every comparable point the two agree to 0.00 percentage points. The two numbers come from different code paths -- one adds the margin to the angle inside the solver, the other rewrites the config and re-reads it -- so this checks both.

One thing to be clear about: this is a *hard* constraint on feasibility, not a soft pointing requirement. An attitude that cannot hold the buffer is not counted at all, so an ADCS that misses its spec does not blur images here -- it removes observations from the timeline. The flip side is the useful part for ADCS: there is no science argument for tightening the pointing budget below its current 1.10 deg, because the geometry cannot tell the difference.

### The trade at each level of ADCS uncertainty

Attitude uncertainty inflates **every** keep-out at once, so its effect is not something one column of a table can carry. The whole trade is instead re-solved at each level and drawn as its own figure. Compare them side by side; the axes are labelled with the quoted angle and, in brackets, the effective half-angle the geometry actually enforces.

| ADCS uncertainty | Figure | Baseline cell | Effective at baseline | Best cell | Worst cell |
| --- | --- | --- | --- | --- | --- |
| 0.00 deg | `exclusion_sweep_u0.png` | 49.4 % | 40 / 70 deg | 53.5 % | 18.6 % |
| 1.10 deg | `exclusion_sweep.png` | 49.3 % | 41.1 / 71.1 deg | 53.5 % | 17.3 % |
| 5.00 deg | `exclusion_sweep_u5.png` | 49.3 % | 45 / 75 deg | 53.5 % | 11.2 % |
| 10.00 deg | `exclusion_sweep_u10.png` | 49.1 % | 50 / 80 deg | 51.5 % | 0.0 % |
| 20.00 deg | `exclusion_sweep_u20.png` | 43.1 % | 60 / 90 deg | 49.4 % | 0.0 % |

Nothing is drawn at or beyond **37 deg** of uncertainty. That is FOUND's half field of view, and the keep-*in* half of the treatment shrinks the usable field of view to nothing there: no commanded attitude can guarantee the limb is in frame, whatever the keep-outs say. It is a hard ADCS requirement independent of the payload's exclusion angles.

Two things to read off the figures. First, where the effective half-angle passes 90 deg the keep-out cone is **larger than a hemisphere**: the allowed region for that boresight is no longer the sky minus a cap but a cap of half-angle `180 - effective` about the anti-Sun direction, shrinking to a point at 180 deg. At 20 deg of uncertainty the 70 deg quoted FOUND exclusion is already at an effective 90 deg, and the 90 deg column is at 110 deg. Second, the grids do not simply shift: the flat region where the +z cone costs nothing shrinks from the bottom as uncertainty grows, because the uncertainty is spending that same slack.

**What the cones cannot fix.** `No sunlit limb` is the largest rejection over most of the grid and it barely moves (a span of 0.0 percentage points across all 35 cells): it is eclipse and orbital geometry, not stray light. That is the floor the trade runs into, and it is why even the loosest corner of the grid leaves roughly half the timeline unusable for science.

## Surface illumination (thermal inputs)

Flown attitude from the CONOPS scheduler, geometry `A_2panel_90`.

| Face | Area (m^2) | Sunlit | Mean solar (W/m^2) | Albedo | Earth IR | Total | Peak solar | Longest dark (min) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +x | 0.030 | 0 % | 1 | 86 | 83 | 169 | 540 | 1623.3 |
| -x | 0.030 | 61 % | 766 | 7 | 82 | 855 | 1361 | 37.2 |
| +y | 0.030 | 24 % | 70 | 41 | 80 | 191 | 1361 | 87.9 |
| -y | 0.030 | 38 % | 32 | 43 | 84 | 159 | 1361 | 85.2 |
| +z | 0.010 | 23 % | 67 | 27 | 62 | 156 | 1115 | 47.6 |
| -z | 0.010 | 38 % | 27 | 52 | 79 | 158 | 1134 | 84.7 |

Eclipse: 38.9 % of the orbit, longest 36.1 min.

## Single-node temperature

Whole spacecraft treated as one isothermal node (instantaneous internal conduction):

```
C dT/dt = Q_solar + Q_albedo + Q_earthIR + Q_internal - P_electrical - eps*sigma*A*T^4
```

**Where the electrical power goes.** Everything drawn becomes heat except what physically leaves the vehicle:

| Subsystem | Leaves as | Non-heat power | Heat fraction |
| --- | --- | --- | --- |
| COMM (radio TX) | RF wave | 0.80 W | **93.0 %** |
| COMM (radio RX) | nothing | 0 W | 100.0 % |
| ADCS (magnetorquers) | mechanical work | 20.607 nW | **100.0000 %** |
| Everything else | nothing | 0 W | 100.0 % |

The transmitter is the only meaningful exception. Of its 11.44 W input, the link budget's own numbers (2 W at the PA, -3 dB return loss, -1 dB circuit loss) leave only 0.80 W actually radiating away -- so the radio is, thermally, almost a pure heater.

Magnetorquers are resistive coils. The mechanical power they deliver is torque x body rate, which at this vehicle's 12.1 uN m and 0.0974 deg/s is about 20.607 nW -- roughly one part in a billion of their electrical draw. Unlike reaction wheels they store no useful kinetic energy, and the coil's field energy returns to the bus on de-energisation. Treating ADCS as 100 % dissipative is correct to nine decimal places.

| Geometry | Mean | Min | Max | Swing | Time constant | Battery margin (cold/hot) |
| --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 8.7 C | -3.6 C | 20.4 C | 24.0 C | 79 min | +6.4 / +24.6 C |
| B_3panel_90 | 9.0 C | -6.9 C | 26.1 C | 33.0 C | 64 min | +3.1 / +18.9 C |
| C_2panel_135_plus_body | 16.0 C | 0.5 C | 30.7 C | 30.2 C | 73 min | +10.5 / +14.3 C |

Radiating area 0.260 m^2 at an effective emissivity of 0.81; thermal capacitance 5100 J/K. Mean absorbed environmental load 74.7 W against 8.2 W of internal dissipation.

The thermal time constant is comparable to the orbit period, which is why the swing is far smaller than the instantaneous radiative equilibrium would suggest: the vehicle's own mass averages the eclipse cycle. A single-node model cannot see gradients, so the deployed wing will in reality run hotter in sunlight and colder in eclipse than these numbers, and the battery -- usually the most temperature-sensitive item -- sits inside the bus where swings are smaller. Treat this as the bulk average, not a component prediction.

## ADCS: magnetorquer limits

- Dipole per axis: [0.2, 0.2, 0.2] A m^2.
- Field 26086-48048 nT (mean 35583 nT).
- Control torque: mean 12.12 uN m, minimum 7.45 uN m.
- Pointing budget: 1.00 deg control + 0.10 deg knowledge, combined by `sum` = **1.10 deg**. Every experiment-mode keep-out is enforced with that as a buffer, so it is a direct tax on science time -- see the exclusion-angle trade.

Slew time is not one number for a magnetically actuated vehicle. The achievable torque `m x B` always lies in the plane perpendicular to the field, so there is **no** authority about an axis parallel to `B` -- a manoeuvre that has to turn about the field direction cannot start, and has to wait for the geometry to rotate. Each row below is the distribution over 24 eigenaxis directions and 16 start phases, integrating a bang-bang profile through the real field history rather than evaluating a constant-torque formula.

| Slew | Best | Median | 90th pct | Worst | Eigenaxis along B | Constant-torque formula |
| --- | --- | --- | --- | --- | --- | --- |
| 10deg | 0.7 min | 1.4 min | 1.8 min | 4.2 min | 3.3 min | 1.2 min |
| 30deg | 1.1 min | 2.3 min | 3.0 min | 5.7 min | 4.7 min | 2.0 min |
| 60deg | 1.5 min | 3.1 min | 4.3 min | 7.0 min | 6.0 min | 2.8 min |
| 90deg | 1.7 min | 3.8 min | 5.3 min | 10.0 min | 6.8 min | 3.5 min |
| 180deg | 2.6 min | 5.4 min | 7.2 min | 12.0 min | 8.6 min | 4.9 min |

The spread is the finding. A 90 deg repoint takes 3.8 min typically but 10.0 min in the worst geometry, and 6.8 min when the eigenaxis starts along the field. The constant-torque formula says 3.5 min for all of them, which is why it is only shown for comparison: it is close to the median and blind to the tail, and the tail is what breaks a schedule. Nothing is actually unreachable (0 % of sampled manoeuvres failed to complete) -- the field sweeps through a large angle every orbit, so a slew that cannot start now can start a few minutes later.

Disturbance torques: gravity gradient 0.077 uN m, residual dipole 0.178 uN m, aero 0.078 uN m. Authority margin 36.5x on average, 18.90x worst case.

Momentum management needs the torquers energised roughly 2.2 % of each orbit.
Detumble from 10 deg/s: about 0.5 hours.

## Payload throughput

- Compressed image: 655,360 B (raw 1,310,720 B).
- USB 2.0 ceiling: 13.7 experiments/s, i.e. 1,186,523 per day.
- Downlink-limited ceiling: 6,216,919 experiments/day.

### What actually limits the image count

Time in experiment mode is a multiplier on cadence rather than a ceiling of its own, and it is already folded into the USB column -- that column is the most images the cameras could produce if run flat out for exactly the time a legal attitude exists. Storage and downlink are genuine rate-independent ceilings. The smallest of the three binds.

| Geometry | Time in experiment mode | USB 2.0 | Storage | Downlink | Binding constraint | Max images/day | Cadence needed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 2.5 % (0.6 h/day) | 60,424 | 195,312 | 12,433,838 | USB 2.0 bus over the available experiment time | **60,424** | 13.73 Hz |
| B_3panel_90 | 9.3 % (2.2 h/day) | 220,638 | 195,312 | 12,433,838 | on-board storage | **195,312** | 12.16 Hz |
| C_2panel_135_plus_body | 16.0 % (3.8 h/day) | 379,158 | 195,312 | 12,433,838 | on-board storage | **195,312** | 7.07 Hz |

Two things follow. First, downlink capacity is **not** the constraint on science volume, and it is not close: only two debug images come down per day, so what is actually transmitted is numerical data plus housekeeping, orders of magnitude below what the Leaf Space contacts can carry. Sizing the radio against image volume would be sizing against the wrong thing. Second, energy and attitude feasibility decide how hard the cameras have to be driven to reach whichever ceiling binds: A_2panel_90 needs 13.7 Hz, B_3panel_90 needs 12.2 Hz, C_2panel_135_plus_body needs 7.1 Hz. A geometry with less time in experiment mode has to run its cameras faster to collect the same science.

### Achieved cadence from the CONOPS scheduler

| Geometry | Requested (Hz) | Experiments/day | Images/day | Min SOC | Downlink (MB/day) | Backlog growth (MB/day) |
| --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 0.02 | 42 | 84 | 70 % | 1.0 | +0.36 |
| A_2panel_90 | 0.05 | 122 | 244 | 70 % | 1.0 | +0.32 |
| A_2panel_90 | 0.10 | 267 | 534 | 70 % | 1.0 | +0.34 |
| A_2panel_90 | 0.20 | 440 | 880 | 70 % | 1.0 | +0.37 |
| A_2panel_90 | 0.50 | 1,270 | 2,540 | 70 % | 1.1 | +0.41 |
| A_2panel_90 | 1.00 | 2,555 | 5,110 | 70 % | 1.4 | +0.41 |
| B_3panel_90 | 0.02 | 172 | 344 | 70 % | 1.0 | +0.38 |
| B_3panel_90 | 0.05 | 428 | 855 | 70 % | 1.0 | +0.37 |
| B_3panel_90 | 0.10 | 812 | 1,624 | 70 % | 1.2 | +0.32 |
| B_3panel_90 | 0.20 | 1,607 | 3,213 | 70 % | 1.1 | +0.51 |
| B_3panel_90 | 0.50 | 4,061 | 8,122 | 70 % | 1.4 | +0.60 |
| B_3panel_90 | 1.00 | 8,002 | 16,003 | 70 % | 2.0 | +0.68 |
| C_2panel_135_plus_body | 0.02 | 264 | 528 | 88 % | 1.1 | +0.29 |
| C_2panel_135_plus_body | 0.05 | 652 | 1,304 | 88 % | 1.1 | +0.35 |
| C_2panel_135_plus_body | 0.10 | 1,340 | 2,679 | 88 % | 1.2 | +0.36 |
| C_2panel_135_plus_body | 0.20 | 2,761 | 5,522 | 88 % | 1.4 | +0.39 |
| C_2panel_135_plus_body | 0.50 | 6,623 | 13,246 | 88 % | 1.9 | +0.56 |
| C_2panel_135_plus_body | 1.00 | 12,411 | 24,823 | 87 % | 2.6 | +0.84 |

## CONOPS mode split (baseline 0.2 Hz)

| Geometry | Standby | Experiment | Downlink | Slew | Slews/day | Energy margin (W) | Slew median / p90 / max |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 75.8 % | 2.5 % | 0.02 % | 21.6 % | 26 | -0.48 | 2.2 / 5.6 / 7.4 min |
| B_3panel_90 | 37.4 % | 9.3 % | 0.02 % | 53.3 % | 54 | -0.10 | 1.4 / 6.4 / 7.4 min |
| C_2panel_135_plus_body | 39.2 % | 16.0 % | 0.03 % | 44.8 % | 77 | 1.12 | 1.7 / 5.2 / 6.3 min |

Every slew in the scheduler is priced against the field the vehicle actually has: its eigenaxis, the inertia about that axis, and the authority `sum_i m_i |(B x e)_i|` available about it over the following orbits. That is why the maximum is several times the median -- a repoint that has to turn about the field direction waits for the geometry before it can even start.

Peak tracking rate is how fast the target attitude moves while following a limb or a ground station. Compare it against the rate the magnetorquers can sustain: at the mean control torque above, spinning up to 0.1 deg/s about the stiff axis takes on the order of a minute, so tracking is not the binding constraint -- the discrete slews between modes are.
