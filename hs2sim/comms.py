"""Ground station access, link budget and the data budget that follows.

The chain is: Basilisk tells us when each station is above the elevation mask
and at what range; the link budget converts range into an achievable bit rate;
integrating that over each pass gives bytes per day; and the data budget turns
bytes per day into a ceiling on the number of experiments per day.

Two corrections to the supplied spreadsheet are applied here, both because the
user asked for Leaf Space rather than the university dish the budget assumed:

  * The ground receiver is Leaf Line's published S-band G/T of 12.8 dB/K, not
    the 1.9 m dish's -0.6 dB/K. That is 13.4 dB of extra margin.
  * The link is solved at every sample using the *actual* slant range from the
    propagation, instead of a single worst-case 10 deg elevation range.

Spacecraft-side numbers (2 W, 5 dBi patch, losses) come from the budget, which
the user flagged as trustworthy for antenna specifications.

Two link modes are modelled, selected by ``radio.fixed_rate.enabled``:

  * **Adaptive** (default): the radio can be commanded to any rate in
    ``radio.available_bitrates_kbps``, coded BPSK, and the solver picks the
    highest one that closes with margin at each sample's actual range.
  * **Fixed-rate GFSK**: the radio is pinned to the single rate in
    ``radio.fixed_rate.bitrate_kbps`` and demodulated non-coherently (GFSK),
    which costs extra Eb/N0 relative to BPSK for the same bit-error rate. The
    link either closes at that one rate or delivers nothing.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from .config import MissionConfig
from .environment import EnvironmentResult

BOLTZMANN_DBW = -228.6   # dB(W/Hz/K)
C_LIGHT = 299792458.0


@dataclasses.dataclass
class Pass:
    station_index: int
    station_name: str
    start_s: float
    end_s: float
    duration_s: float
    max_elevation_deg: float
    min_range_km: float
    usable_s: float          # after acquisition overhead
    bytes_capacity: int      # information bytes deliverable in this pass


def find_passes(env: EnvironmentResult,
                cfg: MissionConfig) -> list[list[tuple[int, int]]]:
    """Contiguous access index ranges per station, as [(start, end_exclusive)]."""
    out = []
    for row in env.station_access:
        passes = []
        start = None
        for i, value in enumerate(row):
            if value and start is None:
                start = i
            elif not value and start is not None:
                passes.append((start, i))
                start = None
        if start is not None:
            passes.append((start, len(row)))
        out.append(passes)
    return out


def free_space_loss_db(range_m: np.ndarray, frequency_hz: float) -> np.ndarray:
    return 20.0 * np.log10(4.0 * math.pi * range_m * frequency_hz / C_LIGHT)


def eirp_dbw(cfg: MissionConfig, worst_case_pointing: bool = False) -> float:
    """Spacecraft effective isotropic radiated power."""
    radio = cfg.radio
    tx_dbw = 10.0 * math.log10(float(radio.tx_power_w))
    pointing = (float(radio.pointing_loss_db_worst) if worst_case_pointing
                else float(radio.pointing_loss_db))
    return (tx_dbw
            + float(radio.tx_antenna_gain_dbi)
            + float(radio.return_loss_db)
            + float(radio.circuit_loss_db)
            + pointing)


def c_over_n0_dbhz(cfg: MissionConfig,
                   range_m: np.ndarray,
                   worst_case_pointing: bool = False) -> np.ndarray:
    """Carrier-to-noise-density ratio at the ground station."""
    radio = cfg.radio
    frequency_hz = float(radio.frequency_ghz) * 1e9
    gt = float(cfg.ground.network.gt_db_per_k)
    return (eirp_dbw(cfg, worst_case_pointing)
            - free_space_loss_db(range_m, frequency_hz)
            + float(radio.atmospheric_loss_db)
            + float(radio.rain_loss_db)
            + float(radio.polarization_loss_db)
            + gt
            - BOLTZMANN_DBW)


def fixed_rate_enabled(cfg: MissionConfig) -> bool:
    """Whether the radio is pinned to a single GFSK rate this run."""
    fixed = getattr(cfg.radio, "fixed_rate", None)
    return bool(fixed) and bool(fixed.get("enabled", False))


def eb_n0_required_db(cfg: MissionConfig) -> float:
    """Eb/N0 threshold for whichever modulation/coding is active this run."""
    if fixed_rate_enabled(cfg):
        return float(cfg.radio.fixed_rate.eb_n0_required_db)
    return float(cfg.radio.eb_n0_required_db)


def required_margin_db(cfg: MissionConfig) -> float:
    """Margin demanded above the demodulator threshold, in dB.

    Configured as a linear power ratio (``required_margin_factor``) because
    that is how the requirement is stated -- "the noise floor plus 50 %" is
    50 % more received power, which is 10*log10(1.5) = 1.76 dB, not 50 % more
    decibels. Falls back to the flat ``required_margin_db`` if no factor is
    given, which is what the UNP budget carried.
    """
    factor = getattr(cfg.radio, "required_margin_factor", None)
    if factor:
        return 10.0 * math.log10(float(factor))
    return float(cfg.radio.required_margin_db)


def link_threshold_db(cfg: MissionConfig) -> float:
    """Total Eb/N0 a link has to show to be declared closed."""
    return (eb_n0_required_db(cfg) + required_margin_db(cfg)
            + float(cfg.radio.implementation_loss_db))


def candidate_bitrates_kbps(cfg: MissionConfig) -> list[float]:
    """Rates the link solver is allowed to choose from this run."""
    if fixed_rate_enabled(cfg):
        return [float(cfg.radio.fixed_rate.bitrate_kbps)]
    return [float(r) for r in cfg.radio.available_bitrates_kbps]


def achievable_bitrate_bps(cfg: MissionConfig,
                           range_m: np.ndarray,
                           worst_case_pointing: bool = False) -> np.ndarray:
    """Highest commandable channel rate that closes with the required margin.

    In fixed-rate mode there is only one candidate rate -- GFSK at
    ``radio.fixed_rate.bitrate_kbps`` -- so the link either closes there or
    returns zero; there is no adaptive fallback to a slower rate.

    Returns the *information* rate: the channel rate divided by the FEC
    expansion, since rate-1/2 convolutional coding transmits two channel bits
    per information bit. Coding gain is deliberately not credited, which keeps
    this conservative relative to the spreadsheet.
    """
    radio = cfg.radio
    cn0 = c_over_n0_dbhz(cfg, range_m, worst_case_pointing)
    required = link_threshold_db(cfg)
    rates_bps = np.array([r * 1e3 for r in candidate_bitrates_kbps(cfg)])
    fec = float(radio.fec_overhead)

    out = np.zeros_like(cn0)
    for channel_rate in np.sort(rates_bps):
        eb_n0 = cn0 - 10.0 * np.log10(channel_rate)
        out = np.where(eb_n0 >= required, channel_rate / fec, out)
    return out


def link_margin_db(cfg: MissionConfig, range_m: float, channel_rate_bps: float,
                   worst_case_pointing: bool = False) -> float:
    """Margin for a specific range and rate, for comparison with the budget."""
    cn0 = c_over_n0_dbhz(cfg, np.array([range_m]), worst_case_pointing)[0]
    eb_n0 = cn0 - 10.0 * math.log10(channel_rate_bps)
    return float(eb_n0 - eb_n0_required_db(cfg)
                 - float(cfg.radio.implementation_loss_db))


def margin_over_threshold_db(cfg: MissionConfig,
                             range_m: np.ndarray,
                             channel_rate_bps: np.ndarray,
                             worst_case_pointing: bool = False) -> np.ndarray:
    """(N,) dB the link has in hand over what it needs, per sample.

    Positive means the link closes. This is the number the dashboard plots:
    a link that closes by 14 dB and one that closes by 0.5 dB are both "up",
    and only one of them is a design that can afford to stop pointing at the
    ground station.
    """
    cn0 = c_over_n0_dbhz(cfg, np.asarray(range_m, dtype=float),
                         worst_case_pointing)
    rate = np.asarray(channel_rate_bps, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        eb_n0 = cn0 - 10.0 * np.log10(np.where(rate > 0, rate, np.nan))
    return eb_n0 - link_threshold_db(cfg)


def downlink_needs_pointing(cfg: MissionConfig,
                            range_m: np.ndarray) -> np.ndarray:
    """(N,) whether the contact has to be flown antenna-on-station.

    Repointing the vehicle to put the +x patch on the ground station is what
    justifies the -3 dB nominal pointing loss instead of the -10 dB worst case
    where the patch is edge-on. It also costs a manoeuvre at each end, and a
    magnetorquer-only 3U takes minutes over one.

    Whether that is worth doing is a link-budget question, not a policy, so it
    is answered here rather than assumed: if the link still closes with the
    worst-case pointing loss, the repoint buys nothing and the contact is flown
    from whatever attitude the vehicle is already holding. At 9.6 kbps it
    closes by more than 13 dB at 10 deg elevation, so it never needs pointing;
    at 1 Mbps the same geometry fails by 6 dB, so it always does.
    """
    return achievable_bitrate_bps(cfg, range_m, worst_case_pointing=True) <= 0.0


def analyse_passes(cfg: MissionConfig,
                   env: EnvironmentResult,
                   worst_case_pointing: bool = False) -> list[Pass]:
    """Every pass in the propagation, with its deliverable data volume."""
    acquisition = float(cfg.radio.acquisition_overhead_s)
    dt = env.dt_s
    passes: list[Pass] = []

    for s_index, intervals in enumerate(find_passes(env, cfg)):
        for start, end in intervals:
            duration = (end - start) * dt
            if duration <= acquisition:
                continue
            ranges = env.station_range[s_index, start:end]
            elevations = env.station_elevation[s_index, start:end]
            rates = achievable_bitrate_bps(cfg, ranges, worst_case_pointing)
            # Drop the acquisition overhead from the front of the pass.
            skip = int(math.ceil(acquisition / dt))
            usable_rates = rates[skip:]
            usable_s = max(0.0, duration - acquisition)
            data_bits = float(np.sum(usable_rates) * dt)
            passes.append(Pass(
                station_index=s_index,
                station_name=env.station_names[s_index],
                start_s=float(env.t_s[start]),
                end_s=float(env.t_s[min(end, len(env.t_s) - 1)]),
                duration_s=duration,
                max_elevation_deg=float(np.degrees(np.max(elevations))),
                min_range_km=float(np.min(ranges) / 1e3),
                usable_s=usable_s,
                bytes_capacity=int(data_bits / 8.0),
            ))
    passes.sort(key=lambda p: p.start_s)
    return passes


def pass_statistics(passes: list[Pass], env: EnvironmentResult) -> dict[str, float]:
    days = env.duration_days
    keys = ("passes_total", "passes_per_day", "mean_pass_duration_min",
            "max_pass_duration_min", "total_contact_min_per_day",
            "mean_max_elevation_deg", "mean_bytes_per_pass",
            "downlink_bytes_per_day", "downlink_mb_per_day")
    if not passes:
        # Return the full key set so callers never trip over a missing entry.
        return {key: 0.0 for key in keys}
    durations = np.array([p.duration_s for p in passes])
    capacities = np.array([p.bytes_capacity for p in passes])
    elevations = np.array([p.max_elevation_deg for p in passes])
    return {
        "passes_total": len(passes),
        "passes_per_day": len(passes) / days,
        "mean_pass_duration_min": float(np.mean(durations) / 60.0),
        "max_pass_duration_min": float(np.max(durations) / 60.0),
        "total_contact_min_per_day": float(np.sum(durations) / 60.0 / days),
        "mean_max_elevation_deg": float(np.mean(elevations)),
        "mean_bytes_per_pass": float(np.mean(capacities)),
        "downlink_bytes_per_day": float(np.sum(capacities) / days),
        "downlink_mb_per_day": float(np.sum(capacities) / days / 1e6),
    }


def per_station_statistics(passes: list[Pass],
                           env: EnvironmentResult) -> list[dict[str, float]]:
    days = env.duration_days
    out = []
    for index, name in enumerate(env.station_names):
        subset = [p for p in passes if p.station_index == index]
        if subset:
            durations = np.array([p.duration_s for p in subset])
            out.append({
                "station": name,
                "passes_per_day": len(subset) / days,
                "mean_duration_min": float(np.mean(durations) / 60.0),
                "contact_min_per_day": float(np.sum(durations) / 60.0 / days),
                "bytes_per_day": float(sum(p.bytes_capacity for p in subset) / days),
            })
        else:
            out.append({"station": name, "passes_per_day": 0.0,
                        "mean_duration_min": 0.0, "contact_min_per_day": 0.0,
                        "bytes_per_day": 0.0})
    out.sort(key=lambda row: -row["passes_per_day"])
    return out


# ---------------------------------------------------------------------------
# Data budget
# ---------------------------------------------------------------------------

# Housekeeping telemetry that is downlinked in real time during a pass.
# Sizes and cadences are taken from the supplied data budget, which the user
# flagged as trustworthy for file sizes and telemetry frequency.
REALTIME_SOH = {          # bytes per sample, sample period in seconds
    "CDH":  (16, 5.0),
    "EPS":  (16, 5.0),
    "ADCS": (39, 5.0),
    "THR":  (9, 5.0),
    "PAY":  (6, 5.0),
    "COMM": (4, 5.0),
}
AGGREGATE_TELEMETRY = (90, 300.0)     # 5-minute aggregate, always stored
SAMPLE_OVERHEAD_B = 16                # per-sample framing from the budget
IMAGE_OVERHEAD_B = 64
PACKET_OVERHEAD_B = 16                # CCSDS 6 + HDLC 6 + CRC32 4
MAX_PACKET_B = 65536
MARGIN = 1.20                         # budget's 20 % margin


@dataclasses.dataclass
class DataBudget:
    experiments_per_day: float
    stored_bytes_per_day: float
    downlink_bytes_per_day: float
    image_bytes_per_day: float
    numerical_bytes_per_day: float
    telemetry_bytes_per_day: float
    storage_required_gb: float


def _with_overhead(payload_bytes: float) -> float:
    """Add packetisation, FEC and margin to a raw payload byte count."""
    packets = max(1.0, math.ceil(payload_bytes / MAX_PACKET_B))
    return (payload_bytes + packets * PACKET_OVERHEAD_B) * MARGIN


def image_bytes(cfg: MissionConfig) -> int:
    """Stored size of one compressed image."""
    payload = cfg.payload
    raw = (int(payload.image_width_px) * int(payload.image_height_px)
           * int(payload.bits_per_pixel) // 8)
    return int(raw * float(payload.compression_ratio))


def usb2_max_fps(cfg: MissionConfig) -> float:
    """Frame rate ceiling imposed by the shared USB 2.0 bus.

    Both cameras sit behind one USB 2.0 connector, and the frames crossing the
    bus are *uncompressed* -- compression happens on the OBC after transfer.
    """
    payload = cfg.payload
    raw_bytes = (int(payload.image_width_px) * int(payload.image_height_px)
                 * int(payload.bits_per_pixel) // 8)
    usable_bps = float(payload.usb2_raw_mbps) * 1e6 * float(payload.usb2_bulk_efficiency)
    frames_per_s = usable_bps / (raw_bytes * 8)
    return frames_per_s / int(payload.n_cameras)


def data_budget(cfg: MissionConfig, experiments_per_day: float,
                contact_seconds_per_day: float) -> DataBudget:
    """Bytes generated and bytes that must be downlinked for a given cadence."""
    payload = cfg.payload
    img_b = image_bytes(cfg)

    # Real-time housekeeping only flows while a pass is up.
    telemetry = 0.0
    for size, period in REALTIME_SOH.values():
        samples = contact_seconds_per_day / period
        telemetry += samples * (size + SAMPLE_OVERHEAD_B)
    agg_size, agg_period = AGGREGATE_TELEMETRY
    telemetry += (86400.0 / agg_period) * (agg_size + SAMPLE_OVERHEAD_B)

    # Only two debug images come down per day, one per camera.
    image_down = int(payload.debug_images_per_day) * (img_b + IMAGE_OVERHEAD_B)

    # Every experiment's numerical product is downlinked.
    numerical = experiments_per_day * (int(payload.numerical_bytes_per_experiment)
                                       + SAMPLE_OVERHEAD_B)

    downlink = _with_overhead(telemetry + image_down + numerical)

    # On-board storage must hold every image until it is discarded.
    stored = experiments_per_day * (int(payload.n_cameras) * img_b
                                    + int(payload.numerical_bytes_per_experiment))

    return DataBudget(
        experiments_per_day=experiments_per_day,
        stored_bytes_per_day=stored,
        downlink_bytes_per_day=downlink,
        image_bytes_per_day=float(image_down),
        numerical_bytes_per_day=float(numerical),
        telemetry_bytes_per_day=float(telemetry),
        storage_required_gb=stored / 1e9,
    )


def max_experiments_from_downlink(cfg: MissionConfig,
                                  downlink_capacity_bytes_per_day: float,
                                  contact_seconds_per_day: float) -> float:
    """Invert the data budget: how many experiments fit in the daily downlink."""
    payload = cfg.payload
    fixed = data_budget(cfg, 0.0, contact_seconds_per_day).downlink_bytes_per_day
    spare = downlink_capacity_bytes_per_day - fixed
    if spare <= 0:
        return 0.0
    per_experiment = (int(payload.numerical_bytes_per_experiment)
                      + SAMPLE_OVERHEAD_B) * MARGIN
    return spare / per_experiment
