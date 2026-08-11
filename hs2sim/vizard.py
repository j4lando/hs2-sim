"""Export the CONOPS timeline for playback in Vizard.

The mode scheduler computes the flown attitude in post-processing, so there is
no live Basilisk spacecraft whose state Vizard could record. Instead the
timeline is written to a data file and replayed through Basilisk's stock
``dataFileToViz`` module, which republishes it as spacecraft state messages
that ``vizInterface`` records into a Vizard binary.

What ends up in the scene:

  * the spacecraft flying the actual CONOPS attitude;
  * two scripted cameras looking exactly along the LOST (+z) and FOUND (+x)
    boresights, at those instruments' real fields of view, so you can see what
    each payload camera sees;
  * every Leaf Space ground station, dim by default and brightly highlighted
    while the spacecraft is above its elevation mask;
  * the pointing constraints as keep-in / keep-out cones. Vizard draws a cone
    translucent when its condition is satisfied and solid when it is violated.
    The cones are always present while the constraints only apply in experiment
    mode, so a cone crossing Earth during sun-pointing is expected.

**Angle conventions**, which are easy to get backwards and were verified
against Basilisk's own constraint module:

  * ``createConeInOut(incidenceAngle=...)`` is a **half-angle** from the
    boresight. ``constrainedAttitudeManeuver`` tests violations as
    ``dot(boresight, body) >= cos(Fov)`` and the stock scenario passes the same
    value to both, so a 40 deg Sun exclusion is passed as 40 deg.
  * Camera and ground-station ``fieldOfView`` are **edge-to-edge** (full cone),
    per the protobuf definitions, so a 25.2 deg full-cone FOV is passed as 25.2.

See ``docs/VIZARD.md`` for how to install Vizard and open the result.
"""

from __future__ import annotations

import datetime as dt
import math
import pathlib

import numpy as np

from . import environment
from .config import MissionConfig
from .environment import R_EARTH, EnvironmentResult

# Vizard colours as RGBA-255.
COLOR_KEEPOUT = [255, 60, 60, 110]
COLOR_KEEPIN = [60, 220, 120, 110]


def body_rates(dcm_BN: np.ndarray, dt_s: float) -> np.ndarray:
    """Body angular velocity from a DCM history, rad/s.

    The rotation from one sample to the next is ``dcm[i+1] @ dcm[i].T``; its
    principal rotation vector divided by ``dt`` is the mean body rate over the
    step.
    """
    n = len(dcm_BN)
    omega = np.zeros((n, 3))
    for i in range(n - 1):
        rel = dcm_BN[i + 1] @ dcm_BN[i].T
        cos_theta = np.clip((np.trace(rel) - 1.0) / 2.0, -1.0, 1.0)
        theta = math.acos(cos_theta)
        if theta < 1e-12:
            continue
        axis = np.array([rel[2, 1] - rel[1, 2],
                         rel[0, 2] - rel[2, 0],
                         rel[1, 0] - rel[0, 1]]) / (2.0 * math.sin(theta))
        omega[i] = axis * theta / dt_s
    omega[-1] = omega[-2] if n > 1 else 0.0
    return omega


def write_trajectory_file(env: EnvironmentResult,
                          dcm_BN: np.ndarray,
                          path: pathlib.Path,
                          stride: int = 1) -> tuple[int, float]:
    """Write the CONOPS timeline in the layout ``dataFileToViz`` expects.

    One row per sample: ``time, r_N(3), v_N(3), sigma_BN(3), omega_BN_B(3)``.
    Returns (rows written, time step of the written file).
    """
    from Basilisk.utilities import RigidBodyKinematics as rbk

    stride = max(1, int(stride))
    index = np.arange(0, env.n_samples, stride)
    dt_out = env.dt_s * stride
    omega = body_rates(dcm_BN, env.dt_s)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("time,rx,ry,rz,vx,vy,vz,s1,s2,s3,wx,wy,wz\n")
        for i in index:
            sigma = rbk.C2MRP(dcm_BN[i])
            row = [env.t_s[i],
                   *env.r_BN_N[i], *env.v_BN_N[i],
                   *sigma, *omega[i]]
            handle.write(",".join(f"{v:.6e}" for v in row) + "\n")
    return len(index), dt_out


def max_slant_range_m(cfg: MissionConfig, elevation_deg: float) -> float:
    """Slant range to a station sitting exactly on the elevation mask.

    Solves the law-of-cosines triangle Earth centre / station / spacecraft, and
    is what the ground-station coverage cone should be drawn out to. Using an
    arbitrary large number instead just produces a cone that swamps the scene.
    """
    altitude = float(cfg.orbit.altitude_km) * 1e3
    elevation = math.radians(elevation_deg)
    return (math.sqrt((R_EARTH * math.sin(elevation)) ** 2
                      + 2.0 * R_EARTH * altitude + altitude ** 2)
            - R_EARTH * math.sin(elevation))


class _StationHighlighter:
    """Brightens each ground station while it has access to the spacecraft.

    Vizard sends the location list once and then clears it, so a station is
    only re-transmitted if it is appended again. Re-sending all fifteen every
    frame would bloat the recording, so this only republishes a station on the
    frames where its access state actually flips -- a few hundred events over a
    3-day run instead of a couple of hundred thousand.
    """

    def __new__(cls, *args, **kwargs):  # pragma: no cover - thin factory
        from Basilisk.architecture import sysModel

        class Impl(sysModel.SysModel):
            def __init__(self, viz, viz_support, station_names, access,
                         dt_out, style):
                super().__init__()
                self.viz = viz
                self.viz_support = viz_support
                self.station_names = station_names
                self.access = access
                self.dt_out = dt_out
                self.style = style
                self.state = [None] * len(station_names)

            def UpdateState(self, CurrentSimNanos):
                index = min(int(round(CurrentSimNanos * 1e-9 / self.dt_out)),
                            self.access.shape[1] - 1)
                for s, name in enumerate(self.station_names):
                    active = bool(self.access[s, index])
                    if active == self.state[s]:
                        continue
                    self.state[s] = active
                    self.viz_support.changeLocation(
                        self.viz, name,
                        color=(self.style["active_color"] if active
                               else self.style["idle_color"]),
                        markerScale=(self.style["active_scale"] if active
                                     else self.style["idle_scale"]))

        return Impl(*args, **kwargs)


def export(cfg: MissionConfig,
           env: EnvironmentResult,
           dcm_BN: np.ndarray,
           out_dir: pathlib.Path,
           name: str = "hs2_conops",
           stride: int = 1,
           live_stream: bool = False) -> pathlib.Path | None:
    """Produce a Vizard binary for the supplied attitude timeline.

    Returns the path to the saved file, or None if Basilisk was built without
    ``vizInterface`` (in which case nothing can be recorded).
    """
    from Basilisk.simulation import dataFileToViz, spacecraft
    from Basilisk.utilities import (SimulationBaseClass, macros,
                                    simIncludeGravBody, vizSupport)

    if not vizSupport.vizFound:
        return None

    out_dir = pathlib.Path(out_dir)
    data_path = out_dir / f"{name}_trajectory.csv"
    rows, dt_out = write_trajectory_file(env, dcm_BN, data_path, stride)

    sim = SimulationBaseClass.SimBaseClass()
    process = sim.CreateNewProcess("vizProcess")
    task = "vizTask"
    process.addTask(sim.CreateNewTask(task, macros.sec2nano(dt_out)))

    # A spacecraft object is still needed so Vizard has a body to attach
    # settings and gravity bodies to; its own dynamics are never used because
    # the state message is overridden below.
    sc = spacecraft.Spacecraft()
    sc.ModelTag = "HS2"
    sc.hub.mHub = float(cfg.spacecraft.bus.mass_kg)
    grav_factory = simIncludeGravBody.gravBodyFactory()
    earth = grav_factory.createEarth()
    earth.isCentralBody = True
    sun = grav_factory.createSun()
    grav_factory.addBodiesTo(sc)

    # Vizard takes each celestial body's position from that gravity body's
    # planetBodyInMsg. Leave them unconnected and Earth and the Sun both sit at
    # the origin -- the Sun ends up inside the Earth, and the lighting is
    # meaningless. Feed them the same ephemeris the analysis used.
    #
    # This is safe here precisely because the spacecraft's own dynamics are
    # discarded: the Earth entry carries a 1 mm orbit whose implied velocity
    # would wreck a real propagation, but nothing integrates in this scene.
    epoch = dt.datetime.fromisoformat(cfg.sim.epoch_utc)
    ephem = environment.build_planet_ephemeris(epoch)
    sim.AddModelToTask(task, ephem, 100)
    earth.planetBodyInMsg.subscribeTo(ephem.planetOutMsgs[0])
    sun.planetBodyInMsg.subscribeTo(ephem.planetOutMsgs[1])

    replay = dataFileToViz.DataFileToViz()
    replay.ModelTag = "conopsReplay"
    replay.setNumOfSatellites(1)
    replay.dataFileName = str(data_path)
    replay.delimiter = ","
    replay.attitudeType = 0          # MRP
    replay.convertPosToMeters = 1.0  # already metres
    sim.AddModelToTask(task, replay)

    save_file = None if live_stream else str(out_dir / name)
    viz = vizSupport.enableUnityVisualization(
        sim, task, [sc], saveFile=save_file, liveStream=live_stream)

    viz.settings.showSpacecraftLabels = 1
    viz.settings.orbitLinesOn = 1
    viz.settings.showCelestialBodyLabels = 1
    viz.settings.trueTrajectoryLinesOn = 1

    # Feed Vizard the replayed CONOPS state instead of the dummy dynamics.
    viz.scData[0].spacecraftName = sc.ModelTag
    viz.scData[0].scStateInMsg.subscribeTo(replay.scStateOutMsgs[0])

    _add_payload_cameras(cfg, viz, vizSupport, sc.ModelTag)
    _add_ground_stations(cfg, viz, vizSupport)
    _add_constraint_cones(cfg, viz, vizSupport, sc.ModelTag)
    _add_station_highlighting(cfg, sim, task, viz, vizSupport, env, stride,
                              dt_out)

    sim.InitializeSimulation()
    sim.ConfigureStopTime(macros.sec2nano((rows - 1) * dt_out))
    sim.ExecuteSimulation()

    if live_stream:
        return None
    # vizInterface nests recordings in a _VizFiles subdirectory.
    return out_dir / "_VizFiles" / f"{name}_UnityViz.bin"


def _add_payload_cameras(cfg: MissionConfig, viz, vizSupport,
                         body_name: str) -> None:
    """Scripted cameras looking down the LOST and FOUND boresights.

    ``fieldOfView`` here is edge-to-edge, so each instrument's full-cone FOV is
    passed straight through: 25.2 deg for LOST, 74 deg for FOUND. Selecting one
    of these in Vizard's camera dropdown shows exactly what that payload camera
    sees at that instant.
    """
    sensors = cfg.spacecraft.sensors
    for sensor_key, label in (("lost_camera", "LOST camera (+z)"),
                              ("found_camera", "FOUND camera (+x)")):
        sensor = sensors[sensor_key]
        vizSupport.createStandardCamera(
            viz,
            spacecraftName=body_name,
            setMode=1,                                   # pointing-vector mode
            pointingVector_B=[float(v) for v in sensor.boresight],
            fieldOfView=math.radians(float(sensor.fov_full_deg)),
            displayName=label,
        )


def _add_ground_stations(cfg: MissionConfig, viz, vizSupport) -> None:
    """Drop every Leaf Space site into the scene with its elevation cone."""
    style = cfg.mission.vizard
    for station in cfg.stations():
        elevation = float(station.minimum_elevation_deg)
        lat = math.radians(float(station.latitude_deg))
        lon = math.radians(float(station.longitude_deg))

        # The boresight must be the station's own local vertical, not the
        # planet's spin axis -- otherwise every cone points at the north pole
        # and the visibility volumes fan off in the same direction instead of
        # radiating out of their own sites.
        #
        # It has to be passed explicitly: vizSupport's fallback divides the
        # list returned by lla2fixedframe by a float, which raises TypeError.
        # Basilisk models Earth with radiusRatio = 1, so the local vertical is
        # exactly the normalised position vector.
        g_hat = [math.cos(lat) * math.cos(lon),
                 math.cos(lat) * math.sin(lon),
                 math.sin(lat)]

        vizSupport.addLocation(
            viz,
            stationName=str(station.name),
            parentBodyName="earth",
            lla_GP=[lat, lon, float(station.altitude_m)],
            gHat_P=g_hat,
            # A station with a 10 deg mask sees everything within 80 deg of its
            # local zenith, i.e. a 160 deg edge-to-edge cone.
            fieldOfView=math.radians(2.0 * (90.0 - elevation)),
            color=[int(c) for c in style.station_idle_color],
            markerScale=float(style.station_idle_marker_scale),
            # Draw the cone only as far as a spacecraft could actually be seen,
            # rather than an arbitrary large radius.
            range=max_slant_range_m(cfg, elevation),
        )


def _add_station_highlighting(cfg, sim, task, viz, vizSupport, env, stride,
                              dt_out) -> None:
    """Make stations light up while the spacecraft is above their mask."""
    style = cfg.mission.vizard
    access = np.asarray(env.station_access)[:, ::max(1, int(stride))]
    highlighter = _StationHighlighter(
        viz, vizSupport, [str(s.name) for s in cfg.stations()], access, dt_out,
        {
            "idle_color": [int(c) for c in style.station_idle_color],
            "active_color": [int(c) for c in style.station_active_color],
            "idle_scale": float(style.station_idle_marker_scale),
            "active_scale": float(style.station_active_marker_scale),
        })
    highlighter.ModelTag = "stationHighlighter"
    sim.AddModelToTask(task, highlighter, 50)


def _add_constraint_cones(cfg, viz, vizSupport, body_name: str) -> None:
    """Show the pointing constraints as cones on the spacecraft body.

    ``incidenceAngle`` is a half-angle measured from the boresight (verified
    against ``constrainedAttitudeManeuver``, which tests violations as
    ``dot(boresight, body) >= cos(Fov)`` and is fed the same value as the cone
    in Basilisk's own example). So the exclusion half-angles go in unchanged,
    and the FOUND field of view -- quoted as a 74 deg full cone -- goes in
    halved.
    """
    sensors = cfg.spacecraft.sensors
    cone_height = float(cfg.mission.vizard.cone_height_m)

    definitions = [
        # (target body, keep-in?, boresight, half angle deg, label)
        ("sun", False, sensors.star_tracker.boresight,
         float(sensors.star_tracker.sun_exclusion_deg),
         "StarTracker/LOST Sun keep-out"),
        ("earth", False, sensors.lost_camera.boresight,
         float(sensors.lost_camera.earth_exclusion_deg),
         "LOST Earth keep-out"),
        ("sun", False, sensors.found_camera.boresight,
         float(sensors.found_camera.sun_exclusion_deg),
         "FOUND Sun keep-out"),
        ("earth", True, sensors.found_camera.boresight,
         float(sensors.found_camera.fov_full_deg) / 2.0,
         "FOUND field of view"),
    ]

    for target, keep_in, boresight, half_angle, label in definitions:
        vizSupport.createConeInOut(
            viz,
            fromBodyName=body_name,
            toBodyName=target,
            coneColor=COLOR_KEEPIN if keep_in else COLOR_KEEPOUT,
            isKeepIn=keep_in,
            normalVector_B=[float(v) for v in boresight],
            incidenceAngle=math.radians(half_angle),
            coneHeight=cone_height,
            coneName=label,
        )
