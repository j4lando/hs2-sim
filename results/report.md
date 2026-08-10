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
| C_2panel_135_plus_body | 22.3 | 8.24 | 0.369 | 6.17 |

### Per-panel incidence (sun-pointing standby attitude)

| Geometry | Panel | Peak (W) | Mean incidence | Illuminated | Mean output (W) |
| --- | --- | --- | --- | --- | --- |
| A_2panel_90 | deployable | 14.8 | 1.9 deg | 100 % | 9.04 |
| B_3panel_90 | deployable | 22.0 | 1.9 deg | 100 % | 13.44 |
| C_2panel_135_plus_body | deployable | 14.8 | 1.9 deg | 100 % | 9.04 |
| C_2panel_135_plus_body | body_plus_y | 7.5 | 90.0 deg | 0 % | 0.00 |

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
| +x | 0.030 | 1 % | 2 | 83 | 78 | 163 | 865 | 1481.4 |
| -x | 0.030 | 61 % | 759 | 9 | 86 | 853 | 1361 | 36.0 |
| +y | 0.030 | 22 % | 71 | 38 | 78 | 187 | 1361 | 41.2 |
| -y | 0.030 | 40 % | 29 | 46 | 88 | 163 | 1356 | 42.2 |
| +z | 0.010 | 22 % | 69 | 24 | 61 | 154 | 1043 | 38.2 |
| -z | 0.010 | 40 % | 12 | 56 | 81 | 149 | 901 | 43.3 |

Eclipse: 38.9 % of the orbit, longest 36.1 min.

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
| A_2panel_90 | 6.8 % (1.6 h/day) | 161,175 | 48,828 | 12,433,838 | on-board storage | **48,828** | 4.16 Hz |
| B_3panel_90 | 24.1 % (5.8 h/day) | 570,958 | 48,828 | 12,433,838 | on-board storage | **48,828** | 1.17 Hz |
| C_2panel_135_plus_body | 9.6 % (2.3 h/day) | 228,053 | 48,828 | 12,433,838 | on-board storage | **48,828** | 2.94 Hz |

Two things follow. First, downlink capacity is **not** the constraint on science volume, and it is not close: only two debug images come down per day, so what is actually transmitted is numerical data plus housekeeping, three orders of magnitude below what the Leaf Space contacts can carry. Sizing the radio against image volume would be sizing against the wrong thing. Second, on-board storage is what binds, and energy plus attitude feasibility decide how hard the cameras must be driven to reach it -- geometry B needs 1.2 Hz, geometry A needs 4.2 Hz to hit the same storage ceiling because it has far less time in experiment mode.

### Achieved cadence from the CONOPS scheduler

| Geometry | Requested (Hz) | Experiments/day | Images/day | Min SOC | Downlink (MB/day) | Backlog growth (MB/day) |
| --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 0.02 | 130 | 259 | 70 % | 1.3 | +0.11 |
| A_2panel_90 | 0.05 | 325 | 650 | 70 % | 1.2 | +0.15 |
| A_2panel_90 | 0.10 | 634 | 1,268 | 70 % | 1.4 | +0.09 |
| A_2panel_90 | 0.20 | 1,174 | 2,347 | 70 % | 1.4 | +0.13 |
| A_2panel_90 | 0.50 | 3,234 | 6,468 | 70 % | 1.8 | +0.11 |
| A_2panel_90 | 1.00 | 5,652 | 11,303 | 70 % | 2.1 | +0.14 |
| B_3panel_90 | 0.02 | 422 | 844 | 70 % | 1.3 | +0.11 |
| B_3panel_90 | 0.05 | 1,070 | 2,140 | 70 % | 1.4 | +0.16 |
| B_3panel_90 | 0.10 | 2,098 | 4,197 | 70 % | 1.5 | +0.18 |
| B_3panel_90 | 0.20 | 4,158 | 8,315 | 70 % | 1.9 | +0.10 |
| B_3panel_90 | 0.50 | 10,180 | 20,360 | 70 % | 2.9 | +0.16 |
| B_3panel_90 | 1.00 | 19,163 | 38,326 | 70 % | 4.4 | +0.14 |
| C_2panel_135_plus_body | 0.02 | 172 | 345 | 70 % | 1.3 | +0.12 |
| C_2panel_135_plus_body | 0.05 | 421 | 842 | 70 % | 1.2 | +0.16 |
| C_2panel_135_plus_body | 0.10 | 849 | 1,699 | 70 % | 1.4 | +0.13 |
| C_2panel_135_plus_body | 0.20 | 1,661 | 3,321 | 70 % | 1.5 | +0.16 |
| C_2panel_135_plus_body | 0.50 | 3,940 | 7,880 | 70 % | 1.8 | +0.17 |
| C_2panel_135_plus_body | 1.00 | 8,100 | 16,200 | 70 % | 2.6 | +0.13 |

## CONOPS mode split (baseline 0.2 Hz)

| Geometry | Standby | Experiment | Downlink | Slew | Slews/day | Energy margin (W) | Peak tracking rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A_2panel_90 | 81.7 % | 6.8 % | 0.03 % | 11.4 % | 80 | -0.27 | 0.923 deg/s |
| B_3panel_90 | 48.5 % | 24.1 % | 0.04 % | 27.4 % | 217 | 0.01 | 0.923 deg/s |
| C_2panel_135_plus_body | 74.8 % | 9.6 % | 0.03 % | 15.6 % | 123 | -0.24 | 0.996 deg/s |

Peak tracking rate is how fast the target attitude moves while following a limb or a ground station. Compare it against the rate the magnetorquers can sustain: at the mean control torque above, spinning up to 0.1 deg/s about the stiff axis takes on the order of a minute, so tracking is not the binding constraint -- the discrete slews between modes are.

## Beta angle sweep

| RAAN (deg) | Beta (deg) | Eclipse | Max eclipse (min) | Orbit-avg power (W) |
| --- | --- | --- | --- | --- |
| 0 | 2.0 | 39.0 % | 36.1 | 8.23 |
| 45 | 31.9 | 37.5 % | 34.4 | 8.43 |
| 90 | 51.6 | 32.5 % | 29.2 | 9.11 |
| 135 | 35.4 | 36.7 % | 33.9 | 8.53 |
| 180 | 2.1 | 38.8 % | 36.1 | 8.25 |
| 225 | 31.8 | 36.2 % | 34.4 | 8.61 |
| 270 | 51.5 | 30.5 % | 29.4 | 9.38 |
| 315 | 35.3 | 35.8 % | 33.9 | 8.66 |
