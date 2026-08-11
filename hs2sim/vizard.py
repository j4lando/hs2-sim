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
  * the four pointing constraints as live keep-in / keep-out cones. Vizard
    draws a cone translucent when its condition is satisfied and solid when it
    is violated. Note the cones are always present, while the constraints only
    apply in experiment mode -- read the Mode gauge before judging one;
  * the CONOPS telemetry on Vizard's gauges: battery, payload storage,
    temperature and the current mode, plus an S-band transceiver that animates
    during downlink passes.

See ``docs/VIZARD.md`` for how to install Vizard and open the result.
"""

from __future__ import annotations

import datetime as dt
import math
import pathlib

import numpy as np

from . import environment
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


MODE_COLORS = [
    [150, 150, 150, 255],   # 0 safe
    [70, 130, 200, 255],    # 1 standby   (sun-pointing, charging)
    [230, 160, 40, 255],    # 2 slew
    [80, 200, 100, 255],    # 3 experiment
    [220, 70, 200, 255],    # 4 downlink
]


class _TelemetryPlayback:
    """Publishes the recorded CONOPS telemetry into Vizard's gauges.

    Built lazily so importing this module does not require Basilisk. Vizard
    reads battery and data-storage gauges from Basilisk messages, and takes the
    value directly off the struct for gauges with no input message linked --
    which is how the temperature and mode indicators are driven here.
    """

    def __new__(cls, *args, **kwargs):  # pragma: no cover - thin factory
        from Basilisk.architecture import sysModel

        class Impl(sysModel.SysModel):
            def __init__(self, telemetry, dt_out, gauges, transceiver,
                         battery_msg, data_msg, capacity_j, storage_capacity_b):
                super().__init__()
                self.telemetry = telemetry
                self.dt_out = dt_out
                self.gauges = gauges
                self.transceiver = transceiver
                self.battery_msg = battery_msg
                self.data_msg = data_msg
                self.capacity_j = capacity_j
                self.storage_capacity_b = storage_capacity_b

            def UpdateState(self, CurrentSimNanos):
                from Basilisk.architecture import messaging

                index = min(int(round(CurrentSimNanos * 1e-9 / self.dt_out)),
                            len(self.telemetry["soc"]) - 1)

                battery = messaging.PowerStorageStatusMsgPayload()
                battery.storageLevel = float(
                    self.telemetry["soc"][index]) * self.capacity_j
                battery.storageCapacity = self.capacity_j
                battery.currentNetPower = float(self.telemetry["net_w"][index])
                self.battery_msg.write(battery, CurrentSimNanos, self.moduleID)

                data = messaging.DataStorageStatusMsgPayload()
                data.storageLevel = float(self.telemetry["stored_bytes"][index])
                data.storageCapacity = self.storage_capacity_b
                self.data_msg.write(data, CurrentSimNanos, self.moduleID)

                # No input message on these two, so Vizard uses the struct value.
                self.gauges["temperature"].currentValue = float(
                    self.telemetry["temperature_c"][index]
                    - self.telemetry["temp_floor_c"])
                mode = int(self.telemetry["mode"][index])
                self.gauges["mode"].currentValue = mode + 0.5

                if self.transceiver is not None:
                    # 1 = sending, 2 = receiving. The receiver is always on.
                    self.transceiver.transceiverState = 1 if mode == 4 else 2

        return Impl(*args, **kwargs)


def export(cfg: MissionConfig,
           env: EnvironmentResult,
           dcm_BN: np.ndarray,
           out_dir: pathlib.Path,
           name: str = "hs2_conops",
           stride: int = 1,
           live_stream: bool = False,
           telemetry: dict | None = None) -> pathlib.Path | None:
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

    gauges, transceiver, playback = _build_telemetry(
        cfg, sim, task, telemetry, dt_out, stride)

    save_file = None if live_stream else str(out_dir / name)
    viz = vizSupport.enableUnityVisualization(
        sim, task, [sc], saveFile=save_file, liveStream=live_stream,
        genericStorageList=[list(gauges.values())] if gauges else None,
        transceiverList=[[transceiver]] if transceiver else None)

    if gauges:
        vizSupport.setInstrumentGuiSetting(viz, spacecraftName=sc.ModelTag,
                                           showGenericStoragePanel=1,
                                           showTransceiverLabels=1)

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


def _build_telemetry(cfg, sim, task, telemetry, dt_out, stride):
    """Create the Vizard gauges and the module that drives them each step."""
    if not telemetry:
        return {}, None, None

    from Basilisk.architecture import messaging
    from Basilisk.simulation import vizInterface

    battery_cfg = cfg.spacecraft.battery
    limits = cfg.spacecraft.thermal.limits_c
    capacity_j = float(battery_cfg.capacity_wh) * 3600.0
    floor_pct = int(round(100 * (1.0 - float(battery_cfg.depth_of_discharge_limit))))
    storage_capacity_b = float(cfg.payload.storage_gb) * 1e9

    battery_gauge = vizInterface.GenericStorage()
    battery_gauge.label = "Battery"
    battery_gauge.units = "J"
    battery_gauge.maxValue = capacity_j
    # Red below the depth-of-discharge floor, amber approaching it, else green.
    battery_gauge.color = vizInterface.IntVector(
        [200, 60, 60, 255] + [230, 170, 40, 255] + [80, 200, 100, 255])
    battery_gauge.thresholds = vizInterface.IntVector(
        [floor_pct, min(99, floor_pct + 15)])

    data_gauge = vizInterface.GenericStorage()
    data_gauge.label = "Payload storage"
    data_gauge.units = "bytes"
    data_gauge.maxValue = storage_capacity_b
    data_gauge.color = vizInterface.IntVector(
        [80, 160, 220, 255] + [230, 170, 40, 255] + [200, 60, 60, 255])
    data_gauge.thresholds = vizInterface.IntVector([70, 90])

    # Vizard gauges start at zero, so temperature is shown as degrees above the
    # electronics cold limit; the label says so.
    temp_floor = float(limits.electronics_min)
    temp_span = float(limits.electronics_max) - temp_floor
    temp_gauge = vizInterface.GenericStorage()
    temp_gauge.label = f"Temperature (0 = {temp_floor:.0f} C)"
    temp_gauge.units = "degC above min"
    temp_gauge.maxValue = temp_span
    battery_cold = (float(limits.battery_min) - temp_floor) / temp_span * 100
    battery_hot = (float(limits.battery_max) - temp_floor) / temp_span * 100
    temp_gauge.color = vizInterface.IntVector(
        [90, 150, 255, 255] + [80, 200, 100, 255] + [220, 90, 60, 255])
    temp_gauge.thresholds = vizInterface.IntVector(
        [int(round(battery_cold)), int(round(battery_hot))])

    mode_gauge = vizInterface.GenericStorage()
    mode_gauge.label = "Mode: safe|standby|slew|experiment|downlink"
    mode_gauge.units = "mode"
    mode_gauge.maxValue = 5.0
    mode_gauge.color = vizInterface.IntVector(
        [c for colour in MODE_COLORS for c in colour])
    mode_gauge.thresholds = vizInterface.IntVector([20, 40, 60, 80])

    gauges = {"battery": battery_gauge, "data": data_gauge,
              "temperature": temp_gauge, "mode": mode_gauge}

    battery_msg = messaging.PowerStorageStatusMsg()
    data_msg = messaging.DataStorageStatusMsg()
    # SWIG hands back a *copy* of these struct members, so subscribing on the
    # attribute in place silently does nothing and the gauge reads zero
    # forever. Subscribe on a local and assign the member back.
    battery_reader = battery_gauge.batteryStateInMsg
    battery_reader.subscribeTo(battery_msg)
    battery_gauge.batteryStateInMsg = battery_reader

    data_reader = data_gauge.dataStorageStateInMsg
    data_reader.subscribeTo(data_msg)
    data_gauge.dataStorageStateInMsg = data_reader

    transceiver = vizInterface.Transceiver()
    transceiver.label = "S-band"
    transceiver.normalVector = [1.0, 0.0, 0.0]     # +x patch
    transceiver.r_SB_B = [0.05, 0.0, 0.0]
    transceiver.fieldOfView = math.radians(100.0)  # patch beamwidth
    transceiver.transceiverState = 0

    playback = _TelemetryPlayback(telemetry, dt_out, gauges, transceiver,
                                  battery_msg, data_msg, capacity_j,
                                  storage_capacity_b)
    playback.ModelTag = "telemetryPlayback"
    sim.AddModelToTask(task, playback, 50)
    return gauges, transceiver, playback


def _add_ground_stations(cfg: MissionConfig, viz, vizSupport) -> None:
    """Drop every Leaf Space site into the scene with its elevation cone."""
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
    # Cone height is in metres, at Earth scale. A few metres makes the cones
    # invisible next to a 6378 km planet, so draw them long enough to reach the
    # limb -- that is what makes "is Earth inside this cone?" legible on screen.
    altitude = float(cfg.orbit.altitude_km) * 1e3
    cone_height = 2.5 * altitude

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


def decimate(telemetry: dict, stride: int) -> dict:
    """Subsample telemetry series to match a strided trajectory export."""
    stride = max(1, int(stride))
    out = {}
    for key, value in telemetry.items():
        out[key] = value[::stride] if isinstance(value, np.ndarray) else value
    return out
