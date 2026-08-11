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
frames. Stride 1 quadruples that; it is smoother but the file grows in
proportion.

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

## 5. What you are looking at

Four cones are attached to the spacecraft body, matching the constraints the
attitude solver enforces:

| Cone | Axis | Half angle | Meaning |
| --- | --- | --- | --- |
| Star tracker / LOST Sun keep-out | +z | 40° | Sun must stay **outside** |
| LOST Earth keep-out | +z | 40° | Earth must stay **outside** |
| FOUND Sun keep-out | +x | 70° | Sun must stay **outside** |
| FOUND field of view | +x | 37° | Earth must stay **inside** |

Vizard recolours a cone when its condition is violated, which makes this the
quickest way to check the solver is doing what it claims. During experiment
mode you should see the +x cone locked onto Earth's limb while both +z cones
stay clear of Earth and Sun — and you should see the vehicle spend real time
slewing between that attitude, sun-pointing, and ground-station tracking,
because with magnetorquers alone a 90° slew takes about six minutes.

The yellow markers on Earth are the Leaf Space sites, each drawn with the cone
its 10° elevation mask sweeps. Watch Reykjavík: at 64°N it never comes into
view, because a 51.6° inclination ground track cannot reach it.

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
