"""Export the CONOPS timeline for playback in Vizard.

The mode scheduler computes the flown attitude in post-processing, so there is
no live Basilisk spacecraft whose state Vizard could record. Instead the
timeline is written to a data file and replayed through Basilisk's stock
``dataFileToViz`` module, which republishes it as spacecraft state messages
that ``vizInterface`` records into a Vizard binary.

What ends up in the scene:

  * the spacecraft flying the actual CONOPS attitude, so you can watch it slew
    between sun-pointing, limb-staring and ground-station tracking;
  * every Leaf Space ground station, with its 10 deg elevation cone;
  * the four pointing constraints as live keep-in / keep-out cones, which
    change colour in Vizard when violated -- the fastest way to sanity-check
    that the attitude solver is doing what it claims.

See ``docs/VIZARD.md`` for how to install Vizard and open the result.
"""

from __future__ import annotations

import math
import pathlib

import numpy as np

from .config import MissionConfig
from .environment import EnvironmentResult

# Vizard colours as RGBA-255.
COLOR_KEEPOUT = [255, 60, 60, 128]
COLOR_KEEPIN = [60, 220, 120, 128]
COLOR_STATION = [255, 200, 0, 255]


def body_rates(dcm_BN: np.ndarray, dt: float) -> np.ndarray:
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
        omega[i] = axis * theta / dt
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
    grav_factory = simIncludeGravBody.gravBodyFactory()
    earth = grav_factory.createEarth()
    earth.isCentralBody = True
    grav_factory.createSun()
    grav_factory.addBodiesTo(sc)

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

    _add_ground_stations(cfg, viz, vizSupport)
    _add_constraint_cones(cfg, viz, vizSupport, sc.ModelTag)

    sim.InitializeSimulation()
    sim.ConfigureStopTime(macros.sec2nano((rows - 1) * dt_out))
    sim.ExecuteSimulation()

    if live_stream:
        return None
    # vizInterface nests recordings in a _VizFiles subdirectory.
    return out_dir / "_VizFiles" / f"{name}_UnityViz.bin"


def _add_ground_stations(cfg: MissionConfig, viz, vizSupport) -> None:
    """Drop every Leaf Space site into the scene with its elevation cone."""
    for station in cfg.stations():
        elevation = float(station.minimum_elevation_deg)
        vizSupport.addLocation(
            viz,
            stationName=str(station.name),
            parentBodyName="earth",
            # Vizard wants the boresight and the half-cone it sweeps. A station
            # with a 10 deg mask sees everything within 80 deg of local zenith.
            lla_GP=[math.radians(float(station.latitude_deg)),
                    math.radians(float(station.longitude_deg)),
                    float(station.altitude_m)],
            gHat_P=[0.0, 0.0, 1.0],
            fieldOfView=math.radians(2.0 * (90.0 - elevation)),
            color=COLOR_STATION,
            range=4000_000.0,
        )


def _add_constraint_cones(cfg, viz, vizSupport, body_name: str) -> None:
    """Show the pointing constraints as live cones.

    Vizard recolours these when the constraint is violated, which makes the
    experiment-mode geometry immediately legible: the +z cones must stay clear
    of both Earth and Sun while the +x cone holds Earth's limb.
    """
    sensors = cfg.spacecraft.sensors
    cone_height = 6.0   # metres in Vizard's spacecraft-scale view

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
