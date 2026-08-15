"""How much stored energy each activity costs, and the SOC it must be entered at.

Mode entry is a question about stored energy, not about a fixed SOC number
picked in advance. An activity is only safe to begin if the battery can pay for
the activity *and* for the recovery back to a sun-pointing charging attitude,
in the dark, with the worst slew the magnetic geometry can impose. That makes
each threshold a budget:

    safe        the vehicle must always hold enough to ride out the longest
                eclipse on survival loads and then turn back to the Sun
    standby     safe, plus a whole worst-case contact: turn to the station,
                downlink, turn back. A contact begun from standby therefore
                cannot push the vehicle into safe mode -- that is the property
                this threshold exists to guarantee
    experiment  standby, plus a whole worst-case science block: turn to the
                target, observe, turn back

Every duration is the worst case rather than the typical one, and every
excursion is priced with no generation at all -- the vehicle is assumed to be
in eclipse throughout, which is when the cost is highest and when a mode
decision most needs to be right.

The margin is a multiplier on each excursion's own cost and is never re-applied
to the running total, so it does not compound up the ladder: at a margin of 2,
the experiment threshold carries twice a science block plus twice a contact
plus twice the survival reserve, not eight times the survival reserve.

The ladder is stacked on the battery's depth-of-discharge limit, which is
configurable and currently zero -- the scheduler may spend the whole battery
and the only hard limit is empty. Set that limit non-zero and every threshold
rises with it, since energy below it is not the scheduler's to spend.
"""

from __future__ import annotations

import dataclasses

from . import adcs, comms, power, thermal
from .config import MissionConfig
from .environment import EnvironmentResult

# The largest reorientation there is. Worst-case slews are priced at 180 deg
# because nothing about the scheduler forbids one: the legal experiment
# attitude can sit on the far side of Earth from the one being held.
WORST_SLEW_DEG = 180.0


@dataclasses.dataclass
class Step:
    """One leg of an excursion: a duration held at a mode's load."""
    label: str
    seconds: float
    watts: float

    @property
    def wh(self) -> float:
        return self.watts * self.seconds / 3600.0


@dataclasses.dataclass
class Excursion:
    """A committed sequence of legs the battery has to pay for in full."""
    name: str
    steps: list[Step]

    @property
    def seconds(self) -> float:
        return sum(s.seconds for s in self.steps)

    @property
    def wh(self) -> float:
        return sum(s.wh for s in self.steps)


@dataclasses.dataclass
class EnergyBudget:
    """Worst-case excursion costs and the SOC thresholds they imply."""
    margin: float
    capacity_wh: float
    hard_floor_soc: float           # cell-protection limit, from the DoD limit
    worst_slew_s: float
    longest_eclipse_s: float
    longest_pass_s: float
    survival: Excursion
    downlink: Excursion
    experiment: Excursion
    soc_safe: float
    soc_standby: float
    soc_experiment: float

    @property
    def experiment_affordable(self) -> bool:
        """False means a full battery still cannot fund a science block."""
        return self.soc_experiment <= 1.0

    @property
    def downlink_affordable(self) -> bool:
        return self.soc_standby <= 1.0

    def table(self) -> list[str]:
        """The worst-case derivation, as lines meant to be logged."""
        lines = [
            f"worst-case inputs: {WORST_SLEW_DEG:.0f} deg slew "
            f"{self.worst_slew_s / 60:.1f} min, longest eclipse "
            f"{self.longest_eclipse_s / 60:.1f} min, longest pass "
            f"{self.longest_pass_s / 60:.1f} min, "
            f"battery {self.capacity_wh:.1f} Wh, margin {self.margin:.2f}",
        ]
        for excursion in (self.survival, self.downlink, self.experiment):
            lines.append(f"  {excursion.name} "
                         f"({excursion.seconds / 60:.1f} min, "
                         f"{excursion.wh:.2f} Wh = "
                         f"{100 * excursion.wh / self.capacity_wh:.1f} % SOC)")
            for step in excursion.steps:
                lines.append(f"      {step.label:<34s} "
                             f"{step.seconds / 60:6.1f} min x "
                             f"{step.watts:6.2f} W = {step.wh:6.2f} Wh")
        lines += [
            f"  SOC thresholds (margin {self.margin:.2f} per excursion, not "
            f"compounded, on a {self.hard_floor_soc * 100:.0f} % floor): "
            f"safe {self.soc_safe * 100:.1f} %, "
            f"standby/downlink {self.soc_standby * 100:.1f} %, "
            f"experiment {self.soc_experiment * 100:.1f} %",
        ]
        if not self.downlink_affordable:
            lines.append("  WARNING: a worst-case contact costs more than the "
                         "whole battery; downlink can never be guaranteed")
        if not self.experiment_affordable:
            lines.append("  WARNING: a worst-case science block costs more "
                         "than the whole battery; experiment mode is "
                         "unreachable at this margin")
        return lines

    def as_dict(self) -> dict:
        return {
            "margin": self.margin,
            "margin_applied": "per excursion, not compounded",
            "capacity_wh": self.capacity_wh,
            "worst_case_inputs": {
                "slew_deg": WORST_SLEW_DEG,
                "worst_slew_min": self.worst_slew_s / 60.0,
                "longest_eclipse_min": self.longest_eclipse_s / 60.0,
                "longest_pass_min": self.longest_pass_s / 60.0,
            },
            "excursions": {
                excursion.name: {
                    "total_min": excursion.seconds / 60.0,
                    "total_wh": excursion.wh,
                    "soc_fraction": excursion.wh / self.capacity_wh,
                    "steps": [
                        {"label": s.label, "minutes": s.seconds / 60.0,
                         "watts": s.watts, "wh": s.wh}
                        for s in excursion.steps
                    ],
                }
                for excursion in (self.survival, self.downlink, self.experiment)
            },
            "soc_thresholds": {
                "safe": self.soc_safe,
                "standby_downlink": self.soc_standby,
                "experiment": self.soc_experiment,
                "hard_cell_floor": self.hard_floor_soc,
            },
            "downlink_affordable": self.downlink_affordable,
            "experiment_affordable": self.experiment_affordable,
        }


def worst_slew_seconds(cfg: MissionConfig, authority: adcs.TorqueAuthority,
                       env: EnvironmentResult | None = None) -> float:
    """Longest a 180 deg reorientation takes over axis and start phase.

    Not the median: an entry condition that used the typical slew would be
    wrong exactly when the field geometry is unhelpful, which is the case it
    exists to cover.
    """
    profile = adcs.slew_time_profile(cfg, authority, WORST_SLEW_DEG, env=env)
    return float(max(profile["worst_s"], profile["worst_axis_s"]))


def budget(cfg: MissionConfig, env: EnvironmentResult,
           authority: adcs.TorqueAuthority, passes: list[comms.Pass],
           margin: float | None = None) -> EnergyBudget:
    """Price every worst-case excursion and derive the SOC thresholds."""
    loads = power.mode_power_table(cfg)
    battery = cfg.spacecraft.battery
    capacity_wh = float(battery.capacity_wh)
    if margin is None:
        margin = float(cfg.spacecraft.conops.soc_margin)

    slew_s = worst_slew_seconds(cfg, authority, env)
    eclipse_s = thermal.eclipse_statistics(env)["max_eclipse_min"] * 60.0
    longest_pass_s = max((p.duration_s for p in passes), default=0.0)
    # A science block is priced over the longest eclipse for the same reason
    # the survival case is: that is the longest the vehicle can be committed
    # with nothing coming in from the array.
    block_s = eclipse_s

    survival = Excursion("survive_eclipse_and_recover", [
        Step("longest eclipse on safe loads", eclipse_s, loads["safe"]),
        Step("worst slew back to sun-pointing", slew_s, loads["slew"]),
    ])
    downlink = Excursion("worst_case_contact", [
        Step("worst slew to the downlink attitude", slew_s, loads["slew"]),
        Step("longest pass transmitting", longest_pass_s, loads["downlink"]),
        Step("worst slew back to sun-pointing", slew_s, loads["slew"]),
    ])
    experiment = Excursion("worst_case_science_block", [
        Step("worst slew to the experiment attitude", slew_s, loads["slew"]),
        Step("science block (longest eclipse)", block_s, loads["experiment"]),
        Step("worst slew back to sun-pointing", slew_s, loads["slew"]),
    ])

    # Each level is the level below it plus its own margined cost. The margin
    # multiplies that one excursion and is not re-applied to the total, so it
    # does not compound. Standby entry is safe entry plus a *whole* worst-case
    # contact, which is precisely what makes a downlink begun from standby
    # unable to push the vehicle into safe mode.
    hard_floor = 1.0 - float(battery.depth_of_discharge_limit)
    soc_safe = hard_floor + margin * survival.wh / capacity_wh
    soc_standby = soc_safe + margin * downlink.wh / capacity_wh
    soc_experiment = soc_standby + margin * experiment.wh / capacity_wh

    return EnergyBudget(
        margin=margin,
        capacity_wh=capacity_wh,
        hard_floor_soc=hard_floor,
        worst_slew_s=slew_s,
        longest_eclipse_s=eclipse_s,
        longest_pass_s=longest_pass_s,
        survival=survival,
        downlink=downlink,
        experiment=experiment,
        soc_safe=soc_safe,
        soc_standby=soc_standby,
        soc_experiment=soc_experiment,
    )
