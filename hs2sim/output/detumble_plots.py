"""Figures for the detumble / sun-acquisition Monte Carlo.

Every chart here compares the sun sensor geometries against each other, so the
geometry is the shared encoding and takes the categorical palette slots in a
fixed order -- the same discipline ``style`` applies to the CONOPS mode
colours. Per-trial traces are drawn as a median line inside a percentile band
rather than as a spaghetti plot: with a couple of hundred trials the spaghetti
is ink, not information, and the band is what the reader is actually after.
"""

from __future__ import annotations

import pathlib

import numpy as np

# Categorical slots, assigned to geometries in a fixed order so a geometry
# keeps its colour across every figure in the set.
GEOMETRY_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#8c5ad6"]
INK = "#0b0b0b"
INK_MUTED = "#898781"
BAND_ALPHA = 0.18
LIMIT_LINE = "#d03b3b"


def _colours(names) -> dict[str, str]:
    return {name: GEOMETRY_COLOURS[i % len(GEOMETRY_COLOURS)]
            for i, name in enumerate(names)}


def _band(ax, t_s, values, colour, label, lo=10, hi=90):
    """Median line with a percentile band, in minutes."""
    minutes = t_s / 60.0
    ax.fill_between(minutes, np.percentile(values, lo, axis=1),
                    np.percentile(values, hi, axis=1),
                    color=colour, alpha=BAND_ALPHA, linewidth=0)
    ax.plot(minutes, np.median(values, axis=1), color=colour, lw=1.6, label=label)


def rate_decay(runs, out_dir: pathlib.Path, plt) -> None:
    """Body rate against time: the detumble itself.

    Log scale, because the rate falls through two orders of magnitude and a
    linear axis would show the first two minutes and nothing else.
    """
    colours = _colours(runs)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for name, run in runs.items():
        _band(ax, run.t_s, run.rate_deg_s, colours[name], name)
    threshold = 1.0
    ax.axhline(threshold, color=LIMIT_LINE, lw=1.0, ls="--")
    ax.annotate("detumbled", (0.99, threshold), xycoords=("axes fraction", "data"),
                ha="right", va="bottom", fontsize=8, color=LIMIT_LINE)
    ax.set_yscale("log")
    ax.set_xlabel("Time since deployment (min)")
    ax.set_ylabel("Body rate magnitude (deg/s)")
    ax.set_title("Detumble: median and 10-90 % band over the Monte Carlo")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(out_dir / "detumble_rate.png", dpi=140)
    plt.close(fig)


def detumble_cdf(runs, out_dir: pathlib.Path, plt) -> None:
    """Cumulative distribution of the time to detumble.

    The distribution matters more than its median: the tail is what sets how
    long the operators have to wait before the vehicle is usable, and it is
    driven by the field geometry at deployment rather than by the initial rate.
    """
    colours = _colours(runs)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    for name, run in runs.items():
        for ax, key, title in (
                (axes[0], "detumble_time_s", "Time to detumble"),
                (axes[1], "sun_acquire_time_s", "Time to acquire the Sun")):
            values = run.per_trial[key]
            finite = np.sort(values[np.isfinite(values)]) / 60.0
            if finite.size == 0:
                continue
            # Fraction of ALL trials, so a geometry that never converges shows
            # a curve that stops short instead of a full one.
            fraction = np.arange(1, finite.size + 1) / len(values)
            ax.step(finite, fraction, where="post", color=colours[name],
                    lw=1.6, label=name)
            ax.set_title(title)
    for ax in axes:
        ax.set_xlabel("Minutes since deployment")
        ax.set_ylabel("Fraction of trials")
        ax.set_ylim(0, 1.02)
        ax.grid(alpha=0.2)
    # A geometry that never converges contributes no line, so there is not
    # always anything to put a legend on.
    if axes[0].get_legend_handles_labels()[0]:
        axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(out_dir / "detumble_time_cdf.png", dpi=140)
    plt.close(fig)


def power_capture(runs, out_dir: pathlib.Path, plt) -> None:
    """Array output against time, as a fraction of what the array could make.

    Normalised by the best any attitude can reach, so the ceiling is 1.0 and
    the gap to it is the controller's, not the array's.
    """
    colours = _colours(runs)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for name, run in runs.items():
        # A quartile band, not 10-90: three overlapping wide bands is mud, and
        # the instantaneous spread across trials at different orbit phases is
        # genuinely near full scale. The per-trial distribution is the
        # steady-state figure's job.
        _band(ax, run.t_s, run.capture_sunlit / run.best_capture,
              colours[name], name, lo=25, hi=75)
    ax.axhline(1.0, color=INK_MUTED, lw=1.0, ls=":")
    ax.annotate("best any attitude can do", (0.99, 1.0),
                xycoords=("axes fraction", "data"), ha="right", va="bottom",
                fontsize=8, color=INK_MUTED)
    ax.set_ylim(0, 1.15)
    ax.set_xlabel("Time since deployment (min)")
    ax.set_ylabel("Array output / best achievable")
    ax.set_title("Sun acquisition, sunlit potential (eclipse excluded)")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(out_dir / "detumble_power_capture.png", dpi=140)
    plt.close(fig)


def sun_estimate_error(runs, out_dir: pathlib.Path, plt) -> None:
    """Where the sun sensors think the Sun is, versus where it is.

    Two panels because there are two different errors and mixing them hides
    the trade. The left is the full 3-D error, which a coplanar layout can
    never win: it cannot see the component of the Sun vector along z. The
    right is the error inside the subspace each layout CAN see, which is the
    part driven by noise, albedo and channel gain spread rather than by rank.
    """
    colours = _colours(runs)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    for name, run in runs.items():
        lit = run.shadow > 0.5
        for ax, values in ((axes[0], run.est_error_deg),
                           (axes[1], run.est_inplane_error_deg)):
            usable = np.where(lit & run.sun_valid, values, np.nan).ravel()
            usable = usable[np.isfinite(usable)]
            if usable.size == 0:
                continue
            ax.hist(usable, bins=60, range=(0, 90), density=True,
                    histtype="step", color=colours[name], lw=1.5, label=name)
    axes[0].set_title("Full 3-D Sun vector error")
    axes[1].set_title("Error within the subspace the layout can see")
    for ax in axes:
        ax.set_xlabel("Error (deg)")
        ax.grid(alpha=0.2)
    axes[0].set_ylabel("Density (sunlit samples with a valid fix)")
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "detumble_sun_error.png", dpi=140)
    plt.close(fig)


def sky_coverage(results, out_dir: pathlib.Path, plt) -> None:
    """What each layout can see, before any dynamics are involved.

    Two panels, because a layout has to answer two separate questions and the
    three geometries answer them differently. Left: how much of the sky lights
    enough channels to solve at all, and enough to solve in three dimensions.
    Right: how well conditioned that solve is, in degrees, by pushing 1 % of a
    normal-incidence reading through it.

    The right panel is the whole case against the canted layout. It lights
    exactly as much sky as the orthogonal four-face set -- both are two
    antipodal pairs, so one of each pair is always lit -- but two of its
    normals sit 45 deg apart, so over the sky directions falling between the
    pairs it is solving for a direction from what is effectively one useful
    reading.
    """
    coverage = results.get("sky_coverage") or {}
    if not coverage:
        return
    names = list(coverage)
    colours = _colours(names)
    width = 0.8 / len(names)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    lit_metrics = [("fraction_two_or_more_lit", "2+ channels lit\n(a fix is possible)"),
                   ("fraction_three_or_more_lit", "3+ channels lit\n(a 3-D fix is possible)")]
    for index, name in enumerate(names):
        offsets = np.arange(len(lit_metrics)) + (index - (len(names) - 1) / 2) * width
        values = [coverage[name][key] for key, _ in lit_metrics]
        axes[0].bar(offsets, values, width, color=colours[name], label=name)
        for x, value in zip(offsets, values):
            axes[0].annotate(f"{value:.2f}", (x, value), ha="center",
                             va="bottom", fontsize=7, color=INK)
    axes[0].set_xticks(np.arange(len(lit_metrics)))
    axes[0].set_xticklabels([label for _, label in lit_metrics], fontsize=8)
    axes[0].set_ylabel("Fraction of the sky")
    axes[0].set_ylim(0, 1.15)
    axes[0].set_title("Coverage", fontsize=10)
    axes[0].legend(frameon=False, fontsize=8, loc="upper right")

    error_metrics = [("one_percent_noise_error_median_deg", "median"),
                     ("one_percent_noise_error_p95_deg", "95th percentile")]
    for index, name in enumerate(names):
        offsets = np.arange(len(error_metrics)) + (index - (len(names) - 1) / 2) * width
        values = [coverage[name][key] for key, _ in error_metrics]
        axes[1].bar(offsets, values, width, color=colours[name])
        for x, value in zip(offsets, values):
            axes[1].annotate(f"{value:.2f}", (x, value), ha="center",
                             va="bottom", fontsize=7, color=INK)
    axes[1].set_xticks(np.arange(len(error_metrics)))
    axes[1].set_xticklabels([label for _, label in error_metrics], fontsize=8)
    axes[1].set_ylabel("Direction error (deg)")
    axes[1].set_title("Conditioning: 1 % reading noise, in degrees", fontsize=10)

    for ax in axes:
        ax.grid(alpha=0.2, axis="y")
    fig.suptitle("Sun sensor layouts, geometry only -- no dynamics, no albedo",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(out_dir / "detumble_sky_coverage.png", dpi=140)
    plt.close(fig)


def steady_state_summary(runs, out_dir: pathlib.Path, plt) -> None:
    """Where each geometry ends up, over the last orbit of every trial.

    Box plots rather than bars: the question a Monte Carlo is asked is how bad
    the bad trials are, and a bar of medians cannot answer it.
    """
    names = list(runs)
    colours = _colours(names)
    panels = [("steady_capture_normalised", "Array output / best achievable"),
              ("steady_sun_error_deg", "Array axis to Sun (deg)"),
              ("sun_fix_availability", "Sunlit samples with a valid fix"),
              ("mean_dipole_fraction", "Mean dipole used / available")]

    fig, axes = plt.subplots(1, len(panels), figsize=(13, 4.4))
    for ax, (key, label) in zip(axes, panels):
        data = [runs[name].per_trial[key] for name in names]
        data = [d[np.isfinite(d)] for d in data]
        boxes = ax.boxplot(data, patch_artist=True, widths=0.6,
                           medianprops={"color": INK, "linewidth": 1.4},
                           flierprops={"marker": ".", "markersize": 3,
                                       "markerfacecolor": INK_MUTED,
                                       "markeredgecolor": "none"})
        for patch, name in zip(boxes["boxes"], names):
            patch.set_facecolor(colours[name])
            patch.set_alpha(0.45)
            patch.set_edgecolor(colours[name])
        ax.set_xticks(np.arange(1, len(names) + 1))
        ax.set_xticklabels(names, rotation=20, ha="right", fontsize=7)
        ax.set_title(label, fontsize=9)
        ax.grid(alpha=0.2, axis="y")
    fig.suptitle("Steady state over the final orbit of each trial", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_dir / "detumble_steady_state.png", dpi=140)
    plt.close(fig)


def make_all(runs, results, out_dir: pathlib.Path, log=None) -> None:
    """Draw every detumble figure into ``out_dir``."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(exist_ok=True)
    if not runs:
        return
    for drawer in (rate_decay, detumble_cdf, power_capture, sun_estimate_error,
                   steady_state_summary):
        drawer(runs, out_dir, plt)
    sky_coverage(results, out_dir, plt)
    if log is not None:
        log(f"wrote detumble figures to {out_dir}")
