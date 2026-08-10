"""Figures for the HS-2 analysis. Silently no-ops if matplotlib is absent."""

from __future__ import annotations

import pathlib

import numpy as np

from .config import MissionConfig
from .environment import EnvironmentResult


def make_all(cfg: MissionConfig, env: EnvironmentResult,
             results: dict, out_dir: pathlib.Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(exist_ok=True)

    # -- ground track with station visibility circles ------------------------
    fig, ax = plt.subplots(figsize=(11, 5.5))
    dcm = env.dcm_PN
    r_fixed = np.einsum("nij,nj->ni", dcm, env.r_BN_N)
    lat = np.degrees(np.arcsin(np.clip(r_fixed[:, 2]
                                       / np.linalg.norm(r_fixed, axis=1), -1, 1)))
    lon = np.degrees(np.arctan2(r_fixed[:, 1], r_fixed[:, 0]))
    jump = np.abs(np.diff(lon)) > 180
    lon_plot = lon.astype(float).copy()
    lon_plot[:-1][jump] = np.nan
    ax.plot(lon_plot, lat, lw=0.4, color="tab:blue", alpha=0.7, label="ground track")
    for station in cfg.stations():
        ax.plot(float(station.longitude_deg), float(station.latitude_deg),
                "r^", ms=7)
        ax.annotate(str(station.name).split(",")[0],
                    (float(station.longitude_deg), float(station.latitude_deg)),
                    fontsize=6, xytext=(3, 3), textcoords="offset points")
    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)
    ax.set_xlabel("Longitude (deg)")
    ax.set_ylabel("Latitude (deg)")
    ax.set_title("HS-2 ground track and Leaf Space stations "
                 "(station coordinates approximate)")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "ground_track.png", dpi=140)
    plt.close(fig)

    # -- per-face illumination ----------------------------------------------
    first_name = next(iter(results["geometries"]))
    thermal_data = results["geometries"][first_name]["thermal"]
    faces = list(thermal_data)
    solar = [thermal_data[f]["mean_solar_flux_w_m2"] for f in faces]
    albedo = [thermal_data[f]["mean_albedo_flux_w_m2"] for f in faces]
    ir = [thermal_data[f]["mean_ir_flux_w_m2"] for f in faces]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(faces))
    ax.bar(x, solar, label="direct solar", color="#e8a33d")
    ax.bar(x, albedo, bottom=solar, label="albedo", color="#7fb3d5")
    ax.bar(x, ir, bottom=np.array(solar) + np.array(albedo),
           label="Earth IR", color="#c0554e")
    ax.set_xticks(x)
    ax.set_xticklabels(faces)
    ax.set_ylabel("Mean absorbed flux (W/m$^2$)")
    ax.set_title(f"Time-averaged illumination per face ({first_name})")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "face_illumination.png", dpi=140)
    plt.close(fig)

    # -- array geometry comparison ------------------------------------------
    names = list(results["geometries"])
    peak = [results["geometries"][n]["peak_total_w"] for n in names]
    standby = [results["geometries"][n]["power_standby"]["orbit_average_w"]
               for n in names]
    experiment = [results["geometries"][n]["power_experiment"]["orbit_average_w"]
                  for n in names]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(names))
    width = 0.27
    ax.bar(x - width, peak, width, label="peak (no cosine loss)", color="#b0b0b0")
    ax.bar(x, standby, width, label="orbit avg, sun-pointing", color="#3d7ea8")
    ax.bar(x + width, experiment, width, label="orbit avg, experiment attitude",
           color="#4e9a51")
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=8)
    ax.set_ylabel("Power (W)")
    ax.set_title("Solar array geometry trade")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "array_trade.png", dpi=140)
    plt.close(fig)

    # -- beta / eclipse sweep ------------------------------------------------
    if "raan_sweep" in results:
        rows = results["raan_sweep"]
        beta = [r["beta_deg"] for r in rows]
        order = np.argsort(beta)
        beta = np.array(beta)[order]
        eclipse = np.array([r["eclipse_fraction"] * 100 for r in rows])[order]
        gen = np.array([r["orbit_average_w"] for r in rows])[order]

        fig, ax1 = plt.subplots(figsize=(7.5, 4.5))
        ax1.plot(beta, eclipse, "o-", color="#3d5a80", label="eclipse fraction")
        ax1.set_xlabel("Beta angle (deg)")
        ax1.set_ylabel("Eclipse fraction (%)", color="#3d5a80")
        ax1.grid(alpha=0.3)
        ax2 = ax1.twinx()
        ax2.plot(beta, gen, "s--", color="#ee6c4d", label="orbit-average power")
        ax2.set_ylabel("Orbit-average power (W)", color="#ee6c4d")
        ax1.set_title("Beta angle drives eclipse time and array output")
        fig.tight_layout()
        fig.savefig(out_dir / "beta_sweep.png", dpi=140)
        plt.close(fig)

    # -- payload rate wall ---------------------------------------------------
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    for name in names:
        sweep = results["geometries"][name]["payload_rate_sweep"]
        requested = [r["requested_rate_hz"] for r in sweep]
        achieved = [r["images_per_day"] for r in sweep]
        ax.plot(requested, achieved, "o-", label=name)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Requested experiment rate (Hz)")
    ax.set_ylabel("Images per day achieved")
    ax.set_title("Where the payload cadence saturates")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "payload_rate.png", dpi=140)
    plt.close(fig)
