"""The plotting layer's pure helpers.

Only the parts that decide *what* gets drawn are checked here -- the orbit
split and the run-length grouping the shading is built from. These need no
matplotlib, so they run wherever the rest of the suite does.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from helpers import orbit_env
from hs2sim import conops
from hs2sim.conops import ConopsResult
from hs2sim.config import MissionConfig
from hs2sim.output import timeline


def test_runs_finds_contiguous_blocks():
    values = np.array([1, 1, 2, 2, 2, 1])
    assert timeline.runs(values) == [(0, 2, 1), (2, 5, 2), (5, 6, 1)]
    assert timeline.runs(np.array([])) == []
    assert timeline.runs(np.array([7])) == [(0, 1, 7)]


def test_orbit_segments_split_at_ascending_nodes():
    period, dt = 5580.0, 10.0
    env = orbit_env(int(3.5 * period / dt), dt, period)
    segments = timeline.orbit_segments(env, period)
    # Starting exactly on the node means no leading fragment: three whole
    # orbits and a trailing half.
    assert len(segments) == 4
    for start, stop, _ in segments[:-1]:
        assert (stop - start) * dt == pytest.approx(period, abs=2 * dt)


def test_orbit_segments_backdate_a_partial_first_orbit():
    period, dt = 5580.0, 10.0
    # Start a quarter of the way into an orbit.
    env = orbit_env(int(2.5 * period / dt), dt, period, phase0=math.pi / 2)
    segments = timeline.orbit_segments(env, period)
    start, stop, t_ref = segments[0]
    assert start == 0
    # The epoch is a quarter of an orbit past the node, so the back-dated
    # fragment occupies the last three quarters of the axis -- the phase it was
    # actually flown at -- rather than being slid back to zero.
    minutes = (env.t_s[start:stop] - t_ref) / 60.0
    assert minutes[0] == pytest.approx(0.25 * period / 60.0, abs=0.5)
    assert minutes[-1] == pytest.approx(period / 60.0, abs=0.5)
    assert np.all(minutes <= period / 60.0 + 1e-9)


def test_orbit_segments_fall_back_to_one_axis_when_too_short():
    period, dt = 5580.0, 10.0
    env = orbit_env(40, dt, period)
    assert timeline.orbit_segments(env, period) == [(0, 40, 0.0)]


def test_geometry_names_become_safe_filenames():
    assert timeline._slug("C_2panel_135_plus_body") == "C_2panel_135_plus_body"
    assert timeline._slug("2 panel / 90 deg") == "2_panel_90_deg"
    assert timeline._slug("///") == "geometry"


def flat_timeline(n: int, generation_w: float, load_w: float,
                  soc: float) -> ConopsResult:
    """A scheduler result holding one steady operating point."""
    return ConopsResult(
        mode=np.full(n, conops.MODE_STANDBY, np.int8),
        dcm_BN=np.tile(np.eye(3), (n, 1, 1)),
        generation_w=np.full(n, generation_w), load_w=np.full(n, load_w),
        soc=np.full(n, soc), experiments=np.zeros(n),
        downlinked_bytes=np.zeros(n), queue_bytes=np.zeros(n),
        tracking_rate=np.zeros(n), slew_count=0, slew_seconds=0.0,
        planned_slew_seconds=np.zeros(0), slew_unreachable=0,
        battery_limited=False)


def test_shared_ranges_span_every_geometry():
    """A starved geometry must not be redrawn to fill its own axis."""
    cfg = MissionConfig()
    env = orbit_env(64, 10.0, 5580.0)
    healthy = flat_timeline(64, 20.0, 7.0, 0.99)
    starved = flat_timeline(64, 2.0, 12.0, 0.72)
    ylim, soc_ylim = timeline.shared_ranges(
        cfg, env, {"healthy": healthy, "starved": starved})

    # Both geometries' power balances sit inside the one range.
    assert ylim[0] < -10.0 and ylim[1] > 13.0
    # And the charge range covers both, the floor, and full.
    floor = timeline.floor_percent(cfg)
    assert soc_ylim[0] < min(72.0, floor) and soc_ylim[1] > 99.0


def test_charge_range_keeps_the_floor_in_frame():
    """Even a timeline that never nears the floor must show it."""
    cfg = MissionConfig()
    env = orbit_env(64, 10.0, 5580.0)
    _, soc_ylim = timeline.shared_ranges(
        cfg, env, {"comfortable": flat_timeline(64, 20.0, 7.0, 0.995)})
    assert soc_ylim[0] < timeline.floor_percent(cfg)
    assert soc_ylim[1] > 100.0
