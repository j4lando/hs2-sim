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

**Sanity check.** The sweep re-solves pointing on a coarser azimuth/roll grid than the headline run, so the baseline cell has to reproduce the headline result or the whole sweep is biased. It does: 49.3 % feasible here against 50.1 % at 48x48. The coarse grid is not losing legal attitudes. Realised images differ by more (5,711 against 5,339 per day), which is the scheduler sensitivity discussed under table 3, not a feasibility difference.

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
| **LOST 20 deg** | 6,021 | 5,685 | 5,503 | 5,350 | 5,410 |
| **LOST 30 deg** | 5,842 | 5,611 | 5,540 | 5,133 | 5,016 |
| **LOST 40 deg** | 5,963 | 5,749 | **5,711** | 4,946 | 4,857 |
| **LOST 50 deg** | 6,172 | 5,541 | 5,879 | 5,270 | 5,262 |
| **LOST 60 deg** | 4,761 | 4,527 | 4,383 | 3,928 | 4,155 |
| **LOST 70 deg** | 3,319 | 3,269 | 2,881 | 2,634 | 2,709 |
| **LOST 80 deg** | 2,211 | 2,036 | 1,756 | 1,585 | 1,743 |

**Read table 3 with care.** Several cells in it share an *identical* feasibility -- the +z cone does nothing at all over part of its range -- yet their realised image counts differ by up to 553 images/day (11 %). That spread is not the cone doing anything. Changing a keep-out changes which rolls are legal, which changes the attitude the solver picks among equally legal options, which changes where the large repoints land; with ~50 % of the timeline in slew, that is a big lever and it is essentially chaotic. Treat 553 images/day as the noise floor of table 3, and trade on tables 1 and 2 instead.

### 4. Energy margin (W)

A looser cone is not free: more experiment time means less sun-pointing, and the margin is what pays for it.

| Margin (W) | FOUND 50 deg | FOUND 60 deg | FOUND 70 deg | FOUND 80 deg | FOUND 90 deg |
| --- | --- | --- | --- | --- | --- |
| **LOST 20 deg** | +0.73 | +0.85 | +1.04 | +1.17 | +1.38 |
| **LOST 30 deg** | +0.69 | +0.91 | +1.19 | +1.21 | +1.40 |
| **LOST 40 deg** | +0.68 | +0.89 | **+1.14** | +1.08 | +1.21 |
| **LOST 50 deg** | +0.59 | +0.76 | +1.12 | +1.21 | +1.27 |
| **LOST 60 deg** | +0.62 | +0.82 | +1.15 | +1.23 | +1.41 |
| **LOST 70 deg** | +1.02 | +1.23 | +1.36 | +1.45 | +1.57 |
| **LOST 80 deg** | +1.76 | +2.11 | +2.36 | +2.54 | +2.70 |

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
| 0.00 | 49.4 % | 17,074 | 5,639 | 8.9 % | 0.0 % |
| 0.50 | 49.3 % | 17,047 | 5,664 | 9.0 % | 0.0 % |
| **1.10** | **49.3 %** | 17,047 | 5,711 | 9.0 % | 0.0 % |
| 2.00 | 49.3 % | 17,047 | 5,301 | 9.0 % | 0.0 % |
| 3.00 | 49.3 % | 17,047 | 5,160 | 9.0 % | 0.0 % |
| 5.00 | 49.3 % | 17,047 | 4,702 | 9.0 % | 0.0 % |
| 10.00 | 49.1 % | 16,966 | 5,181 | 9.2 % | 0.0 % |
| 11.10 | 48.1 % | 16,617 | 5,270 | 10.2 % | 0.0 % |
| 15.00 | 47.0 % | 16,259 | 4,588 | 11.2 % | 0.0 % |
| 20.00 | 43.1 % | 14,886 | 4,513 | 11.2 % | 4.0 % |
| 21.10 | 41.0 % | 14,167 | 4,155 | 11.4 % | 5.9 % |

**The pointing budget is very nearly free at its current size, and the sweep says exactly how much room there is.** The as-designed 1.10 deg buffer costs 0.08 percentage points of feasible time against a hypothetical perfect pointer, and feasibility is unchanged all the way out to **5 deg**, only starting to move at 10 deg. That is not luck and it is not a modelling artefact: it is the +z slack from the cone sweep, spent on pointing error instead of on keep-out. In other words the vehicle can miss its pointing spec by a factor of 5 before the geometry charges anything at all for it.

Past that the price accelerates hard: 0.40 pp/deg averaged over the whole swept range but 0.52 pp/deg over the upper half. The buffer eats into the roll window from the Earth side and the Sun side at once, which is the superadditive collapse from the previous section arriving by a different route.

**Cross-check.** Padding every keep-out by *m* degrees is the same inequality as moving both cones out by *m*, so a buffer of 21 deg has to reproduce the grid cell at LOST 60 / FOUND 90 deg. It does: 41.0 % against 41.0 %. Across every comparable point the two agree to 0.00 percentage points. The two numbers come from different code paths -- one adds the margin to the angle inside the solver, the other rewrites the config and re-reads it -- so this checks both.

One thing to be clear about: this is a *hard* constraint on feasibility, not a soft pointing requirement. An attitude that cannot hold the buffer is not counted at all, so an ADCS that misses its spec does not blur images here -- it removes observations from the timeline. The flip side is the useful part for ADCS: there is no science argument for tightening the pointing budget below its current 1.10 deg, because the geometry cannot tell the difference.

**What the cones cannot fix.** `No sunlit limb` is the largest rejection over most of the grid and it barely moves (a span of 0.0 percentage points across all 35 cells): it is eclipse and orbital geometry, not stray light. That is the floor the trade runs into, and it is why even the loosest corner of the grid leaves roughly half the timeline unusable for science.

## Surface illumination (thermal inputs)

Flown attitude from the CONOPS scheduler, geometry `A_2panel_90`.

| Face | Area (m^2) | Sunlit | Mean solar (W/m^2) | Albedo | Earth IR | Total | Peak solar | Longest dark (min) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +x | 0.030 | 0 % | 1 | 88 | 86 | 175 | 569 | 1298.0 |
| -x | 0.030 | 61 % | 776 | 6 | 79 | 861 | 1361 | 38.7 |
| +y | 0.030 | 23 % | 68 | 40 | 82 | 191 | 1361 | 64.4 |
| -y | 0.030 | 38 % | 24 | 43 | 83 | 151 | 1355 | 85.4 |
| +z | 0.010 | 22 % | 55 | 27 | 63 | 145 | 1092 | 47.6 |
| -z | 0.010 | 39 % | 22 | 50 | 77 | 149 | 1064 | 84.6 |

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
| ADCS (magnetorquers) | mechanical work | 15.163 nW | **100.0000 %** |
| Everything else | nothing | 0 W | 100.0 % |

The transmitter is the only meaningful exception. Of its 11.44 W input, the link budget's own numbers (2 W at the PA, -3 dB return loss, -1 dB circuit loss) leave only 0.80 W actually radiating away -- so the radio is, thermally, almost a pure heater.

Magnetorquers are resistive coils. The mechanical power they deliver is torque x body rate, which at this vehicle's 8.9 uN m and 0.0974 deg/s is about 15.163 nW -- roughly one part in a billion of their electrical draw. Unlike reaction wheels they store no useful kinetic energy, and the coil's field energy returns to the bus on de-energisation. Treating ADCS as 100 % dissipative is correct to nine decimal places.

| Geometry | Mean | Min | Max | Swing | Time constant | Battery margin (cold/hot) |
| --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 9.1 C | -3.6 C | 20.5 C | 24.1 C | 79 min | +6.4 / +24.5 C |
| B_3panel_90 | 8.9 C | -7.9 C | 25.8 C | 33.7 C | 64 min | +2.1 / +19.2 C |
| C_2panel_135_plus_body | 15.8 C | 1.0 C | 29.3 C | 28.3 C | 73 min | +11.0 / +15.7 C |

Radiating area 0.260 m^2 at an effective emissivity of 0.81; thermal capacitance 5100 J/K. Mean absorbed environmental load 75.2 W against 8.2 W of internal dissipation.

The thermal time constant is comparable to the orbit period, which is why the swing is far smaller than the instantaneous radiative equilibrium would suggest: the vehicle's own mass averages the eclipse cycle. A single-node model cannot see gradients, so the deployed wing will in reality run hotter in sunlight and colder in eclipse than these numbers, and the battery -- usually the most temperature-sensitive item -- sits inside the bus where swings are smaller. Treat this as the bulk average, not a component prediction.

## ADCS: magnetorquer limits

- Dipole per axis: [0.2, 0.2, 0.2] A m^2.
- Field 26086-48048 nT (mean 35583 nT).
- Control torque: mean 8.92 uN m, minimum 1.27 uN m.
- Pointing budget: 1.00 deg control + 0.10 deg knowledge, combined by `sum` = **1.10 deg**. Every experiment-mode keep-out is enforced with that as a buffer, so it is a direct tax on science time -- see the exclusion-angle trade.

| Slew | Best (min) | Median (min) | 10th percentile field (min) |
| --- | --- | --- | --- |
| 10deg | 1.6 | 2.0 | 2.7 |
| 30deg | 2.7 | 3.4 | 4.7 |
| 60deg | 3.8 | 4.8 | 6.6 |
| 90deg | 4.7 | 5.9 | 8.1 |
| 180deg | 6.6 | 8.4 | 11.4 |

Disturbance torques: gravity gradient 0.077 uN m, residual dipole 0.178 uN m, aero 0.078 uN m. Authority margin 26.9x on average, 3.22x worst case.

Momentum management needs the torquers energised roughly 3.0 % of each orbit.
Detumble from 10 deg/s: about 0.7 hours.

## Payload throughput

- Compressed image: 655,360 B (raw 1,310,720 B).
- USB 2.0 ceiling: 13.7 experiments/s, i.e. 1,186,523 per day.
- Downlink-limited ceiling: 6,216,919 experiments/day.

### What actually limits the image count

Time in experiment mode is a multiplier on cadence rather than a ceiling of its own, and it is already folded into the USB column -- that column is the most images the cameras could produce if run flat out for exactly the time a legal attitude exists. Storage and downlink are genuine rate-independent ceilings. The smallest of the three binds.

| Geometry | Time in experiment mode | USB 2.0 | Storage | Downlink | Binding constraint | Max images/day | Cadence needed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 1.7 % (0.4 h/day) | 39,275 | 195,312 | 12,433,838 | USB 2.0 bus over the available experiment time | **39,275** | 13.73 Hz |
| B_3panel_90 | 6.8 % (1.6 h/day) | 161,908 | 195,312 | 12,433,838 | USB 2.0 bus over the available experiment time | **161,908** | 13.73 Hz |
| C_2panel_135_plus_body | 15.4 % (3.7 h/day) | 366,616 | 195,312 | 12,433,838 | on-board storage | **195,312** | 7.32 Hz |

Two things follow. First, downlink capacity is **not** the constraint on science volume, and it is not close: only two debug images come down per day, so what is actually transmitted is numerical data plus housekeeping, orders of magnitude below what the Leaf Space contacts can carry. Sizing the radio against image volume would be sizing against the wrong thing. Second, energy and attitude feasibility decide how hard the cameras have to be driven to reach whichever ceiling binds: A_2panel_90 needs 13.7 Hz, B_3panel_90 needs 13.7 Hz, C_2panel_135_plus_body needs 7.3 Hz. A geometry with less time in experiment mode has to run its cameras faster to collect the same science.

### Achieved cadence from the CONOPS scheduler

| Geometry | Requested (Hz) | Experiments/day | Images/day | Min SOC | Downlink (MB/day) | Backlog growth (MB/day) |
| --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 0.02 | 39 | 77 | 70 % | 0.9 | +0.41 |
| A_2panel_90 | 0.05 | 85 | 170 | 70 % | 0.9 | +0.42 |
| A_2panel_90 | 0.10 | 158 | 316 | 70 % | 0.9 | +0.43 |
| A_2panel_90 | 0.20 | 286 | 572 | 70 % | 1.0 | +0.40 |
| A_2panel_90 | 0.50 | 937 | 1,875 | 70 % | 1.0 | +0.45 |
| A_2panel_90 | 1.00 | 1,627 | 3,253 | 70 % | 1.1 | +0.46 |
| B_3panel_90 | 0.02 | 123 | 245 | 70 % | 0.9 | +0.48 |
| B_3panel_90 | 0.05 | 301 | 601 | 70 % | 0.8 | +0.56 |
| B_3panel_90 | 0.10 | 626 | 1,252 | 70 % | 0.9 | +0.51 |
| B_3panel_90 | 0.20 | 1,179 | 2,358 | 70 % | 0.9 | +0.60 |
| B_3panel_90 | 0.50 | 2,967 | 5,935 | 70 % | 1.1 | +0.69 |
| B_3panel_90 | 1.00 | 5,767 | 11,533 | 70 % | 1.5 | +0.84 |
| C_2panel_135_plus_body | 0.02 | 279 | 558 | 89 % | 1.1 | +0.29 |
| C_2panel_135_plus_body | 0.05 | 690 | 1,379 | 89 % | 1.1 | +0.36 |
| C_2panel_135_plus_body | 0.10 | 1,357 | 2,714 | 89 % | 1.2 | +0.36 |
| C_2panel_135_plus_body | 0.20 | 2,670 | 5,339 | 89 % | 1.3 | +0.48 |
| C_2panel_135_plus_body | 0.50 | 6,656 | 13,311 | 89 % | 1.8 | +0.61 |
| C_2panel_135_plus_body | 1.00 | 13,250 | 26,499 | 89 % | 2.7 | +0.87 |

## CONOPS mode split (baseline 0.2 Hz)

| Geometry | Standby | Experiment | Downlink | Slew | Slews/day | Energy margin (W) | Peak tracking rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 75.3 % | 1.7 % | 0.02 % | 23.0 % | 29 | -0.41 | 0.721 deg/s |
| B_3panel_90 | 36.3 % | 6.8 % | 0.02 % | 56.9 % | 50 | -0.13 | 0.721 deg/s |
| C_2panel_135_plus_body | 36.8 % | 15.4 % | 0.03 % | 47.7 % | 75 | 0.93 | 0.942 deg/s |

Peak tracking rate is how fast the target attitude moves while following a limb or a ground station. Compare it against the rate the magnetorquers can sustain: at the mean control torque above, spinning up to 0.1 deg/s about the stiff axis takes on the order of a minute, so tracking is not the binding constraint -- the discrete slews between modes are.
