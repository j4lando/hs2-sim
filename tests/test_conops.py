"""Scheduler decisions that do not need a propagation to check."""

from __future__ import annotations

import math

import numpy as np

from helpers import orbit_env
from hs2sim import comms, conops
from hs2sim.config import MissionConfig


def contact(station_index: int, start_s: float, end_s: float,
            bytes_capacity: int = 10_000_000) -> comms.Pass:
    return comms.Pass(
        station_index=station_index, station_name=f"s{station_index}",
        start_s=start_s, end_s=end_s, duration_s=end_s - start_s,
        max_elevation_deg=40.0, min_range_km=800.0,
        usable_s=end_s - start_s, bytes_capacity=bytes_capacity)


def test_downlink_is_committed_before_the_station_rises():
    """A slew begun at AOS loses the whole pass, so the window starts early."""
    env = orbit_env(400, 10.0, 5580.0)          # 10 s steps, 4000 s long
    committed = conops.downlink_commitment(
        env, [contact(3, 1000.0, 1300.0)], lead_s=240.0)

    # Committed from AOS minus the lead, through to LOS.
    assert committed[int(760 / 10)] == 3
    assert committed[int(1000 / 10)] == 3
    assert committed[int(1290 / 10)] == 3
    # And not before the lead-in, nor after the station sets.
    assert committed[int(750 / 10)] == -1
    assert committed[int(1310 / 10)] == -1
    # The lead really is the configured length, not a rounding accident.
    live = np.flatnonzero(committed >= 0)
    assert env.t_s[live[0]] == 760.0
    assert env.t_s[live[-1]] < 1300.0


def test_a_pass_that_carries_nothing_is_not_worth_pointing_at():
    env = orbit_env(400, 10.0, 5580.0)
    committed = conops.downlink_commitment(
        env, [contact(1, 1000.0, 1300.0, bytes_capacity=0)], lead_s=240.0)
    assert np.all(committed == -1)


def test_a_contact_under_way_is_not_dropped_for_a_later_one():
    """There is one antenna, and 15 sites overlap constantly.

    Station 7's lead-in (from 960 s) runs straight through station 0's whole
    pass. Handing the antenna to 7 early would abandon a contact already being
    flown, so 0 keeps every sample it claimed and 7 picks up only what is left.
    """
    env = orbit_env(400, 10.0, 5580.0)
    committed = conops.downlink_commitment(
        env, [contact(0, 1000.0, 1400.0), contact(7, 1200.0, 1600.0)],
        lead_s=240.0)
    assert committed[int(960 / 10)] == 0     # 0's lead-in, claimed first
    assert committed[int(1300 / 10)] == 0    # mid-pass, not pre-empted
    assert committed[int(1400 / 10)] == 7    # 7 takes over at 0's LOS
    assert committed[int(1590 / 10)] == 7


def dark_env(n: int = 240, dt: float = 10.0):
    """An orbit spent entirely in eclipse: nothing comes in from the array."""
    env = orbit_env(n, dt, 5580.0)
    env.shadow_factor[:] = 0.0
    ang = 2 * np.pi * env.t_s / 5580.0
    env.b_field_N = 3.5e-5 * np.stack(
        [np.cos(ang), np.sin(ang), 0.3 * np.ones_like(ang)], axis=1)
    return env


def run_in_the_dark(cfg, env):
    """Scheduler over an env with no sunlight and no station, so the battery
    only ever discharges and nothing else can confuse the accounting."""
    from hs2sim import adcs, geometry, power
    array = power.all_array_geometries(cfg)[0]
    standby = np.tile(np.eye(3), (env.n_samples, 1, 1))
    pointing = geometry.PointingResult(
        feasible=np.zeros(env.n_samples, bool),
        dcm_BN=standby.copy(),
        x_axis_N=np.tile([1.0, 0, 0], (env.n_samples, 1)),
        z_axis_N=np.tile([0, 0, 1.0], (env.n_samples, 1)),
        roll_used=np.zeros(env.n_samples),
        array_power_frac=np.zeros(env.n_samples),
        reject_reason=np.zeros(env.n_samples, int))
    authority = adcs.torque_authority(cfg, env)
    return conops.simulate(cfg, env, array, pointing, standby, authority,
                           0.2, [])


def test_the_battery_is_not_propped_up_at_the_cell_floor():
    """SOC must be allowed through the floor.

    Clamping there keeps charging the mode's full load while inventing the
    energy to pay for it, so the model would report a vehicle sitting at its
    floor running loads it cannot power. Whether the scheduler respects the
    floor is a result, not an assumption.
    """
    # Configure a real floor for this one: the property under test is that a
    # floor, when there is one, is never propped up. The shipped config has no
    # floor, which would make the check vacuous.
    cfg = MissionConfig().copy_with(**{
        "spacecraft.battery.capacity_wh": 0.4,
        "spacecraft.battery.depth_of_discharge_limit": 0.5})
    result = run_in_the_dark(cfg, dark_env())
    floor = 1.0 - float(cfg.spacecraft.battery.depth_of_discharge_limit)
    assert result.soc.min() < floor
    assert result.battery_limited
    # And it is monotonically falling: no step ever gains charge in the dark.
    assert np.all(np.diff(result.soc) <= 1e-12)


def test_an_emptied_battery_fails_the_mission():
    cfg = MissionConfig().copy_with(**{"spacecraft.battery.capacity_wh": 0.05})
    result = run_in_the_dark(cfg, dark_env())
    assert result.mission_failed
    assert result.soc.min() == 0.0
    assert result.failure_time_s >= 0.0
    # The demand the empty battery could not serve is reported, not absorbed.
    assert result.unserved_wh > 0.0


def test_a_healthy_battery_neither_fails_nor_breaches_the_floor():
    cfg = MissionConfig()
    env = dark_env(n=30)          # only a few minutes of dark
    result = run_in_the_dark(cfg, env)
    assert not result.mission_failed
    assert not result.battery_limited
    assert math.isnan(result.failure_time_s)
    assert result.unserved_wh == 0.0


def sunlit_env(n: int = 900, dt: float = 10.0):
    """Fully sunlit orbit with a turning field, so the battery stays healthy
    and slew pricing is finite -- leaving mode logic as the only variable."""
    env = orbit_env(n, dt, 5580.0)
    env.shadow_factor[:] = 1.0
    ang = 2 * np.pi * env.t_s / 5580.0
    env.b_field_N = 3.5e-5 * np.stack(
        [np.cos(ang), np.sin(ang), 0.3 * np.ones_like(ang)], axis=1)
    return env


def run_with_pass(cfg, env, feasible, pass_window=None):
    from hs2sim import adcs, geometry, power
    n = env.n_samples
    array = power.all_array_geometries(cfg)[0]
    standby = np.tile(np.eye(3), (n, 1, 1))
    # An experiment attitude a long way from standby, so wanting it costs a
    # real slew rather than a nudge.
    turned = np.tile(np.diag([1.0, -1.0, -1.0]), (n, 1, 1))
    pointing = geometry.PointingResult(
        feasible=feasible, dcm_BN=turned,
        x_axis_N=np.tile([1.0, 0, 0], (n, 1)),
        z_axis_N=np.tile([0, 0, 1.0], (n, 1)),
        roll_used=np.zeros(n), array_power_frac=np.zeros(n),
        reject_reason=np.zeros(n, int))
    passes = []
    if pass_window is not None:
        start, stop = pass_window
        env.station_access[0, start:stop] = True
        env.station_range[0, :] = 800e3
        passes = [contact(0, float(env.t_s[start]), float(env.t_s[stop]))]
    authority = adcs.torque_authority(cfg, env)
    return conops.simulate(cfg, env, array, pointing, standby, authority,
                           0.2, passes)


def test_the_transmitter_is_not_keyed_before_the_station_rises():
    """Committing to a contact early must cost pointing, not 10 W of RF.

    The vehicle turns toward a station up to a lead time before AOS. Charging
    the full downlink load through that window would burn the transmitter into
    the ground for minutes before every pass and send nothing.
    """
    from hs2sim import power
    env = sunlit_env()
    cfg = MissionConfig()
    result = run_with_pass(cfg, env, np.zeros(env.n_samples, bool),
                           pass_window=(600, 660))
    loads = power.mode_power_table(cfg)
    in_downlink = result.mode == conops.MODE_DOWNLINK
    no_link = ~env.station_access[0]
    keyed_early = in_downlink & no_link
    if keyed_early.any():
        assert result.load_w[keyed_early].max() <= loads["standby"] + 1e-9
    # And nothing is ever sent while the station is below the horizon.
    assert result.downlinked_bytes[no_link].sum() == 0.0


def test_a_target_that_outruns_the_vehicle_is_abandoned_to_sun_pointing():
    """A manoeuvre that cannot converge must be given up, not chased forever.

    A station crossing overhead moves faster than a magnetorquer-only 3U can
    turn, so a rate-limited follower aimed at one never arrives. Left alone it
    burns the rest of the orbit in SLEW. Here the commanded attitude spins far
    faster than any achievable slew rate, which is that case in the limit.
    """
    from hs2sim import adcs, geometry, power
    env = sunlit_env()
    n = env.n_samples
    cfg = MissionConfig()
    array = power.all_array_geometries(cfg)[0]
    standby = np.tile(np.eye(3), (n, 1, 1))
    # An experiment attitude tumbling at ~9 deg per sample -- far beyond the
    # few tenths of a degree per second the vehicle can manage.
    spin = np.zeros((n, 3, 3))
    for i in range(n):
        a = 0.157 * i
        spin[i] = np.array([[math.cos(a), -math.sin(a), 0.0],
                            [math.sin(a), math.cos(a), 0.0],
                            [0.0, 0.0, 1.0]])
    pointing = geometry.PointingResult(
        feasible=np.ones(n, bool), dcm_BN=spin,
        x_axis_N=np.tile([1.0, 0, 0], (n, 1)),
        z_axis_N=np.tile([0, 0, 1.0], (n, 1)),
        roll_used=np.zeros(n), array_power_frac=np.zeros(n),
        reject_reason=np.zeros(n, int))
    authority = adcs.torque_authority(cfg, env)
    result = conops.simulate(cfg, env, array, pointing, standby, authority,
                             0.2, [])

    assert result.slew_abandoned > 0, "an unconvergeable slew was never given up"
    # Each giving-up redirects to sun-pointing and the scheduler then commands
    # afresh, so the run is a sequence of bounded manoeuvres rather than one
    # open-ended chase.
    assert result.slew_count >= result.slew_abandoned > 1


def test_abandoned_slews_are_counted_in_the_summary():
    env = sunlit_env(n=200)
    result = run_with_pass(MissionConfig(), env, np.zeros(200, bool))
    summary = conops.summarise(MissionConfig(), env, result)
    assert summary["slews_abandoned"] == result.slew_abandoned
