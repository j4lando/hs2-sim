"""Scheduler decisions that do not need a propagation to check."""

from __future__ import annotations

import numpy as np

from helpers import orbit_env
from hs2sim import comms, conops


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
