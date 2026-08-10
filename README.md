# HS-2 CubeSat operations simulation

A [Basilisk](https://avslab.github.io/basilisk/)-backed operations model of a
3U CubeSat in an ISS orbit, built to answer six questions:

| Question | Where it is answered |
| --- | --- |
| Thermal: average sunlight exposure per surface | `hs2sim/thermal.py` |
| Power: sunlight on three candidate array geometries | `hs2sim/power.py` |
| Payload: how many images are sustainable | `hs2sim/comms.py` + `hs2sim/conops.py` |
| Comms: Leaf Space passes per day | `hs2sim/comms.py` |
| ADCS: magnetorquer limits on operations | `hs2sim/adcs.py` |
| CONOPS: how it fits together | `hs2sim/conops.py` |

## Running it

```bash
pip install -r requirements.txt      # numpy, scipy, matplotlib, pyyaml, pytest
# plus Basilisk, built from source per the AVS Lab instructions
python run_analysis.py               # full run -> results/
python run_analysis.py --quick       # 1 day, coarse search, for a fast check
pytest tests/                        # physics checks, no Basilisk needed
```

Everything configurable lives in `config/`. No spacecraft number is hard-coded
in the analysis code; if a value matters it is in a YAML file and can be swept.

## How the model is put together

**Basilisk owns the truth.** `hs2sim/environment.py` builds a Basilisk scenario
with the spacecraft, an Earth spherical-harmonic gravity model (GGM03S to
degree 4, so nodal regression and hence beta-angle drift are real), the
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
| Battery capacity | 77 Wh | Single biggest driver of sustainable image count. Not supplied in any budget. |
| Ground station coordinates | approximate | `leaf.space` is blocked by this environment's network egress policy, so exact site coordinates could not be retrieved. See below. |
| MT01 dipole moment | 0.20 A m² | Not clearly published. CR0002 is confirmed at 0.20 A m². |
| Heater duty cycle | swept | Explicitly untrusted. |
| USB 2.0 bulk efficiency | 60 % of 480 Mb/s | Sets the payload frame-rate ceiling. |
| Residual dipole | 0.005 A m² | Drives the disturbance torque the magnetorquers must fight. |
| Geometry C interpretation | see below | The wording admits more than one reading. |

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

"1 deployable solar panel attached to +y face with a 135 degree angle between
deployables and +y face, two panels on the deployable and one panel on the +y
face" is modelled as:

- one deployable wing carrying 2 panels, 14.8 W at normal incidence, at a
  135 deg dihedral to the +y face, so its normal is `(-0.707, -0.707, 0)`;
- one body-mounted panel on +y, 7.5 W, normal `(0, 1, 0)`.

The hinge is taken to be along the long (z) edge of the +y face, which is what
makes the 90 deg case in geometries A and B put the wing normal at exactly
`-x` as you described. If you meant two wings in a V, add the second panel to
`config/spacecraft.yaml` — the analysis code needs no change.

## Layout

```
config/          mission, spacecraft and ground station YAML
hs2sim/
  config.py      YAML loading, dotted-path overrides for sweeps
  environment.py Basilisk scenario; orbit, Sun, eclipse, B-field, access
  geometry.py    attitude constraint solving
  power.py       array output, mode loads, battery integration
  thermal.py     per-face illumination, albedo and Earth IR view factors
  comms.py       passes, link budget, data budget
  adcs.py        magnetorquer authority, slew times, disturbances
  conops.py      the mode scheduler
  report.py      Markdown report generation
  plots.py       figures
run_analysis.py  entry point
tests/           physics checks that run without Basilisk
```
