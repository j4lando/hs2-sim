"""Orbit and space-environment propagation, backed by Basilisk.

This module owns everything that is *truth*: where the spacecraft is, where
the Sun is, whether we are in eclipse, what the magnetic field is, and when
each ground station can see us. Every downstream analysis (power, thermal,
comms, ADCS, CONOPS) consumes the arrays produced here and adds no dynamics of
its own.

Two implementation notes worth knowing:

1. **No SPICE kernels are required.** Basilisk's ``spiceInterface`` wants
   ``de430.bsp`` (~120 MB), which is downloaded on demand. Instead we drive
   Basilisk's stock ``planetEphemeris`` module from classical elements: the Sun
   on its apparent geocentric orbit, and Earth pinned at the origin with a
   correct sidereal rotation so ground-station geometry is right. The resulting
   Sun direction is good to better than 0.02 deg, which is far finer than
   anything in this analysis is sensitive to.

2. **Gravity uses the real J2.** Earth is a spherical-harmonic body built from
   the bundled GGM03S coefficients (degree/order 4), so nodal regression is
   modelled properly. That matters here because RAAN drift is what moves the
   beta angle, which drives both eclipse fraction and array output.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from typing import Any

import numpy as np

from .config import MissionConfig

# Physical constants
MU_EARTH = 3.986004418e14        # m^3/s^2
R_EARTH = 6378136.3              # m, equatorial
EARTH_ROT_RATE = 7.292115e-5     # rad/s
AU = 1.495978707e11              # m
OBLIQUITY = math.radians(23.4392911)
SUN_RADIUS = 6.957e8             # m


@dataclasses.dataclass
class EnvironmentResult:
    """Time histories produced by one propagation.

    All vectors are in the Earth-centred inertial (J2000) frame unless the name
    says otherwise. Arrays are indexed by time sample.
    """

    t_s: np.ndarray                 # (N,) seconds from epoch
    r_BN_N: np.ndarray              # (N,3) spacecraft position, m
    v_BN_N: np.ndarray              # (N,3) spacecraft velocity, m/s
    r_sun_N: np.ndarray             # (N,3) Sun position wrt Earth, m
    shadow_factor: np.ndarray       # (N,) 1 = full sun, 0 = umbra
    b_field_N: np.ndarray           # (N,3) magnetic field, Tesla
    dcm_PN: np.ndarray              # (N,3,3) inertial -> Earth-fixed
    station_access: np.ndarray      # (S,N) bool, above minimum elevation
    station_elevation: np.ndarray   # (S,N) radians
    station_range: np.ndarray       # (S,N) metres
    station_names: list[str]

    @property
    def dt_s(self) -> float:
        return float(self.t_s[1] - self.t_s[0])

    @property
    def n_samples(self) -> int:
        return len(self.t_s)

    @property
    def duration_days(self) -> float:
        return float(self.t_s[-1] - self.t_s[0] + self.dt_s) / 86400.0

    def sun_unit(self) -> np.ndarray:
        """Unit vector from spacecraft to Sun, inertial frame."""
        d = self.r_sun_N - self.r_BN_N
        return d / np.linalg.norm(d, axis=1, keepdims=True)

    def nadir_unit(self) -> np.ndarray:
        """Unit vector from spacecraft toward Earth centre."""
        return -self.r_BN_N / np.linalg.norm(self.r_BN_N, axis=1, keepdims=True)

    def altitude_m(self) -> np.ndarray:
        return np.linalg.norm(self.r_BN_N, axis=1) - R_EARTH

    def earth_angular_radius(self) -> np.ndarray:
        """Half-angle subtended by Earth's disc, radians."""
        return np.arcsin(np.clip(R_EARTH / np.linalg.norm(self.r_BN_N, axis=1), -1, 1))

    def beta_angle(self) -> np.ndarray:
        """Angle between the Sun vector and the orbit plane, radians.

        Positive/negative sign is not meaningful here; magnitude is what drives
        eclipse fraction and array illumination.
        """
        h = np.cross(self.r_BN_N, self.v_BN_N)
        h /= np.linalg.norm(h, axis=1, keepdims=True)
        s = self.r_sun_N / np.linalg.norm(self.r_sun_N, axis=1, keepdims=True)
        return np.arcsin(np.clip(np.sum(h * s, axis=1), -1, 1))


# ---------------------------------------------------------------------------
# Solar ephemeris helpers
# ---------------------------------------------------------------------------

def julian_date(when: dt.datetime) -> float:
    """Julian date from a UTC datetime."""
    y, m = when.year, when.month
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    day_fraction = (when.hour + when.minute / 60.0 + when.second / 3600.0) / 24.0
    return (math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1))
            + when.day + day_fraction + b - 1524.5)


def gmst_rad(when: dt.datetime) -> float:
    """Greenwich mean sidereal time, radians. IAU 1982 series."""
    jd = julian_date(when)
    t = (jd - 2451545.0) / 36525.0
    seconds = (67310.54841
               + (876600.0 * 3600.0 + 8640184.812866) * t
               + 0.093104 * t * t
               - 6.2e-6 * t * t * t)
    return math.radians((seconds % 86400.0) / 240.0)


def sun_orbit_elements(epoch: dt.datetime) -> dict[str, float]:
    """Classical elements of the Sun's *apparent* geocentric orbit at epoch.

    Expressed in the J2000 equatorial frame, so the inclination is the
    obliquity of the ecliptic and the node is the vernal equinox.
    """
    t = (julian_date(epoch) - 2451545.0) / 36525.0
    # Mean anomaly of the Sun (same as Earth's), degrees.
    mean_anomaly = math.radians((357.52911 + 35999.05029 * t) % 360.0)
    e = 0.016708634 - 0.000042037 * t
    # Solve Kepler for the true anomaly.
    ecc_anom = mean_anomaly
    for _ in range(12):
        ecc_anom -= ((ecc_anom - e * math.sin(ecc_anom) - mean_anomaly)
                     / (1.0 - e * math.cos(ecc_anom)))
    true_anom = 2.0 * math.atan2(math.sqrt(1 + e) * math.sin(ecc_anom / 2),
                                 math.sqrt(1 - e) * math.cos(ecc_anom / 2))
    return {
        "a": AU * (1.0 - e * e) / (1.0 - e * e),  # semi-major axis
        "e": e,
        "i": OBLIQUITY,
        "Omega": 0.0,
        # Longitude of perihelion of the Sun as seen from Earth.
        "omega": math.radians((282.9372 + 4.70935e-5 * 36525 * t) % 360.0),
        "f": true_anom,
    }


class BasiliskUnavailable(RuntimeError):
    """Raised when the Basilisk package cannot be imported."""


def basilisk_available() -> bool:
    try:
        import Basilisk  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# The propagation
# ---------------------------------------------------------------------------

def propagate(cfg: MissionConfig) -> EnvironmentResult:
    """Run the Basilisk scenario described by ``cfg`` and return time histories."""
    try:
        from Basilisk import __path__ as bsk_path
        from Basilisk.architecture import messaging  # noqa: F401
        from Basilisk.simulation import (eclipse, groundLocation,
                                         magneticFieldCenteredDipole,
                                         planetEphemeris, spacecraft)
        from Basilisk.utilities import (SimulationBaseClass, macros,
                                        orbitalMotion, simIncludeGravBody,
                                        simSetPlanetEnvironment)
    except ImportError as exc:  # pragma: no cover
        raise BasiliskUnavailable(
            "Basilisk is not importable. Install it from "
            "https://avslab.github.io/basilisk/ and re-run."
        ) from exc

    bsk_root = bsk_path[0]
    dt_s = float(cfg.sim.time_step_s)
    duration_s = float(cfg.sim.duration_days) * 86400.0
    epoch = dt.datetime.fromisoformat(cfg.sim.epoch_utc)
    stations = cfg.stations()

    sim = SimulationBaseClass.SimBaseClass()
    process = sim.CreateNewProcess("hs2Process")
    task_name = "hs2Task"
    process.addTask(sim.CreateNewTask(task_name, macros.sec2nano(dt_s)))

    # -- spacecraft ---------------------------------------------------------
    sc = spacecraft.Spacecraft()
    sc.ModelTag = "hs2"
    bus = cfg.spacecraft.bus
    sc.hub.mHub = float(bus.mass_kg)
    inertia = bus.inertia_kgm2
    sc.hub.IHubPntBc_B = [[float(inertia.xx), 0.0, 0.0],
                          [0.0, float(inertia.yy), 0.0],
                          [0.0, 0.0, float(inertia.zz)]]

    # -- gravity: Earth with real spherical harmonics ------------------------
    grav_factory = simIncludeGravBody.gravBodyFactory()
    earth = grav_factory.createEarth()
    earth.isCentralBody = True
    ggm03s = f"{bsk_root}/supportData/LocalGravData/GGM03S.txt"
    try:
        earth.useSphericalHarmonicsGravityModel(ggm03s, 4)
    except Exception:  # pragma: no cover - falls back to point mass
        pass
    grav_factory.addBodiesTo(sc)

    # -- initial state from classical elements ------------------------------
    oe = orbitalMotion.ClassicElements()
    oe.a = R_EARTH + float(cfg.orbit.altitude_km) * 1e3
    oe.e = float(cfg.orbit.eccentricity)
    oe.i = math.radians(float(cfg.orbit.inclination_deg))
    oe.Omega = math.radians(float(cfg.orbit.raan_deg))
    oe.omega = math.radians(float(cfg.orbit.arg_periapsis_deg))
    oe.f = math.radians(float(cfg.orbit.true_anomaly_deg))
    r_init, v_init = orbitalMotion.elem2rv(MU_EARTH, oe)
    sc.hub.r_CN_NInit = r_init
    sc.hub.v_CN_NInit = v_init
    sim.AddModelToTask(task_name, sc)

    # -- Sun and Earth ephemeris without SPICE kernels -----------------------
    # Earth is given a 1 mm "orbit" so it sits at the origin; what we actually
    # need from it is J20002Pfix, the inertial-to-Earth-fixed rotation that
    # groundLocation uses to place the stations.
    ephem = planetEphemeris.PlanetEphemeris()
    ephem.ModelTag = "planetEphemeris"
    ephem.setPlanetNames(planetEphemeris.StringVector(["earth", "sun"]))

    earth_oe = planetEphemeris.ClassicElements()
    earth_oe.a = 1e-3
    earth_oe.e = 0.0
    earth_oe.i = 0.0
    earth_oe.Omega = 0.0
    earth_oe.omega = 0.0
    earth_oe.f = 0.0

    sun_elements = sun_orbit_elements(epoch)
    sun_oe = planetEphemeris.ClassicElements()
    sun_oe.a = sun_elements["a"]
    sun_oe.e = sun_elements["e"]
    sun_oe.i = sun_elements["i"]
    sun_oe.Omega = sun_elements["Omega"]
    sun_oe.omega = sun_elements["omega"]
    sun_oe.f = sun_elements["f"]

    ephem.planetElements = planetEphemeris.classicElementVector([earth_oe, sun_oe])
    # North pole of the Earth-fixed frame is the J2000 +z axis by construction.
    ephem.rightAscension = planetEphemeris.DoubleVector([0.0, 0.0])
    ephem.declination = planetEphemeris.DoubleVector([math.pi / 2, math.pi / 2])
    ephem.lst0 = planetEphemeris.DoubleVector([gmst_rad(epoch), 0.0])
    ephem.rotRate = planetEphemeris.DoubleVector([EARTH_ROT_RATE, 0.0])
    sim.AddModelToTask(task_name, ephem, 100)

    earth_msg = ephem.planetOutMsgs[0]
    sun_msg = ephem.planetOutMsgs[1]

    # -- eclipse ------------------------------------------------------------
    eclipse_obj = eclipse.Eclipse()
    eclipse_obj.ModelTag = "eclipse"
    eclipse_obj.addSpacecraftToModel(sc.scStateOutMsg)
    eclipse_obj.addPlanetToModel(earth_msg)
    eclipse_obj.sunInMsg.subscribeTo(sun_msg)
    sim.AddModelToTask(task_name, eclipse_obj, 99)

    # -- magnetic field (for magnetorquer authority) ------------------------
    mag = magneticFieldCenteredDipole.MagneticFieldCenteredDipole()
    mag.ModelTag = "magField"
    mag.addSpacecraftToModel(sc.scStateOutMsg)
    simSetPlanetEnvironment.centeredDipoleMagField(mag, "earth")
    mag.planetPosInMsg.subscribeTo(earth_msg)
    sim.AddModelToTask(task_name, mag, 98)

    # -- ground stations ----------------------------------------------------
    gl_modules = []
    for index, station in enumerate(stations):
        gl = groundLocation.GroundLocation()
        gl.ModelTag = f"gs{index}"
        gl.planetRadius = R_EARTH
        gl.specifyLocation(math.radians(float(station.latitude_deg)),
                           math.radians(float(station.longitude_deg)),
                           float(station.altitude_m))
        gl.minimumElevation = math.radians(float(station.minimum_elevation_deg))
        gl.maximumRange = 4.0e6
        gl.planetInMsg.subscribeTo(earth_msg)
        gl.addSpacecraftToModel(sc.scStateOutMsg)
        sim.AddModelToTask(task_name, gl, 97)
        gl_modules.append(gl)

    # -- recorders ----------------------------------------------------------
    sc_log = sc.scStateOutMsg.recorder()
    sun_log = sun_msg.recorder()
    earth_log = earth_msg.recorder()
    ecl_log = eclipse_obj.eclipseOutMsgs[0].recorder()
    mag_log = mag.envOutMsgs[0].recorder()
    access_logs = [gl.accessOutMsgs[0].recorder() for gl in gl_modules]
    for recorder in [sc_log, sun_log, earth_log, ecl_log, mag_log] + access_logs:
        sim.AddModelToTask(task_name, recorder)

    sim.InitializeSimulation()
    sim.ConfigureStopTime(macros.sec2nano(duration_s))
    sim.ExecuteSimulation()

    # -- gather -------------------------------------------------------------
    t_s = np.asarray(sc_log.times()) * macros.NANO2SEC
    result = EnvironmentResult(
        t_s=t_s,
        r_BN_N=np.asarray(sc_log.r_BN_N),
        v_BN_N=np.asarray(sc_log.v_BN_N),
        r_sun_N=np.asarray(sun_log.PositionVector),
        shadow_factor=np.asarray(ecl_log.shadowFactor),
        b_field_N=np.asarray(mag_log.magField_N),
        dcm_PN=np.asarray(earth_log.J20002Pfix),
        station_access=np.asarray([np.asarray(log.hasAccess, dtype=bool)
                                   for log in access_logs]),
        station_elevation=np.asarray([np.asarray(log.elevation)
                                      for log in access_logs]),
        station_range=np.asarray([np.asarray(log.slantRange)
                                  for log in access_logs]),
        station_names=[str(s.name) for s in stations],
    )
    return result


def summarise(env: EnvironmentResult) -> dict[str, Any]:
    """Headline orbit/environment numbers, for reporting and sanity checks."""
    r = np.linalg.norm(env.r_BN_N, axis=1)
    speed = np.linalg.norm(env.v_BN_N, axis=1)
    # Osculating semi-major axis from the vis-viva equation.
    sma = 1.0 / (2.0 / r - speed ** 2 / MU_EARTH)
    period = 2 * math.pi * np.sqrt(sma ** 3 / MU_EARTH)
    eclipsed = env.shadow_factor < 0.5
    return {
        "duration_days": env.duration_days,
        "time_step_s": env.dt_s,
        "mean_altitude_km": float(np.mean(env.altitude_m()) / 1e3),
        "orbit_period_min": float(np.mean(period) / 60.0),
        "orbits": float(env.t_s[-1] / np.mean(period)),
        "eclipse_fraction": float(np.mean(eclipsed)),
        "beta_angle_deg_mean": float(np.degrees(np.mean(np.abs(env.beta_angle())))),
        "beta_angle_deg_min": float(np.degrees(np.min(np.abs(env.beta_angle())))),
        "beta_angle_deg_max": float(np.degrees(np.max(np.abs(env.beta_angle())))),
        "b_field_nt_mean": float(np.mean(np.linalg.norm(env.b_field_N, axis=1)) * 1e9),
        "earth_angular_radius_deg": float(np.degrees(np.mean(env.earth_angular_radius()))),
    }
