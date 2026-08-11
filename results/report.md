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

## Surface illumination (thermal inputs)

Flown attitude from the CONOPS scheduler, geometry `A_2panel_90`.

| Face | Area (m^2) | Sunlit | Mean solar (W/m^2) | Albedo | Earth IR | Total | Peak solar | Longest dark (min) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +x | 0.030 | 1 % | 1 | 82 | 77 | 160 | 294 | 1571.9 |
| -x | 0.030 | 61 % | 759 | 9 | 86 | 855 | 1361 | 36.0 |
| +y | 0.030 | 23 % | 75 | 36 | 77 | 189 | 1352 | 41.2 |
| -y | 0.030 | 38 % | 23 | 47 | 88 | 158 | 1332 | 43.2 |
| +z | 0.010 | 22 % | 74 | 23 | 60 | 158 | 1043 | 38.2 |
| -z | 0.010 | 39 % | 14 | 57 | 82 | 154 | 1158 | 43.3 |

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
| A_2panel_90 | 8.1 C | -5.9 C | 19.9 C | 25.8 C | 80 min | +4.1 / +25.1 C |
| B_3panel_90 | 6.3 C | -8.9 C | 22.5 C | 31.4 C | 66 min | +1.1 / +22.5 C |
| C_2panel_135_plus_body | 15.8 C | 0.8 C | 27.8 C | 27.0 C | 73 min | +10.8 / +17.2 C |

Radiating area 0.260 m^2 at an effective emissivity of 0.81; thermal capacitance 5100 J/K. Mean absorbed environmental load 74.1 W against 8.0 W of internal dissipation.

The thermal time constant is comparable to the orbit period, which is why the swing is far smaller than the instantaneous radiative equilibrium would suggest: the vehicle's own mass averages the eclipse cycle. A single-node model cannot see gradients, so the deployed wing will in reality run hotter in sunlight and colder in eclipse than these numbers, and the battery -- usually the most temperature-sensitive item -- sits inside the bus where swings are smaller. Treat this as the bulk average, not a component prediction.

## ADCS: magnetorquer limits

- Dipole per axis: [0.2, 0.2, 0.2] A m^2.
- Field 26086-48048 nT (mean 35583 nT).
- Control torque: mean 8.92 uN m, minimum 1.27 uN m.

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
| A_2panel_90 | 7.8 % (1.9 h/day) | 183,926 | 195,312 | 12,433,838 | USB 2.0 bus over the available experiment time | **183,926** | 13.73 Hz |
| B_3panel_90 | 24.0 % (5.8 h/day) | 570,088 | 195,312 | 12,433,838 | on-board storage | **195,312** | 4.70 Hz |
| C_2panel_135_plus_body | 29.4 % (7.1 h/day) | 698,305 | 195,312 | 12,433,838 | on-board storage | **195,312** | 3.84 Hz |

Two things follow. First, downlink capacity is **not** the constraint on science volume, and it is not close: only two debug images come down per day, so what is actually transmitted is numerical data plus housekeeping, orders of magnitude below what the Leaf Space contacts can carry. Sizing the radio against image volume would be sizing against the wrong thing. Second, energy and attitude feasibility decide how hard the cameras have to be driven to reach whichever ceiling binds: A_2panel_90 needs 13.7 Hz, B_3panel_90 needs 4.7 Hz, C_2panel_135_plus_body needs 3.8 Hz. A geometry with less time in experiment mode has to run its cameras faster to collect the same science.

### Achieved cadence from the CONOPS scheduler

| Geometry | Requested (Hz) | Experiments/day | Images/day | Min SOC | Downlink (MB/day) | Backlog growth (MB/day) |
| --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 0.02 | 139 | 277 | 70 % | 1.2 | +0.17 |
| A_2panel_90 | 0.05 | 338 | 677 | 70 % | 1.2 | +0.15 |
| A_2panel_90 | 0.10 | 677 | 1,354 | 70 % | 1.4 | +0.10 |
| A_2panel_90 | 0.20 | 1,339 | 2,679 | 70 % | 1.5 | +0.10 |
| A_2panel_90 | 0.50 | 3,196 | 6,392 | 70 % | 1.8 | +0.10 |
| A_2panel_90 | 1.00 | 6,243 | 12,486 | 70 % | 2.2 | +0.13 |
| B_3panel_90 | 0.02 | 422 | 844 | 70 % | 1.3 | +0.11 |
| B_3panel_90 | 0.05 | 1,071 | 2,141 | 70 % | 1.4 | +0.16 |
| B_3panel_90 | 0.10 | 2,099 | 4,199 | 70 % | 1.5 | +0.18 |
| B_3panel_90 | 0.20 | 4,151 | 8,303 | 70 % | 1.9 | +0.10 |
| B_3panel_90 | 0.50 | 9,858 | 19,716 | 70 % | 2.8 | +0.16 |
| B_3panel_90 | 1.00 | 18,641 | 37,283 | 70 % | 4.3 | +0.16 |
| C_2panel_135_plus_body | 0.02 | 509 | 1,018 | 89 % | 1.2 | +0.18 |
| C_2panel_135_plus_body | 0.05 | 1,256 | 2,513 | 89 % | 1.5 | +0.09 |
| C_2panel_135_plus_body | 0.10 | 2,544 | 5,089 | 89 % | 1.7 | +0.10 |
| C_2panel_135_plus_body | 0.20 | 5,085 | 10,170 | 89 % | 2.1 | +0.10 |
| C_2panel_135_plus_body | 0.50 | 12,167 | 24,335 | 89 % | 3.2 | +0.12 |
| C_2panel_135_plus_body | 1.00 | 22,838 | 45,676 | 89 % | 5.0 | +0.12 |

## CONOPS mode split (baseline 0.2 Hz)

| Geometry | Standby | Experiment | Downlink | Slew | Slews/day | Energy margin (W) | Peak tracking rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 80.6 % | 7.8 % | 0.03 % | 11.7 % | 82 | -0.32 | 0.975 deg/s |
| B_3panel_90 | 48.6 % | 24.0 % | 0.04 % | 27.4 % | 216 | 0.00 | 0.923 deg/s |
| C_2panel_135_plus_body | 47.3 % | 29.4 % | 0.04 % | 23.3 % | 187 | 1.65 | 0.983 deg/s |

Peak tracking rate is how fast the target attitude moves while following a limb or a ground station. Compare it against the rate the magnetorquers can sustain: at the mean control torque above, spinning up to 0.1 deg/s about the stiff axis takes on the order of a minute, so tracking is not the binding constraint -- the discrete slews between modes are.
