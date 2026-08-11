"""Validate and preview a Vizard recording without opening Vizard.

Vizard is a separate Unity download, and on a machine that cannot fetch it
there is otherwise no way to tell whether a recording is any good. This module
decodes the ``.bin`` directly -- it is a stream of varint-length-prefixed
``VizMessage`` protobufs -- and does two things:

* **checks** the scene against physics: Earth at the origin at the right
  radius, the Sun roughly 1 AU away with a declination inside the obliquity,
  the spacecraft in the right altitude band at the right inclination, the
  attitude a valid MRP set, the ground stations on Earth's surface;
* **renders** a preview of the same data, so the geometry can be eyeballed.

Angles in the file are in degrees: ``vizInterface`` multiplies by R2D on the
way out because Unity expects degrees, even though the Python API takes
radians. Anything reading this file back has to know that.

Usage:
    python -m hs2sim.vizcheck results/_VizFiles/<name>_UnityViz.bin
"""

from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

AU = 1.495978707e11
R_EARTH = 6378136.3
OBLIQUITY_DEG = 23.4392911


def _protobuf_module():
    """Import the generated Vizard protobuf bindings from the Basilisk tree."""
    try:
        import vizMessage_pb2
        return vizMessage_pb2
    except ImportError:
        pass
    import Basilisk
    root = pathlib.Path(Basilisk.__path__[0]).parent.parent
    candidates = list(root.glob("src/utilities/vizProtobuffer")) or \
        list(root.glob("**/vizProtobuffer"))
    for candidate in candidates:
        if (candidate / "vizMessage_pb2.py").exists():
            sys.path.insert(0, str(candidate))
            import vizMessage_pb2
            return vizMessage_pb2
    raise ImportError(
        "vizMessage_pb2.py not found. It is generated when Basilisk is built "
        "with --vizInterface True.")


def decode(path: pathlib.Path) -> list:
    """Decode every frame of a Vizard recording."""
    from google.protobuf.internal.decoder import _DecodeVarint32
    viz = _protobuf_module()

    buf = pathlib.Path(path).read_bytes()
    frames, pos = [], 0
    while pos < len(buf):
        try:
            size, header_end = _DecodeVarint32(buf, pos)
        except Exception:
            break
        chunk = buf[header_end:header_end + size]
        if len(chunk) < size:
            break
        message = viz.VizMessage()
        try:
            message.ParseFromString(chunk)
        except Exception:
            break
        frames.append(message)
        pos = header_end + size
    return frames


def _expected_angles():
    """Sensor angles straight from config, for cross-checking the recording."""
    try:
        from .config import MissionConfig
    except ImportError:
        return None
    sensors = MissionConfig().spacecraft.sensors
    return {
        "cone_half_angles": sorted([
            float(sensors.star_tracker.sun_exclusion_deg),
            float(sensors.lost_camera.earth_exclusion_deg),
            float(sensors.found_camera.sun_exclusion_deg),
            float(sensors.found_camera.fov_full_deg) / 2.0,
        ]),
        "camera_fovs": sorted([float(sensors.lost_camera.fov_full_deg),
                               float(sensors.found_camera.fov_full_deg)]),
    }


def check(frames: list) -> tuple[list[tuple[str, bool, str]], dict]:
    """Run the physical sanity checks. Returns (results, extracted arrays)."""
    first = frames[0]
    bodies = {cb.bodyName: np.array(cb.position) for cb in first.celestialBodies}
    radii = {cb.bodyName: cb.radiusEq for cb in first.celestialBodies}

    sc_r = np.array([np.array(f.spacecraft[0].position)
                     for f in frames if f.spacecraft])
    sc_v = np.array([np.array(f.spacecraft[0].velocity)
                     for f in frames if f.spacecraft])
    sc_sigma = np.array([np.array(f.spacecraft[0].rotation)
                         for f in frames if f.spacecraft])
    sun = np.array([np.array(cb.position) for f in frames
                    for cb in f.celestialBodies if cb.bodyName == "sun"])
    stations = [(loc.stationName, np.array(loc.r_GP_P), loc.fieldOfView,
                 np.array(loc.gHat_P)) for loc in first.locations]
    cones = [(c.coneName, c.toBodyName, c.isKeepIn, c.incidenceAngle,
              np.array(c.normalVector)) for c in first.settings.keepOutInCones]

    expected = _expected_angles()
    cameras = list(first.settings.standardCameraSettings)
    station_records = sum(len(f.locations) for f in frames)

    # Attitude continuity: a slew modelled as an instant snap shows up as a
    # single enormous step between consecutive frames.
    attitude_step_deg = np.array([
        math.degrees(math.acos(float(np.clip(
            (np.trace(_mrp_to_dcm(sc_sigma[i + 1]) @ _mrp_to_dcm(sc_sigma[i]).T)
             - 1.0) / 2.0, -1.0, 1.0))))
        for i in range(len(sc_sigma) - 1)])

    altitude = np.linalg.norm(sc_r, axis=1) - R_EARTH
    h = np.cross(sc_r, sc_v)
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    inclination = np.degrees(np.arccos(np.clip(h[:, 2], -1, 1)))
    sun_dist = np.linalg.norm(sun, axis=1)
    sun_dec = np.degrees(np.arcsin(sun[:, 2] / sun_dist))
    station_radii = np.array([np.linalg.norm(r) for _, r, _, _ in stations])
    # Each station's boresight must be its own local vertical. Getting this
    # wrong (e.g. using the planet spin axis for every site) leaves the markers
    # in the right place but sends every visibility cone the same way.
    boresight_error = np.array([
        math.degrees(math.acos(float(np.clip(
            np.dot(g / np.linalg.norm(g), r / np.linalg.norm(r)), -1, 1))))
        for _, r, _, g in stations])

    results = [
        ("Earth present and at the origin",
         "earth" in bodies and np.linalg.norm(bodies["earth"]) < 1.0,
         f"|r| = {np.linalg.norm(bodies.get('earth', np.zeros(3))):.3f} m"),
        ("Earth radius correct",
         abs(radii.get("earth", 0) - 6378.1366) < 1.0,
         f"{radii.get('earth', 0):.1f} km"),
        ("Sun present at ~1 AU",
         "sun" in bodies and 0.98 < sun_dist.mean() / AU < 1.02,
         f"{sun_dist.mean() / AU:.4f} AU"),
        ("Sun declination within the obliquity",
         np.abs(sun_dec).max() <= OBLIQUITY_DEG + 0.1,
         f"{sun_dec.min():.2f} to {sun_dec.max():.2f} deg"),
        ("Sun is not sitting inside the Earth",
         np.linalg.norm(bodies.get("sun", np.zeros(3))) > 1e10,
         "Sun and Earth are distinct bodies"),
        ("Spacecraft in the ISS altitude band",
         300e3 < altitude.mean() < 500e3,
         f"{altitude.min()/1e3:.1f} - {altitude.max()/1e3:.1f} km"),
        ("Orbit inclination is ISS-like",
         abs(inclination.mean() - 51.64) < 1.0,
         f"{inclination.mean():.2f} deg"),
        ("Attitude is a valid MRP set",
         np.linalg.norm(sc_sigma, axis=1).max() <= 1.0 + 1e-9,
         f"max |sigma| = {np.linalg.norm(sc_sigma, axis=1).max():.4f}"),
        ("Ground stations on Earth's surface",
         station_radii.size > 0 and np.all(np.abs(station_radii - R_EARTH) < 5e3),
         f"{station_radii.min()/1e3:.1f} - {station_radii.max()/1e3:.1f} km"),
        ("Station boresights point at local zenith",
         boresight_error.size > 0 and boresight_error.max() < 1.0,
         f"max deviation {boresight_error.max():.2f} deg from local vertical"),
        ("Constraint cones attached",
         len(cones) == 4,
         f"{len(cones)} cones"),
        # Cone incidenceAngle is a HALF angle (verified against Basilisk's
        # constrainedAttitudeManeuver, which tests dot >= cos(Fov)), so the
        # exclusion half-cones go in unchanged and the full-cone FOV halved.
        ("Cone half-angles match config",
         expected is None or
         sorted(round(c[3], 3) for c in cones) == [round(a, 3) for a in
                                                   expected["cone_half_angles"]],
         ", ".join(f"{c[3]:.1f}" for c in sorted(cones, key=lambda x: x[3]))
         + " deg vs config "
         + (", ".join(f"{a:.1f}" for a in expected["cone_half_angles"])
            if expected else "n/a")),
        # Camera fieldOfView is EDGE-TO-EDGE per the protobuf, so the full-cone
        # FOV goes in unchanged.
        ("Payload cameras match config FOV (edge-to-edge)",
         expected is None or
         sorted(round(c.fieldOfView, 3) for c in cameras) ==
         [round(a, 3) for a in expected["camera_fovs"]],
         ", ".join(f"{c.displayName}={c.fieldOfView:.1f}" for c in cameras)
         or "no cameras"),
        ("Attitude is continuous (no instantaneous repoints)",
         attitude_step_deg.size == 0 or attitude_step_deg.max() < 45.0,
         f"largest step {attitude_step_deg.max():.1f} deg/frame, "
         f"median {np.median(attitude_step_deg):.2f}"),
        ("Ground stations re-highlighted on access changes",
         station_records > len(stations),
         f"{station_records} location records over {len(frames)} frames"),
    ]

    data = {"sc_r": sc_r, "sc_v": sc_v, "sc_sigma": sc_sigma, "sun": sun,
            "stations": stations, "cones": cones, "bodies": bodies}

    # End-to-end check: do the attitudes actually written into the file satisfy
    # the experiment-mode constraints, and for what fraction of the run? Only
    # some frames are experiment mode -- the rest are sun-pointing or slewing --
    # so this is a lower bound on correctness, not a pass/fail on every frame.
    satisfied = experiment_mode_frames(data)
    data["experiment_frames"] = satisfied
    results.append((
        "Experiment-mode attitudes present and legal",
        satisfied.any(),
        f"{satisfied.sum()} of {len(satisfied)} frames "
        f"({100.0 * satisfied.mean():.1f} %) satisfy all four cones"))
    return results, data


def experiment_mode_frames(data: dict) -> np.ndarray:
    """Per-frame boolean: does this attitude satisfy every experiment cone?

    FOUND (+x) must sit on Earth's limb with the Sun more than 70 deg away, and
    the +z sensors must clear both Earth's disc and the Sun by 40 deg.
    """
    sc_r = data["sc_r"]
    sun = data["sun"]
    n = len(sc_r)
    out = np.zeros(n, dtype=bool)
    for i in range(n):
        r = sc_r[i]
        rho = math.degrees(math.asin(R_EARTH / np.linalg.norm(r)))
        nadir = -r / np.linalg.norm(r)
        to_sun = sun[i] - r
        to_sun /= np.linalg.norm(to_sun)
        dcm = _mrp_to_dcm(data["sc_sigma"][i])
        x_body, z_body = dcm[0], dcm[2]
        out[i] = (
            abs(_angle(x_body, nadir) - rho) < 1.0        # FOUND on the limb
            and _angle(x_body, to_sun) > 70.0             # FOUND Sun keep-out
            and _angle(z_body, nadir) > rho + 40.0        # LOST Earth keep-out
            and _angle(z_body, to_sun) > 40.0             # LOST Sun keep-out
        )
    return out


def render(data: dict, out_path: pathlib.Path, frame: int | None = None) -> None:
    """Draw the scene the recording describes: Earth, Sun lighting, orbit.

    Defaults to an experiment-mode frame, since that is the attitude worth
    inspecting -- frame 0 is usually sun-pointing, where the payload
    constraints simply do not apply.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    sc_r = data["sc_r"]
    sun = data["sun"]
    if frame is None:
        experiment = data.get("experiment_frames")
        frame = int(np.argmax(experiment)) if experiment is not None and experiment.any() else 0
    sun_hat = sun[frame] / np.linalg.norm(sun[frame])

    fig = plt.figure(figsize=(13, 6.2))

    # ---- 3D scene -------------------------------------------------------
    ax = fig.add_subplot(121, projection="3d")
    u = np.linspace(0, 2 * np.pi, 120)
    v = np.linspace(0, np.pi, 60)
    xs = np.outer(np.cos(u), np.sin(v))
    ys = np.outer(np.sin(u), np.sin(v))
    zs = np.outer(np.ones_like(u), np.cos(v))

    # Shade the globe by its own solar incidence: this is the terminator, and
    # it is the quickest visual check that the Sun is where it should be.
    illumination = np.clip(xs * sun_hat[0] + ys * sun_hat[1] + zs * sun_hat[2],
                           0, 1)
    ocean = LinearSegmentedColormap.from_list(
        "ocean", ["#05070f", "#0b2545", "#1c5d99", "#4fa3d1", "#bde3f5"])
    radius = R_EARTH / 1e3
    ax.plot_surface(xs * radius, ys * radius, zs * radius,
                    facecolors=ocean(illumination * 0.9 + 0.05),
                    rstride=2, cstride=2, linewidth=0, antialiased=False,
                    shade=False, zorder=1)

    orbit = sc_r / 1e3
    ax.plot(orbit[:, 0], orbit[:, 1], orbit[:, 2], color="#ffb703", lw=0.7,
            alpha=0.85, label="orbit")
    ax.scatter(*orbit[frame], color="#ff206e", s=70, depthshade=False,
               label="spacecraft", zorder=6)

    # matplotlib has no real depth sorting against a surface, so only draw the
    # stations on the hemisphere facing the camera; otherwise far-side markers
    # punch through the globe.
    view_elev, view_azim = 24.0, -58.0
    cam = np.array([
        math.cos(math.radians(view_elev)) * math.cos(math.radians(view_azim)),
        math.cos(math.radians(view_elev)) * math.sin(math.radians(view_azim)),
        math.sin(math.radians(view_elev))])
    shown = 0
    for name, r, _, _ in data["stations"]:
        p = r / 1e3
        if np.dot(p / np.linalg.norm(p), cam) <= 0.10:
            continue
        shown += 1
        ax.scatter(*p, color="#39ff14", s=26, depthshade=False, zorder=6,
                   edgecolors="black", linewidths=0.4,
                   label="ground station" if shown == 1 else None)
    ax.view_init(elev=view_elev, azim=view_azim)

    arrow = sun_hat * radius * 1.9
    ax.quiver(0, 0, 0, *arrow, color="#ffd60a", lw=2.5, arrow_length_ratio=0.12)
    ax.text(*(arrow * 1.06), "to Sun", color="#ffd60a", fontsize=10)

    limit = radius * 1.7
    ax.set_xlim(-limit, limit)
    ax.set_ylim(-limit, limit)
    ax.set_zlim(-limit, limit)
    ax.set_box_aspect((1, 1, 1))
    ax.set_axis_off()
    ax.set_facecolor("black")
    ax.set_title("Scene in the Vizard file: Earth (day/night from the recorded\n"
                 "Sun vector), orbit, spacecraft, and 15 ground stations",
                 fontsize=10)
    ax.legend(loc="upper left", fontsize=8)

    # ---- attitude and constraint check at this instant -------------------
    # Rebuild the body frame from the recorded MRP and confirm each sensor
    # boresight sits where the constraints require.
    sigma = data["sc_sigma"][frame]
    dcm_BN = _mrp_to_dcm(sigma)
    x_body, z_body = dcm_BN[0], dcm_BN[2]

    r = sc_r[frame]
    nadir = -r / np.linalg.norm(r)
    to_sun = sun[frame] - r
    to_sun /= np.linalg.norm(to_sun)
    earth_half_angle = math.degrees(math.asin(R_EARTH / np.linalg.norm(r)))

    ax2 = fig.add_subplot(122, projection="3d")
    for vec, color, label in ((x_body, "#e63946", "+x  FOUND / S-band"),
                              (dcm_BN[1], "#8d99ae", "+y  array hinge"),
                              (z_body, "#2a9d8f", "+z  LOST / star tracker")):
        ax2.quiver(0, 0, 0, *vec, color=color, lw=2.4,
                   arrow_length_ratio=0.15, label=label)
    ax2.quiver(0, 0, 0, *nadir, color="#1c5d99", lw=2.0, ls="--",
               arrow_length_ratio=0.15, label="nadir (Earth centre)")
    ax2.quiver(0, 0, 0, *to_sun, color="#ffd60a", lw=2.0, ls="--",
               arrow_length_ratio=0.15, label="to Sun")

    ax2.set_xlim(-1, 1); ax2.set_ylim(-1, 1); ax2.set_zlim(-1, 1)
    ax2.set_box_aspect((1, 1, 1))
    ax2.set_axis_off()

    angles = {
        "FOUND(+x) off nadir": _angle(x_body, nadir),
        "Earth half-angle": earth_half_angle,
        "FOUND(+x) to Sun": _angle(x_body, to_sun),
        "LOST(+z) off nadir": _angle(z_body, nadir),
        "LOST(+z) to Sun": _angle(z_body, to_sun),
    }
    checks = [
        f"FOUND on the limb: {angles['FOUND(+x) off nadir']:.1f} deg vs "
        f"{earth_half_angle:.1f} deg limb",
        f"FOUND Sun keep-out (>70): {angles['FOUND(+x) to Sun']:.1f} deg",
        f"LOST Earth keep-out (>{earth_half_angle + 40:.0f}): "
        f"{angles['LOST(+z) off nadir']:.1f} deg",
        f"LOST Sun keep-out (>40): {angles['LOST(+z) to Sun']:.1f} deg",
    ]
    ax2.set_title(f"Body frame at frame {frame} (an experiment-mode attitude),\n"
                  "reconstructed from the recorded MRP\n"
                  + "\n".join(checks), fontsize=8.5)
    ax2.legend(loc="upper left", fontsize=7.5)

    fig.tight_layout()
    fig.savefig(out_path, dpi=140, facecolor="white")
    plt.close(fig)


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(math.acos(float(np.clip(np.dot(a, b), -1, 1))))


def _mrp_to_dcm(sigma: np.ndarray) -> np.ndarray:
    """Modified Rodrigues Parameters to a body-from-inertial DCM."""
    s2 = float(np.dot(sigma, sigma))
    tilde = np.array([[0.0, -sigma[2], sigma[1]],
                      [sigma[2], 0.0, -sigma[0]],
                      [-sigma[1], sigma[0], 0.0]])
    return (np.eye(3) + (8.0 * tilde @ tilde - 4.0 * (1.0 - s2) * tilde)
            / (1.0 + s2) ** 2)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = pathlib.Path(argv[1])
    frames = decode(path)
    if not frames:
        print(f"No frames decoded from {path}")
        return 1

    print(f"{path.name}: {path.stat().st_size/1e6:.2f} MB, {len(frames)} frames\n")
    results, data = check(frames)
    width = max(len(name) for name, _, _ in results)
    ok = True
    for name, passed, detail in results:
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name:<{width}}  {detail}")

    print("\n  Constraint cones:")
    for name, body, keep_in, angle, axis in data["cones"]:
        kind = "keep-IN " if keep_in else "keep-OUT"
        print(f"    {kind} {angle:5.1f} deg about {axis.astype(int)} "
              f"vs {body:6s}  {name}")

    out = path.with_suffix(".preview.png")
    try:
        render(data, out)
        print(f"\n  Preview rendered to {out}")
    except Exception as exc:
        print(f"\n  Preview skipped: {exc}")

    print(f"\n{'ALL CHECKS PASSED' if ok else 'SOME CHECKS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
