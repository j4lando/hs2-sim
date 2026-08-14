"""The mode scheduler -- where power, pointing, comms and ADCS interact.

A discrete-time state machine walks the propagation and decides what the
spacecraft is doing at each sample. The point of running it, rather than
adding up per-subsystem averages, is that the constraints are coupled:

  * Experiment mode needs a legal attitude, which only exists part of the time.
  * Downlink needs an attitude that puts a patch antenna on the ground station.
  * Both compete with sun-pointing for charging, and the battery is finite.
  * Every switch between those attitudes costs a magnetorquer-limited slew,
    which is minutes, not seconds -- so mode thrash is genuinely expensive.

Mode priority, highest first:
    DOWNLINK  when a station is visible and there is data queued
    EXPERIMENT when the pointing constraints are satisfiable and SOC allows
    STANDBY   otherwise (sun-pointing, charging)
SLEW is inserted whenever the attitude has to change by more than
``intra_mode_slew_threshold_deg``. That covers mode changes, but also genuine
repoints *inside* experiment mode: when the sunlit-limb and Sun keep-out
constraints make the limb point currently being held illegal, the nearest legal
attitude can be on the far side of Earth. Smooth drift below the threshold --
following the limb, or a station across the sky -- is treated as a slew *rate*
requirement instead, and reported separately so it can be checked against
actuator authority.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from . import comms, environment, power
from .adcs import (TorqueAuthority, available_torque_about, dipole_vector,
                   eigenaxis_inertia, inertia_matrix, slew_time_eigenaxis)
from .config import MissionConfig
from .environment import EnvironmentResult
from .geometry import PointingResult

MODE_SAFE = 0
MODE_STANDBY = 1
MODE_SLEW = 2
MODE_EXPERIMENT = 3
MODE_DOWNLINK = 4

# Longest a single manoeuvre is allowed to take before the scheduler stops
# waiting for the field to cooperate. Far beyond any real slew; it exists only
# so a pathological geometry cannot stall the run.
SLEW_GIVE_UP_S = 6.0 * 3600.0

MODE_NAMES = {
    MODE_SAFE: "safe",
    MODE_STANDBY: "standby",
    MODE_SLEW: "slew",
    MODE_EXPERIMENT: "experiment",
    MODE_DOWNLINK: "downlink",
}


@dataclasses.dataclass
class ConopsResult:
    mode: np.ndarray                # (N,) mode code per sample
    dcm_BN: np.ndarray              # (N,3,3) attitude actually flown
    generation_w: np.ndarray
    load_w: np.ndarray
    soc: np.ndarray
    experiments: np.ndarray         # (N,) experiments completed in that sample
    downlinked_bytes: np.ndarray    # (N,) information bytes sent
    queue_bytes: np.ndarray         # (N,) backlog awaiting downlink
    tracking_rate: np.ndarray       # (N,) rad/s the target attitude moves
    slew_count: int
    slew_seconds: float
    planned_slew_seconds: np.ndarray   # (S,) magnetically-priced slew durations
    slew_unreachable: int              # manoeuvres the field never permitted
    battery_limited: bool

    def mode_fractions(self) -> dict[str, float]:
        total = len(self.mode)
        return {name: float(np.sum(self.mode == code) / total)
                for code, name in MODE_NAMES.items()}


def principal_angle(dcm_a: np.ndarray, dcm_b: np.ndarray) -> float:
    """Rotation angle between two attitudes, radians."""
    rel = dcm_b @ dcm_a.T
    cos_theta = (np.trace(rel) - 1.0) / 2.0
    return float(np.arccos(np.clip(cos_theta, -1.0, 1.0)))


def rotation_axis_angle(dcm_a: np.ndarray,
                        dcm_b: np.ndarray) -> tuple[np.ndarray, float]:
    """Eigenaxis and angle of the rotation taking ``dcm_a`` to ``dcm_b``.

    The axis is invariant under the rotation, so the same components describe
    it in either frame -- which is what lets the caller express the magnetic
    field in the starting body frame and still get the right answer.
    """
    rel = dcm_b @ dcm_a.T
    cos_theta = np.clip((np.trace(rel) - 1.0) / 2.0, -1.0, 1.0)
    theta = math.acos(cos_theta)
    axis = np.array([rel[2, 1] - rel[1, 2],
                     rel[0, 2] - rel[2, 0],
                     rel[1, 0] - rel[0, 1]])
    norm = np.linalg.norm(axis)
    if norm < 1e-12:
        if theta < 1e-9:
            return np.array([0.0, 0.0, 1.0]), 0.0
        # 180 deg: the skew part vanishes, so take the axis from the symmetric
        # part instead.
        eigenvalues, eigenvectors = np.linalg.eigh((rel + np.eye(3)) / 2.0)
        return eigenvectors[:, int(np.argmax(eigenvalues))], theta
    return axis / norm, theta


def slerp_dcm(dcm_a: np.ndarray, dcm_b: np.ndarray, fraction: float) -> np.ndarray:
    """Rotate along the shortest geodesic from ``dcm_a`` to ``dcm_b``.

    Slews take minutes here, so snapping straight from the old attitude to the
    new one at the end would misreport both the array output during the slew and
    the motion a visualiser shows. Interpolating along the principal rotation
    axis is the eigenaxis manoeuvre a real controller approximates anyway.
    """
    fraction = float(np.clip(fraction, 0.0, 1.0))
    rel = dcm_b @ dcm_a.T
    cos_theta = np.clip((np.trace(rel) - 1.0) / 2.0, -1.0, 1.0)
    theta = math.acos(cos_theta)
    if theta < 1e-9:
        return dcm_b if fraction >= 1.0 else dcm_a.copy()

    axis = np.array([rel[2, 1] - rel[1, 2],
                     rel[0, 2] - rel[2, 0],
                     rel[1, 0] - rel[0, 1]])
    norm = np.linalg.norm(axis)
    if norm < 1e-12:
        # 180 deg rotation: the skew part vanishes, so take the axis from the
        # symmetric part instead.
        eigenvalues, eigenvectors = np.linalg.eigh((rel + np.eye(3)) / 2.0)
        axis = eigenvectors[:, int(np.argmax(eigenvalues))]
    else:
        axis = axis / norm

    angle = theta * fraction
    skew = np.array([[0.0, -axis[2], axis[1]],
                     [axis[2], 0.0, -axis[0]],
                     [-axis[1], axis[0], 0.0]])
    partial = (np.eye(3) + math.sin(angle) * skew
               + (1.0 - math.cos(angle)) * (skew @ skew))
    return partial @ dcm_a


def downlink_attitude(env: EnvironmentResult,
                      station_index: np.ndarray,
                      sun_dcm: np.ndarray,
                      station_pos_N: np.ndarray) -> np.ndarray:
    """Attitude that puts the +x S-band patch on the visible station.

    The +x boresight is aimed at the true spacecraft-to-station vector, which
    is what justifies the modest antenna pointing loss in the link budget. The
    remaining freedom -- roll about the boresight -- is spent on solar power by
    keeping the standby attitude's z axis as close as possible.
    """
    n = env.n_samples
    dcm = sun_dcm.copy()
    for i in range(n):
        s = int(station_index[i])
        if s < 0:
            continue
        to_station = station_pos_N[s, i] - env.r_BN_N[i]
        norm_s = np.linalg.norm(to_station)
        if norm_s < 1e-9:
            continue
        x_axis = to_station / norm_s
        # Keep z as close to the sun-pointing z as possible.
        z_ref = sun_dcm[i, 2, :]
        z_axis = z_ref - np.dot(z_ref, x_axis) * x_axis
        norm = np.linalg.norm(z_axis)
        if norm < 1e-9:
            z_axis = np.array([0.0, 0.0, 1.0]) - x_axis * x_axis[2]
            norm = np.linalg.norm(z_axis)
        z_axis /= norm
        y_axis = np.cross(z_axis, x_axis)
        dcm[i] = np.vstack([x_axis, y_axis, z_axis])
    return dcm


def simulate(cfg: MissionConfig,
             env: EnvironmentResult,
             array: power.ArrayGeometry,
             pointing: PointingResult,
             standby_dcm: np.ndarray,
             authority: TorqueAuthority,
             payload_rate_hz: float,
             passes: list[comms.Pass]) -> ConopsResult:
    """Run the mode scheduler over the whole propagation."""
    n = env.n_samples
    dt = env.dt_s

    # Which station (if any) is visible at each sample, preferring the one
    # with the best link (shortest range).
    ranges = np.where(env.station_access, env.station_range, np.inf)
    best_station = np.argmin(ranges, axis=0)
    visible = np.isfinite(np.min(ranges, axis=0))
    station_index = np.where(visible, best_station, -1)

    station_pos_N = environment.station_positions_inertial(cfg, env)
    dl_dcm = downlink_attitude(env, station_index, standby_dcm, station_pos_N)

    # Achievable information rate while a station is up.
    best_range = np.where(visible, np.min(ranges, axis=0), 1e12)
    link_bps = comms.achievable_bitrate_bps(cfg, best_range)
    link_bps = np.where(visible, link_bps, 0.0)

    # Pre-compute generation for each candidate attitude.
    gen_experiment = power.generation_w(cfg, env, array, pointing.dcm_BN)
    gen_standby = power.generation_w(cfg, env, array, standby_dcm)
    gen_downlink = power.generation_w(cfg, env, array, dl_dcm)

    loads = power.mode_power_table(cfg)
    battery = cfg.spacecraft.battery
    capacity_wh = float(battery.capacity_wh)
    soc_floor = 1.0 - float(battery.depth_of_discharge_limit)
    charge_efficiency = float(battery.round_trip_efficiency)
    # Hysteresis so the scheduler does not chatter around the floor.
    policy = cfg.spacecraft.conops
    soc_resume = soc_floor + float(policy.soc_resume_margin)
    downlink_trigger = float(policy.downlink_trigger_bytes)
    intra_mode_slew_threshold = math.radians(
        float(policy.intra_mode_slew_threshold_deg))
    # A slew is "done" once the attitude is inside the control error -- the
    # controller cannot do better than that, so waiting for more is waiting
    # forever. Knowledge error does not belong here: it does not stop the
    # vehicle from being where it was told to go.
    pointing_accuracy = math.radians(
        float(cfg.spacecraft.adcs.control_error_deg))

    inertia = inertia_matrix(cfg)
    slew_margin = float(cfg.spacecraft.adcs.settle_margin)
    dipole = dipole_vector(cfg)
    # Slews are priced against the actual field history about the actual
    # eigenaxis, so a manoeuvre that has to turn about the field direction is
    # charged the wait. Look ahead three orbits, which is far more than any
    # slew needs and enough for the field geometry to come round.
    slew_horizon = min(n, max(64, int(3.0 * 5580.0 / dt)))

    mode = np.full(n, MODE_STANDBY, dtype=np.int8)
    flown = standby_dcm.copy()
    generation = np.zeros(n)
    load = np.zeros(n)
    soc = np.zeros(n)
    experiments = np.zeros(n)
    downlinked = np.zeros(n)
    queue = np.zeros(n)
    tracking_rate = np.zeros(n)   # rad/s the target attitude is moving

    img_bytes = comms.image_bytes(cfg)
    per_experiment_bytes = (int(cfg.payload.numerical_bytes_per_experiment)
                            + comms.SAMPLE_OVERHEAD_B) * comms.MARGIN
    # Housekeeping accrues continuously and must also go down.
    agg_size, agg_period = comms.AGGREGATE_TELEMETRY
    housekeeping_bps = (agg_size + comms.SAMPLE_OVERHEAD_B) / agg_period
    debug_image_bytes_per_day = (int(cfg.payload.debug_images_per_day)
                                 * (img_bytes + comms.IMAGE_OVERHEAD_B))
    debug_bytes_per_s = debug_image_bytes_per_day / 86400.0

    level_wh = float(battery.initial_soc) * capacity_wh
    backlog = 0.0
    current_dcm = standby_dcm[0]
    current_mode = MODE_STANDBY
    pending_mode = MODE_STANDBY
    slewing = False
    slew_rate = 0.0
    slew_count = 0
    slew_seconds = 0.0
    slew_seconds_planned: list[float] = []
    slew_unreachable = 0
    battery_limited = False
    charging_hold = False

    usb_fps = comms.usb2_max_fps(cfg)
    effective_rate = min(payload_rate_hz, usb_fps)

    # Hoisted out of the loop: recomputing these per sample would make the
    # scheduler quadratic in the number of samples.
    sun_hat = env.sun_unit()
    b_field_N = env.b_field_N
    array_settings = cfg.spacecraft.solar_array
    array_efficiency = (float(array_settings.mppt_efficiency)
                        * float(array_settings.degradation))

    for i in range(n):
        soc_now = level_wh / capacity_wh
        if soc_now <= soc_floor + 1e-9:
            charging_hold = True
            battery_limited = True
        elif soc_now >= soc_resume:
            charging_hold = False

        # -- choose the target mode -----------------------------------------
        # Science is the discretionary activity; downlink is not. A low battery
        # suspends experiments but must not suspend downlink, or the vehicle
        # deadlocks: it stops sending, the backlog grows without bound, and the
        # mission silently fails while the model reports a healthy SOC.
        # Contacts are scarce (a few minutes each), so a pass is spent even at
        # the cost of discharging.
        if (station_index[i] >= 0 and link_bps[i] > 0
                and backlog >= downlink_trigger):
            target_mode = MODE_DOWNLINK
        elif charging_hold or not pointing.feasible[i]:
            target_mode = MODE_STANDBY
        else:
            target_mode = MODE_EXPERIMENT

        target_dcm = {
            MODE_STANDBY: standby_dcm[i],
            MODE_EXPERIMENT: pointing.dcm_BN[i],
            MODE_DOWNLINK: dl_dcm[i],
        }[target_mode]

        # -- decide between tracking and slewing ------------------------------
        # Two different things move the target attitude, and they cost
        # different amounts:
        #   * Smooth drift within a mode -- following the limb, or a station
        #     across the sky. That is a slew *rate* requirement, not a
        #     reorientation, and charging it as a slew every sample would pin
        #     the vehicle in SLEW for whole passes.
        #   * A genuine repoint. These happen inside experiment mode too: when
        #     the sunlit-limb and Sun keep-out constraints make the currently
        #     held limb point illegal, the only legal attitudes can be on the
        #     far side of Earth, which is a >100 deg reorientation.
        # Anything above the threshold is treated as a real slew.
        angle_to_target = principal_angle(current_dcm, target_dcm)
        mode_changed = target_mode != current_mode

        if not slewing:
            if angle_to_target > intra_mode_slew_threshold or (
                    mode_changed and angle_to_target > pointing_accuracy):
                slewing = True
                slew_count += 1
                pending_mode = target_mode
                # Price this specific manoeuvre: the eigenaxis it has to turn
                # about, the inertia about that axis, and the authority the
                # field actually offers about it over the coming orbits. The
                # field is taken in the body frame held at the start of the
                # slew; the vehicle also rotates during the manoeuvre, which
                # this does not track, but that is second order next to the
                # twice-per-orbit sweep of the field itself.
                axis_B, _ = rotation_axis_angle(current_dcm, target_dcm)
                b_body = (b_field_N[i:i + slew_horizon] @ current_dcm.T)
                torque_series = available_torque_about(dipole, b_body, axis_B)
                seconds = slew_time_eigenaxis(
                    torque_series, eigenaxis_inertia(inertia, axis_B),
                    angle_to_target, dt, 0, slew_margin)
                if not math.isfinite(seconds) or seconds <= 0:
                    # The integrator gave up: no field geometry inside its
                    # horizon lets this manoeuvre finish. Do not deadlock the
                    # scheduler on it -- charge the horizon and move on, and
                    # count it so it cannot hide.
                    seconds = SLEW_GIVE_UP_S
                    slew_unreachable += 1
                slew_rate = angle_to_target / seconds
                slew_seconds_planned.append(seconds)
            elif mode_changed:
                current_mode = target_mode

        if slewing:
            mode[i] = MODE_SLEW
            # Rate-limited follower: the vehicle turns toward wherever it is
            # currently commanded, by at most slew_rate * dt per step. Bounding
            # the step is what makes the attitude continuous *by construction* --
            # if the target jumps mid-manoeuvre (the feasible limb region can
            # flip to the far side of Earth), the slew simply takes longer
            # instead of the vehicle teleporting.
            step = min(angle_to_target, slew_rate * dt)
            if angle_to_target > 1e-12:
                current_dcm = slerp_dcm(current_dcm, target_dcm,
                                        step / angle_to_target)
            flown[i] = current_dcm
            cosines = np.clip(sun_hat[i] @ (current_dcm.T @ array.normals.T), 0.0, None)
            generation[i] = float(cosines @ array.peak_w
                                  * env.shadow_factor[i] * array_efficiency)
            load[i] = loads["slew"]
            slew_seconds += dt
            if principal_angle(current_dcm, target_dcm) <= pointing_accuracy:
                slewing = False
                current_mode = pending_mode
        else:
            mode[i] = current_mode
            # Continuous tracking within the mode: record how fast the target
            # attitude is moving so it can be checked against actuator limits.
            tracking_rate[i] = principal_angle(current_dcm, target_dcm) / dt
            current_dcm = target_dcm
            flown[i] = target_dcm
            if current_mode == MODE_EXPERIMENT:
                generation[i] = gen_experiment[i]
                load[i] = loads["experiment"]
                experiments[i] = effective_rate * dt
                backlog += experiments[i] * per_experiment_bytes
            elif current_mode == MODE_DOWNLINK:
                generation[i] = gen_downlink[i]
                load[i] = loads["downlink"]
                sendable = link_bps[i] * dt / 8.0
                sent = min(sendable, backlog)
                downlinked[i] = sent
                backlog -= sent
            else:
                generation[i] = gen_standby[i]
                load[i] = loads["standby"]

        # Housekeeping and the daily debug images join the queue continuously.
        backlog += (housekeeping_bps + debug_bytes_per_s) * dt

        delta = (generation[i] - load[i]) * dt / 3600.0
        if delta > 0:
            delta *= charge_efficiency
        level_wh = min(capacity_wh, level_wh + delta)
        if level_wh < soc_floor * capacity_wh:
            level_wh = soc_floor * capacity_wh
            battery_limited = True
        soc[i] = level_wh / capacity_wh
        queue[i] = backlog

    return ConopsResult(
        mode=mode,
        dcm_BN=flown,
        generation_w=generation,
        load_w=load,
        soc=soc,
        experiments=experiments,
        downlinked_bytes=downlinked,
        queue_bytes=queue,
        tracking_rate=tracking_rate,
        slew_count=slew_count,
        slew_seconds=slew_seconds,
        planned_slew_seconds=np.array(slew_seconds_planned),
        slew_unreachable=slew_unreachable,
        battery_limited=battery_limited,
    )


def summarise(cfg: MissionConfig, env: EnvironmentResult,
              result: ConopsResult) -> dict[str, float]:
    days = env.duration_days
    images_per_experiment = int(cfg.payload.n_cameras)
    total_experiments = float(np.sum(result.experiments))
    return {
        "experiments_per_day": total_experiments / days,
        "images_per_day": total_experiments * images_per_experiment / days,
        "downlinked_mb_per_day": float(np.sum(result.downlinked_bytes) / 1e6 / days),
        "final_queue_mb": float(result.queue_bytes[-1] / 1e6),
        # Net growth of the downlink backlog. A positive number means data is
        # being generated faster than contacts can clear it, so the mission is
        # downlink-bound at this cadence; the sign is what matters, not noise
        # from where in a pass the run happens to end.
        "backlog_growth_mb_per_day": float(
            (result.queue_bytes[-1] - result.queue_bytes[0]) / 1e6 / days),
        "min_soc": float(np.min(result.soc)),
        "mean_soc": float(np.mean(result.soc)),
        "battery_limited": result.battery_limited,
        "mean_generation_w": float(np.mean(result.generation_w)),
        "mean_load_w": float(np.mean(result.load_w)),
        "energy_margin_w": float(np.mean(result.generation_w - result.load_w)),
        "slews_per_day": result.slew_count / days,
        "slew_time_fraction": result.slew_seconds / (days * 86400.0),
        "planned_slew_median_min": (
            float(np.median(result.planned_slew_seconds)) / 60.0
            if result.planned_slew_seconds.size else 0.0),
        "planned_slew_p90_min": (
            float(np.percentile(result.planned_slew_seconds, 90)) / 60.0
            if result.planned_slew_seconds.size else 0.0),
        "planned_slew_max_min": (
            float(np.max(result.planned_slew_seconds)) / 60.0
            if result.planned_slew_seconds.size else 0.0),
        "slews_unreachable": result.slew_unreachable,
        "max_tracking_rate_dps": float(np.degrees(np.max(result.tracking_rate))),
        "mean_tracking_rate_dps": float(np.degrees(np.mean(result.tracking_rate))),
        **{f"frac_{name}": value for name, value in result.mode_fractions().items()},
    }
