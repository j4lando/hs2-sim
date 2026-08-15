"""Worst-case excursion costs and the SOC thresholds derived from them."""

from __future__ import annotations

import numpy as np
import pytest

from helpers import orbit_env
from hs2sim import comms, energy
from hs2sim.config import MissionConfig
from hs2sim.adcs import TorqueAuthority


def fake_authority(n: int) -> TorqueAuthority:
    """Uniform, generous authority, so slew pricing is finite and quick."""
    return TorqueAuthority(
        b_magnitude_nt=np.full(n, 36000.0),
        max_torque_nm=np.full(n, 1.2e-5),
        axis_torque_nm=np.full((n, 3), 1.2e-5),
        mean_max_torque_nm=1.2e-5,
        min_max_torque_nm=1.2e-5,
        worst_axis_mean_nm=1.2e-5)


def a_pass(duration_s: float) -> comms.Pass:
    return comms.Pass(station_index=0, station_name="s", start_s=100.0,
                      end_s=100.0 + duration_s, duration_s=duration_s,
                      max_elevation_deg=40.0, min_range_km=800.0,
                      usable_s=duration_s, bytes_capacity=1_000_000)


def a_budget(cfg: MissionConfig, margin: float = 1.2) -> energy.EnergyBudget:
    env = orbit_env(600, 10.0, 5580.0)
    # Part of the run in shadow, so there is a longest eclipse to price against.
    env.shadow_factor[100:280] = 0.0
    # A field that turns through the orbit. A constant one would leave the
    # eigenaxis-along-B case permanently unactuatable and the worst-case slew
    # infinite, which is a real behaviour but not what these tests are about.
    ang = 2 * np.pi * env.t_s / 5580.0
    env.b_field_N = 3.5e-5 * np.stack(
        [np.cos(ang), np.sin(ang), 0.3 * np.ones_like(ang)], axis=1)
    return energy.budget(cfg, env, fake_authority(env.n_samples),
                         [a_pass(400.0)], margin=margin)


def test_thresholds_stack_upward_from_the_cell_floor():
    """Energy under the DoD limit is not the scheduler's to spend."""
    budget = a_budget(MissionConfig())
    assert budget.soc_safe > budget.hard_floor_soc
    assert budget.soc_standby > budget.soc_safe
    assert budget.soc_experiment > budget.soc_standby


def test_a_contact_begun_from_standby_cannot_reach_safe_mode():
    """The property the standby threshold exists to guarantee.

    Standby entry is safe entry plus a *whole* worst-case contact, so paying
    for that contact in full still leaves the vehicle at or above safe entry.
    """
    budget = a_budget(MissionConfig())
    after = budget.soc_standby - budget.downlink.wh / budget.capacity_wh
    assert after >= budget.soc_safe


def test_a_science_block_begun_from_its_threshold_cannot_reach_safe():
    budget = a_budget(MissionConfig())
    after = budget.soc_experiment - budget.experiment.wh / budget.capacity_wh
    assert after >= budget.soc_safe


def test_margin_only_ever_raises_the_thresholds():
    lean = a_budget(MissionConfig(), margin=1.0)
    padded = a_budget(MissionConfig(), margin=1.2)
    assert padded.soc_safe > lean.soc_safe
    assert padded.soc_standby > lean.soc_standby
    assert padded.soc_experiment > lean.soc_experiment
    # With no margin at all the reserve is exactly the worst-case cost.
    assert lean.soc_safe == pytest.approx(
        lean.hard_floor_soc + lean.survival.wh / lean.capacity_wh)


def test_excursion_energy_is_the_sum_of_its_legs():
    budget = a_budget(MissionConfig())
    for excursion in (budget.survival, budget.downlink, budget.experiment):
        assert excursion.wh == pytest.approx(
            sum(s.watts * s.seconds / 3600.0 for s in excursion.steps))
        assert excursion.seconds == pytest.approx(
            sum(s.seconds for s in excursion.steps))


def test_survival_is_priced_on_safe_loads_not_standby_loads():
    """Safe mode exists to be cheaper; pricing it at standby hides that."""
    from hs2sim import power
    loads = power.mode_power_table(MissionConfig())
    budget = a_budget(MissionConfig())
    eclipse_leg = budget.survival.steps[0]
    assert eclipse_leg.watts == pytest.approx(loads["safe"])
    assert loads["safe"] < loads["standby"]


def test_an_unaffordable_excursion_is_reported_not_hidden():
    """A battery too small for a contact must say so rather than round down."""
    cfg = MissionConfig().copy_with(**{"spacecraft.battery.capacity_wh": 2.0})
    budget = a_budget(cfg)
    assert not budget.downlink_affordable
    assert any("WARNING" in line for line in budget.table())
