# HS-2 CubeSat operations simulation

A [Basilisk](https://avslab.github.io/basilisk/)-backed operations model of a
3U CubeSat in an ISS orbit, built to answer the operational questions below:

| Question | Where it is answered |
| --- | --- |
| Thermal: average sunlight exposure per surface | `hs2sim/thermal.py` |
| Thermal: single-node spacecraft temperature | `hs2sim/thermal.py` |
| Power: sunlight on three candidate array geometries | `hs2sim/power.py` |
| Payload: how many images are sustainable | `hs2sim/comms.py` + `hs2sim/conops.py` |
| Comms: Leaf Space passes per day | `hs2sim/comms.py` |
| ADCS: magnetorquer limits on operations | `hs2sim/adcs.py` |
| CONOPS: how it fits together | `hs2sim/conops.py` |
| Watching the CONOPS in 3D | `hs2sim/vizard.py`, [docs/VIZARD.md](docs/VIZARD.md) |

## Running it

```bash
pip install -r requirements.txt      # numpy, scipy, matplotlib, pyyaml, pytest
# plus Basilisk, built from source per the AVS Lab instructions
python run_analysis.py               # full run -> results/
python run_analysis.py --quick       # 1 day, coarse search, for a fast check
python run_analysis.py --vizard      # also export a Vizard recording
python run_analysis.py --no-exclusion-sweep   # skip the keep-out trade study
pytest tests/                        # physics checks, no Basilisk needed
```

See [docs/VIZARD.md](docs/VIZARD.md) for installing Vizard and opening the
recording — including how to rebuild Basilisk with `vizInterface` if
`vizSupport.vizFound` comes back `False`.

Everything configurable lives in `config/`. No spacecraft number is hard-coded
in the analysis code; if a value matters it is in a YAML file and can be swept.

## How the model is put together

**Basilisk owns the truth.** `hs2sim/environment.py` builds a Basilisk scenario
with the spacecraft, an Earth zonal spherical-harmonic gravity model (GGM03S
J2-J4, so nodal regression and hence beta-angle drift are real), the
`eclipse` module, a centred-dipole magnetic field, and one `groundLocation`
module per Leaf Space site. Every downstream module consumes those time
histories and adds no dynamics of its own.

**No SPICE kernels are needed.** Basilisk's `spiceInterface` wants `de430.bsp`
(~120 MB, downloaded on demand). Instead the stock `planetEphemeris` module is
driven from classical elements: the Sun on its apparent geocentric orbit, and
Earth pinned at the origin with a correct sidereal rotation so ground-station
geometry is right. Sun direction is good to better than 0.02 deg, far finer
than anything here is sensitive to.

**The attitude problem is solved, not assumed.** Experiment mode has to satisfy
four constraints at once (FOUND on a sunlit limb, Sun out of FOUND's 70 deg
cone, Earth and Sun out of the +z 40 deg cone). Since +x and +z are orthogonal,
fixing the FOUND boresight leaves one free parameter — roll about +x — so
`hs2sim/geometry.py` searches limb azimuth against roll angle and reports
whether *any* legal attitude exists at each instant. Where several are legal it
picks the one that generates the most solar power. `tests/test_physics.py`
independently re-checks the solver's own answers against every keep-out cone.

## The camera exclusion-angle trade

`hs2sim/exclusion.py` re-solves the whole pointing problem and re-runs the mode
scheduler across a grid of both keep-out cones, so the question "what would a
different exclusion angle buy us" is answered in images per day rather than in
solid angle. The grid is in `config/mission.yaml` under
`analysis.exclusion_sweep`; results land in `results/report.md` and
`results/exclusion_sweep.png`.

`LOST` moves the +z keep-out against **both** Sun and Earth, because the
requirement quotes a single angle for both and the star tracker shares that
face. `FOUND` moves FOUND's Sun keep-out only — its 74 deg field of view is an
optical property and does not move.

The LOST axis runs to 80 deg on purpose: that is where the geometry has to
break. Fixing FOUND on the limb puts +x about 70 deg off nadir, and +z is
perpendicular to +x, so +z can only reach between 20 and 160 deg from nadir.
The Earth keep-out demands more than (70 + LOST) deg of that range, so the
roll freedom closes completely at LOST = 90 deg regardless of anything else.
The sweep brackets that cliff — feasibility is flat at 49.4 % out to 50 deg,
then falls to 45.4 / 32.8 / 21.0 % at 60 / 70 / 80 deg.

The most useful result is what happens when the two halves of the +z cone are
moved separately. At 80 deg, widening *only* the Sun exclusion leaves 45.4 %
feasible and widening *only* the Earth exclusion leaves 45.3 % — a few points
each. Move both together and it collapses to 21.0 %, far worse than the sum of
the parts, because the two keep-outs exclude different arcs of the roll circle
and only their union leaves nothing behind. If the +z keep-out has to grow,
growing one half is survivable and growing both is not.

One thing to know before reading the output. Three quantities are reported and
they are not equally trustworthy:

| Quantity | What it is | Trust |
| --- | --- | --- |
| Feasible fraction | how much of the timeline has a legal attitude | deterministic function of the cones |
| Image ceiling | feasible fraction × cadence × 2 cameras | same number, mission units |
| Images collected | what the scheduler actually delivers | carries a large noise term |

The last one is noisy for a real reason, not a numerical one. Changing a
keep-out changes which rolls are legal, which changes *which* of several
equally legal attitudes the solver picks, which changes where the large
repoints land. With roughly half the timeline spent slewing, that is a big
lever and it behaves chaotically. The sweep measures the size of that effect
directly — several grid cells have identical feasibility, so their disagreement
in realised images is the noise floor — and the report prints it. Trade on
feasibility; read the realised count as an existence proof, not a ranking.

## What is trusted, and what is not

Per your instructions, these budget values are taken as given:

- Peak power and quantity for every component (the heater is **not** trusted,
  so its duty cycle is swept: 0 / 15 / 30 / 50 %).
- Link budget numbers that pertain to antenna specifications (2 W transmit,
  5 dBi patch, circuit/return/polarisation losses).
- File sizes and telemetry frequencies in the data budget.
- Payload frequency is a free parameter, capped by the USB 2.0 bus.

Two things in the budgets were **changed** because they conflict with the
stated mission:

1. **Ground station.** The link budget models a 1.9 m dish at UW with a G/T of
   -0.6 dB/K. Leaf Space publishes 12.8 dB/K for Leaf Line S-band, which is
   13.4 dB better. Using Leaf Space's number is the whole point of buying the
   service. The link is also solved at the *actual* slant range at every
   sample rather than at one worst-case 10 deg elevation.
2. **Debug images per day.** The spreadsheet downlinks 8; you specified 2
   (1 LOST + 1 FOUND). The model uses 2.

## Assumptions you should challenge first

These are the numbers most likely to change your answers. All are in `config/`.

| Assumption | Value | Why it matters |
| --- | --- | --- |
| Ground station coordinates | approximate | `leaf.space` is blocked by this environment's network egress policy, so exact site coordinates could not be retrieved. See below. |
| Surface optical properties | α/ε per surface | Drives the single-node temperature more than anything else. Handbook values; replace with coupon data. |
| Specific heat | 850 J/kg/K | Sets the thermal time constant, and hence the size of the orbital temperature swing. |
| MT01 dipole moment | 0.20 A m² | Not clearly published. CR0002 is confirmed at 0.20 A m². |
| Heater duty cycle | swept | Explicitly untrusted. |
| USB 2.0 bulk efficiency | 60 % of 480 Mb/s | Sets the payload frame-rate ceiling. |
| Residual dipole | 0.005 A m² | Drives the disturbance torque the magnetorquers must fight. |
| Deployable panel area | 0.03 m² each | Only used by the thermal model, for radiating area. |

Battery capacity (75.6 Wh), payload storage (128 GB) and the geometry C
deployment angle are all as specified, not assumed.

### Ground station coordinates

The site *list* is assembled from Leaf Space press releases and public
reporting: Italy, Lithuania, Ireland, Spain, Sri Lanka, Azores, Scotland,
Iceland, Bulgaria, West and South Australia, British Columbia, New Zealand,
Brazil, and Spaceport Nova Scotia. The latitudes and longitudes are
**city-level approximations**, not surveyed antenna positions, because
`leaf.space` could not be reached from this environment.

What that means: the *number* of sites and their latitude spread are
representative, so the aggregate passes-per-day figure is meaningful, but any
single station's pass times are only as good as its coordinate. Replace the
coordinates in `config/ground_stations.yaml` with the real ones from your
service agreement and re-run; nothing else needs to change.

Note also that Leaf Space advertises 40+ antennas across 17+ locations.
Multiple antennas at one location do not add geometric passes — they add
capacity and scheduling redundancy — so the model counts locations.

### Solar array geometry C

The deployment angle is the dihedral between the wing and the +y face, anchored
by two stated facts: at 180° the wing cells face the same way as the +y face,
and at 90° they face −x (geometries A and B). Both are satisfied by rotating
the normal about +z through (180° − θ):

| θ | Wing normal |
| --- | --- |
| 180° | `( 0.000,  1.000, 0)` = +y |
| 135° | `(-0.707,  0.707, 0)` |
| 90° | `(-1.000,  0.000, 0)` = −x |

So geometry C is one wing carrying 2 panels (14.8 W) whose normal sits 45° off
the +y body panel (7.5 W) — near enough that all three panels are illuminated
at once, which is the whole point of the configuration.

## Single-node thermal model

The whole spacecraft is treated as one isothermal node (instantaneous internal
conduction):

```
C dT/dt = Q_solar + Q_albedo + Q_earthIR + Q_internal - P_electrical - eps*sigma*A*T^4
```

Internal dissipation is derived, not assumed. Everything drawn becomes heat
except energy that physically leaves the vehicle, which is only two things: the
RF the transmitter radiates (computed from the link budget's own 2 W PA output,
−3 dB return loss and −1 dB circuit loss) and the mechanical work the
magnetorquers do (torque × body rate). The second turns out to be about a
billionth of their electrical draw, so ADCS is thermally a pure resistor.

The model reports mean, min, max and swing, plus margin against battery and
electronics limits. Its honest limitation: a single node cannot see gradients,
so the deployed wing really will run hotter in sunlight and colder in eclipse
than the bulk number, and the battery — usually the most temperature-sensitive
item — sits inside the bus where swings are smaller.

## Layout

```
config/          mission, spacecraft and ground station YAML
hs2sim/
  config.py      YAML loading, dotted-path overrides for sweeps
  environment.py Basilisk scenario; orbit, Sun, eclipse, B-field, access
  geometry.py    attitude constraint solving
  power.py       array output, mode loads, battery integration
  thermal.py     per-face illumination, view factors, single-node temperature
  comms.py       passes, link budget, data budget
  adcs.py        magnetorquer authority, slew times, disturbances
  conops.py      the mode scheduler
  exclusion.py   camera keep-out angle trade study
  report.py      Markdown report generation
  plots.py       figures
  vizard.py      CONOPS export for 3D playback
  vizcheck.py    decode and validate a Vizard recording without Vizard
run_analysis.py  entry point
docs/VIZARD.md   how to install Vizard and view the CONOPS
tests/           physics checks that run without Basilisk
```
