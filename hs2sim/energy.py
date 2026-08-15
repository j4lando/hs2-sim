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

Two things set where the ladder starts and how the margin is applied, and both
are worth stating because neither is forced by the words above:

*The ladder is built on the cell-protection floor, not on zero.* Energy below
the depth-of-discharge limit is not the scheduler's to spend, so the survival
reserve has to sit on top of that limit. Measuring it from an empty battery
instead puts every threshold under the floor -- with the numbers this vehicle
actually has, safe entry lands near 10 % SOC -- and the floor stops meaning
anything.

*The margin is applied to each activity's own cost, not re-applied to the
running total.* Compounding it up the ladder inflates the survival reserve by
``margin`` again at every level, and with a 50 % floor it drives the experiment
threshold past a full battery, i.e. science becomes impossible on paper for
reasons that are pure double counting. The compounded figures are still
computed and reported next to the ones in use, so the difference is visible
rather than assumed away.
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
    # The literal compounding reading, for comparison only -- see the module
    # docstring. Nothing schedules on these.
    compounded: tuple[float, float, float] = (0.0, 0.0, 0.0)

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
            f"  SOC thresholds on a {self.hard_floor_soc * 100:.0f} % cell "
            f"floor, margin {self.margin:.2f} per excursion: "
            f"safe {self.soc_safe * 100:.1f} %, "
            f"standby/downlink {self.soc_standby * 100:.1f} %, "
            f"experiment {self.soc_experiment * 100:.1f} %",
            f"  (margin compounded on the running total instead would give "
            f"{self.compounded[0] * 100:.1f} / {self.compounded[1] * 100:.1f} "
            f"/ {self.compounded[2] * 100:.1f} %)",
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
            "margin_applied": "per excursion, stacked on the cell floor",
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
            "soc_thresholds_if_margin_compounded": {
                "safe": self.compounded[0],
                "standby_downlink": self.compounded[1],
                "experiment": self.compounded[2],
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

    # Each level is the level below it plus its own margined cost, stacked on
    # the cell floor because energy under that floor is not the scheduler's to
    # spend. Standby entry is safe entry plus a *whole* worst-case contact,
    # which is precisely what makes a downlink begun from standby unable to
    # push the vehicle into safe mode.
    hard_floor = 1.0 - float(battery.depth_of_discharge_limit)
    soc_safe = hard_floor + margin * survival.wh / capacity_wh
    soc_standby = soc_safe + margin * downlink.wh / capacity_wh
    soc_experiment = soc_standby + margin * experiment.wh / capacity_wh

    # The literal "(level below + this excursion) * margin" reading, reported
    # so the cost of compounding is visible instead of argued about.
    c_safe = margin * (hard_floor * capacity_wh + survival.wh) / capacity_wh
    c_standby = margin * (c_safe * capacity_wh + downlink.wh) / capacity_wh
    c_experiment = margin * (c_standby * capacity_wh
                             + experiment.wh) / capacity_wh

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
        compounded=(c_safe, c_standby, c_experiment),
    )
