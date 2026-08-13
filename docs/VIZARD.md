# Viewing the CONOPS in Vizard

Vizard is the AVS Lab's 3D visualiser for Basilisk. This project can export the
whole CONOPS timeline — the flown attitude, the ground stations, and the
pointing constraints as live cones — so you can watch the mission instead of
reading tables.

## 1. Install Vizard

Download the build for your OS from the AVS Lab release page:

<https://avslab.github.io/basilisk/Vizard/VizardDownload.html>

It is a standalone Unity application; there is nothing to compile and it does
not need to live next to Basilisk.

- **macOS** — unzip and drag `Vizard.app` to Applications. On first launch,
  right-click → Open (it is unsigned, so a double-click gets blocked by
  Gatekeeper).
- **Windows** — unzip and run `Vizard.exe`.
- **Linux** — unzip, then `chmod +x Vizard.x86_64` and run it.

## 2. Build Basilisk with vizInterface

The export needs Basilisk's `vizInterface` module, which is **off by default**
in some builds. Check:

```bash
python -c "from Basilisk.utilities import vizSupport; print(vizSupport.vizFound)"
```

If that prints `False`, rebuild Basilisk with the flag on:

```bash
python conanfile.py --vizInterface True --buildProject True
```

`vizInterface` pulls in protobuf and cppzmq. If your build cannot reach Conan
Center, both are available from system packages — on Ubuntu,
`apt install libprotobuf-dev protobuf-compiler libzmq3-dev cppzmq-dev` supplies
protobuf 3.21.12, which is the exact version Basilisk asks for.

## 3. Export a recording

```bash
python run_analysis.py --vizard
```

That runs the full analysis and then writes a Vizard binary for whichever array
geometry has the best energy margin. To pick a specific one, or to change how
finely the timeline is sampled:

```bash
python run_analysis.py --vizard B_3panel_90          # a named geometry
python run_analysis.py --vizard --vizard-stride 1    # every sample (bigger file)
```

The recording lands in:

```
results/_VizFiles/hs2_conops_<geometry>_UnityViz.bin
```

`--vizard-stride` defaults to 4, so a 3-day run at a 5 s step becomes ~13,000
frames at 20 s apart. **For watching slews, use `--vizard-stride 1`**: a slew
takes about six minutes, which is only ~18 frames at the default and looks
steppy, versus ~72 frames at stride 1.

## 3b. Verify the recording without Vizard

If you cannot install Vizard (or just want a fast check that an export is
sound), the recording can be decoded and validated directly:

```bash
python -m hs2sim.vizcheck results/_VizFiles/hs2_conops_<geometry>_UnityViz.bin
```

It decodes the protobuf stream and checks the scene against physics — Earth at
the origin with the right radius, the Sun about 1 AU away with a declination
inside the obliquity, the spacecraft in the ISS altitude band at the right
inclination, a valid MRP attitude, stations on Earth's surface, and the four
constraint cones at their configured angles. It also reconstructs the body
frame from each recorded attitude and reports what fraction of frames satisfy
all four experiment-mode cones, then writes a `*.preview.png` next to the
`.bin` showing the Earth with its day/night terminator, the orbit, and the body
axes at an experiment-mode instant.

One gotcha if you parse the file yourself: angles inside it are in **degrees**.
`vizInterface` multiplies by R2D on the way out because Unity expects degrees,
even though the Python API takes radians.

## 4. Open it

Launch Vizard, then either:

- press **Select Data File** on the start screen and choose the `.bin`, or
- drag the `.bin` onto the Vizard window.

Playback controls sit along the bottom: play/pause, speed, and a scrub bar.

Useful things once it is running:

| What | Where |
| --- | --- |
| Follow the spacecraft | double-click it, or use the camera dropdown |
| See the body axes | `View → Coordinate Frames → Spacecraft Body` |
| Show the keep-out cones | `View → Cones` (they are on by default) |
| Show ground stations | `View → Locations` |
| Speed up / slow down | the playback rate box, bottom right |

At high playback rates (the default can exceed 1000×) a 93-minute orbit goes by
in a few seconds and every mode change blurs together, which makes the attitude
look static. Drop to ~60× to actually see the vehicle slew between
sun-pointing, limb-staring and ground-station tracking.

Slews are modelled as continuous eigenaxis rotations at a magnetorquer-limited
rate, not as instant snaps, so the vehicle visibly turns. Peak rate is about
0.9 °/s and a large repoint takes several minutes.

**A straight line through the spacecraft?** That is a Vizard HUD element, not
something in the recording — the export contains no point-lines, no target
lines and no scripted cameras. It is almost certainly the boresight line of the
**Standard Camera** panel (the inset window titled "Standard Camera 1"). Close
that panel, or toggle the camera boresight HUD, and it disappears.

## 4b. The payload camera views

Two scripted cameras are exported, looking exactly down the payload boresights
at those instruments' real fields of view:

| Camera | Axis | Field of view (edge-to-edge) |
| --- | --- | --- |
| `LOST camera (+z)` | +z | 25.2° |
| `FOUND camera (+x)` | +x | 74° |

Pick either from Vizard's camera dropdown to see what that instrument sees at
that instant. This is the view to use when checking whether FOUND really is on
a sunlit limb, rather than trying to judge it from the outside.

Note the free-look Vizard camera has nothing to do with these — it is wherever
you last dragged it. If the outside view and the sensor cones seem to disagree,
you are comparing the free camera against a body-fixed boresight; switch to the
scripted camera instead.

## 5. What you are looking at

Four cones are attached to the spacecraft body, matching the constraints the
attitude solver enforces:

| Cone | Axis | Half angle | Meaning |
| --- | --- | --- | --- |
| Star tracker / LOST Sun keep-out | +z | 40° | Sun must stay **outside** |
| LOST Earth keep-out | +z | 40° | Earth must stay **outside** |
| FOUND Sun keep-out | +x | 70° | Sun must stay **outside** |
| FOUND field of view | +x | 37° | Earth must stay **inside** |

**How a cone signals a violation.** Vizard does *not* change the cone's
colour. Per the Vizard GUI documentation: if the in/out condition is not
triggered the cone is drawn **opaque** (translucent); when it *is* triggered
the cone becomes **solid**. It is a subtle change and easy to miss with the
station cones also on screen — turn the ground-station cones off under
`Edit Location` if you want to watch it clearly.

**The drawn cones are the requirement, not what the solver enforced.** Every
keep-out is enforced with the pointing-error buffer on top (1.1 deg as
configured — see `adcs.pointing_margin_deg`), so in experiment mode the flown
attitude clears each cone by that much and you should never see the Sun or
Earth graze a cone edge. If one ever does graze, that is a finding.

The cones are drawn at spacecraft scale (12 m, set by `vizard.cone_height_m`
in `config/mission.yaml`), matching the convention in Basilisk's own examples.
Drawing them out to orbit altitude makes them fill the screen and hide
everything else.

**These cones are drawn all the time, but the constraints only apply in
experiment mode.** The payload is off in standby and downlink, so the LOST
cone sweeping across Earth then is expected and is not a violation. Use the
payload is off outside experiment mode. Over a 3-day run the vehicle spends
roughly 15 % of the time in experiment mode, 36 % sun-pointing and 48 %
slewing, so most of what you are watching is a mode where those cones do not
apply.

**Ground stations light up when they have the spacecraft.** Each site is a dim
marker normally, and switches to a bright enlarged marker while the spacecraft
is above its 10° elevation mask. Colours and marker sizes are in
`config/mission.yaml` under `vizard`. Watch Reykjavík: at 64°N it never lights
up at all, because a 51.6° inclination ground track cannot reach it.

Each site also carries the cone its elevation mask sweeps — 160° edge-to-edge
about that site's own local vertical, drawn out to the true maximum slant range
(~1480 km at this altitude) rather than an arbitrary radius.

### Angle conventions, verified

Two different conventions are in play, which is easy to get backwards:

| Quantity | Convention | Source |
| --- | --- | --- |
| Cone `incidenceAngle` | **half**-angle from boresight | `constrainedAttitudeManeuver` tests `dot(boresight, body) >= cos(Fov)`, and Basilisk's own example feeds the same value to both the cone and that module |
| Camera / location `fieldOfView` | **edge-to-edge** (full cone) | stated in `vizMessage.proto` |

So the 40° and 70° Sun exclusions go in unchanged, FOUND's 74° full-cone FOV
goes in as a 37° cone half-angle, and the camera FOVs go in as the full 25.2°
and 74°. `hs2sim.vizcheck` asserts the recording matches
`config/spacecraft.yaml` on every one of these.

## 6. Live streaming instead of a file

To drive a running Vizard directly rather than recording:

1. Start Vizard and choose **Live Streaming** on the start screen (the default
   address, `tcp://localhost:5556`, is what Basilisk publishes to).
2. Then run:

```bash
python run_analysis.py --vizard --vizard-live
```

The simulation will pace itself to the socket. This is convenient for quick
looks, but the recorded file is better for anything you want to scrub through
or share.

## Troubleshooting

**`vizSupport.vizFound` is False** — Basilisk was built without
`vizInterface`; see step 2.

**Vizard opens but the spacecraft does not move** — the `.bin` did not record
any frames. Confirm `results/hs2_conops_*_trajectory.csv` has more than a
header line, and that the run printed `wrote .../_UnityViz.bin`.

**Playback is jerky** — increase `--vizard-stride` to reduce the frame count,
or lower the playback rate in Vizard.

**Nothing appears when live streaming** — start Vizard *before* the script, and
check nothing else is bound to port 5556.
