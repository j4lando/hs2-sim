"""The interactive HTML timeline: payload shape and honest gaps."""

from __future__ import annotations

import json
import re

import numpy as np

from helpers import orbit_env
from hs2sim import conops, geometry, power
from hs2sim.config import MissionConfig
from hs2sim.output import dashboard


def a_run(cfg, n=700, dt=10.0, period=5580.0):
    env = orbit_env(n, dt, period)
    env.shadow_factor[:] = 1.0
    ang = 2 * np.pi * env.t_s / period
    env.b_field_N = 3.5e-5 * np.stack(
        [np.cos(ang), np.sin(ang), 0.3 * np.ones_like(ang)], axis=1)
    env.station_range[0, :] = 800e3
    from hs2sim import adcs
    array = power.all_array_geometries(cfg)[0]
    standby = np.tile(np.eye(3), (n, 1, 1))
    pointing = geometry.PointingResult(
        feasible=np.zeros(n, bool), dcm_BN=standby.copy(),
        x_axis_N=np.tile([1.0, 0, 0], (n, 1)),
        z_axis_N=np.tile([0, 0, 1.0], (n, 1)),
        roll_used=np.zeros(n), array_power_frac=np.zeros(n),
        reject_reason=np.zeros(n, int))
    flown = conops.simulate(cfg, env, array, pointing, standby,
                            adcs.torque_authority(cfg, env), 0.2, [])
    results = {
        "orbit": {"orbit_period_min": period / 60.0, "eclipse_fraction": 0.0},
        "comms": {"aggregate": {"passes_per_day": 0.0}},
        "geometries": {array.name: {"description": array.description,
                                    "conops_baseline": conops.summarise(
                                        cfg, env, flown)}},
    }
    return env, results, {array.name: flown}


def embedded(path):
    """The inlined payload, parsed back out of the page."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"const DATA = (\{.*?\});\n", text, re.S)
    assert match, "no data payload found in the page"
    return json.loads(match.group(1))


def test_the_page_is_self_contained(tmp_path):
    cfg = MissionConfig()
    env, results, timelines = a_run(cfg)
    path = dashboard.build(cfg, env, results, timelines, tmp_path)
    text = path.read_text(encoding="utf-8")

    assert path.name == "mission_dashboard.html"
    assert "/*__DATA__*/null" not in text, "the payload placeholder survived"
    # Nothing may be fetched: the page has to open from disk with no network.
    assert not re.search(r'\ssrc\s*=\s*["\']http', text)
    assert not re.search(r'<link[^>]+href\s*=\s*["\']http', text)


def test_every_series_is_on_the_shared_grid(tmp_path):
    cfg = MissionConfig()
    env, results, timelines = a_run(cfg)
    data = embedded(dashboard.build(cfg, env, results, timelines, tmp_path))

    grid = data["meta"]["grid"]
    assert len(grid) == dashboard.GRID_POINTS
    for entry in data["geometries"].values():
        assert entry["orbits"], "no orbits in the payload"
        for orbit in entry["orbits"]:
            for key in ("gen", "load", "soc", "mode", "queue", "stored",
                        "link", "eclipse", "access"):
                assert len(orbit[key]) == len(grid), f"{key} off the grid"


def test_a_partial_orbit_is_left_as_a_gap(tmp_path):
    """The run ends mid-orbit; that stretch was never propagated.

    Interpolating to the edge of the axis would draw a vehicle that does not
    exist, so the trailing samples must come back as nulls.
    """
    cfg = MissionConfig()
    # 2.5 orbits, so the run ends halfway through the last one.
    env, results, timelines = a_run(cfg, n=1400, dt=10.0)
    data = embedded(dashboard.build(cfg, env, results, timelines, tmp_path))
    orbits = next(iter(data["geometries"].values()))["orbits"]
    assert len(orbits) >= 2
    assert any(v is None for v in orbits[-1]["soc"]), \
        "the trailing partial orbit was filled in rather than left blank"


def test_mode_colours_match_the_figures(tmp_path):
    """One encoding across the PNG timeline and the page."""
    from hs2sim.output.style import MODE_WASH
    cfg = MissionConfig()
    env, results, timelines = a_run(cfg)
    data = embedded(dashboard.build(cfg, env, results, timelines, tmp_path))
    assert data["modeColors"] == MODE_WASH
