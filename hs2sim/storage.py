"""The payload image store: capture, on-board reduction, and the purge.

Imagery is the only thing on this vehicle that is generated far faster than it
leaves. The numerical product of an experiment is 122 bytes and goes down the
S-band link; the two frames it came from are 640 kB each and stay on board,
where they are reduced by the OBC and then held for a while before being
purged. So the store has three populations at any instant:

    unprocessed   captured, waiting its turn through the reduction pipeline
    processed     reduced, waiting out its retention before deletion
    (deleted)     gone

and the interesting question is whether the first one is growing. The pipeline
runs at a fixed cadence -- one FOUND frame and one LOST frame every
``processing_period_s`` -- and that cadence, not the 128 GB of flash, is what
ultimately bounds how much imaging the mission can do. A capture rate above it
does not fail immediately; it fills the store at the difference between the two
rates and fails when the store is full, which can be weeks in.

Because of that this is not a reporting layer. ``ImageStore`` is stepped by the
scheduler inside its own loop, and a capture that has nowhere to go does not
happen -- ``offer`` returns how much imagery was actually stored. A model that
let the store run past its capacity would show a mission taking images it had
no room for.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from . import comms
from .config import MissionConfig
from .environment import EnvironmentResult


@dataclasses.dataclass
class StorageResult:
    """Per-sample state of the payload store, in images and in bytes."""

    unprocessed_images: np.ndarray   # (N,) awaiting reduction
    processed_images: np.ndarray     # (N,) reduced, not yet purged
    stored_images: np.ndarray        # (N,) total resident
    stored_bytes: np.ndarray         # (N,) total resident, bytes
    captured_total: np.ndarray       # (N,) cumulative images captured
    processed_total: np.ndarray      # (N,) cumulative images reduced
    purged_total: np.ndarray         # (N,) cumulative images deleted
    dropped_images: float            # captures refused for want of room
    capacity_bytes: float
    image_bytes: int
    processing_period_s: float
    retention_s: float

    @property
    def full(self) -> bool:
        return self.dropped_images > 0

    def summary(self, env: EnvironmentResult) -> dict[str, float]:
        days = env.duration_days
        return {
            "images_captured": float(self.captured_total[-1]),
            "images_processed": float(self.processed_total[-1]),
            "images_purged": float(self.purged_total[-1]),
            "images_dropped_store_full": float(self.dropped_images),
            "images_resident_final": float(self.stored_images[-1]),
            "stored_gb_final": float(self.stored_bytes[-1] / 1e9),
            "stored_gb_peak": float(np.max(self.stored_bytes) / 1e9),
            "capacity_gb": float(self.capacity_bytes / 1e9),
            "store_full_fraction": float(
                np.mean(self.stored_bytes >= self.capacity_bytes * 0.999)),
            "processing_capacity_images_per_day": float(
                2.0 * 86400.0 / self.processing_period_s),
            "unprocessed_growth_images_per_day": float(
                (self.unprocessed_images[-1] - self.unprocessed_images[0]) / days),
            "processing_backlog_final": float(self.unprocessed_images[-1]),
        }


class ImageStore:
    """Stateful payload store, stepped once per scheduler sample.

    Deletion is scheduled rather than integrated: a frame processed at step *i*
    is purged at step ``i + retention_steps``, so the history of what was
    processed when *is* the deletion schedule and no separate age bookkeeping is
    needed.
    """

    def __init__(self, cfg: MissionConfig, dt_s: float, n_samples: int):
        payload = cfg.payload
        self.dt = float(dt_s)
        self.n = int(n_samples)
        self.per_experiment = int(payload.n_cameras)
        self.image_bytes = comms.image_bytes(cfg)
        self.capacity_bytes = float(payload.storage_gb) * 1e9
        self.capacity_images = self.capacity_bytes / self.image_bytes
        self.processing_period_s = float(payload.processing_period_s)
        self.retention_s = float(payload.processed_retention_h) * 3600.0
        # One frame per camera per period.
        self.rate_images_per_s = self.per_experiment / self.processing_period_s
        self.retention_steps = max(1, int(round(self.retention_s / self.dt)))

        self._unprocessed = 0.0
        self._processed = 0.0
        self._processed_at = np.zeros(self.n)
        self._unprocessed_hist = np.zeros(self.n)
        self._processed_hist = np.zeros(self.n)
        self._captured_hist = np.zeros(self.n)
        self.dropped_images = 0.0

    def room_images(self) -> float:
        return max(0.0, self.capacity_images - self._unprocessed - self._processed)

    def has_room(self) -> bool:
        """Is there space for at least one more experiment's worth of frames?"""
        return self.room_images() >= self.per_experiment

    def offer(self, i: int, experiments: float, processing: bool = True) -> float:
        """Take up to ``experiments`` experiments' worth of frames at step ``i``.

        Returns the number of experiments actually stored -- less than offered
        only when the store is full, which is the one case where the scheduler
        has to stop imaging for a reason that is neither pointing nor power.
        """
        wanted = float(experiments) * self.per_experiment
        room = self.room_images()
        stored = min(wanted, room)
        self.dropped_images += wanted - stored
        self._unprocessed += stored

        # Reduction runs at its own fixed cadence, independent of what is being
        # captured; it is a queue being worked off, not a per-image cost.
        if processing:
            done = min(self._unprocessed, self.rate_images_per_s * self.dt)
            self._unprocessed -= done
            self._processed += done
            self._processed_at[i] = done

        # Anything processed a full retention ago goes now.
        expired = i - self.retention_steps
        if expired >= 0:
            self._processed -= self._processed_at[expired]

        self._captured_hist[i] = stored
        self._unprocessed_hist[i] = self._unprocessed
        self._processed_hist[i] = self._processed
        return stored / self.per_experiment if self.per_experiment else 0.0

    def result(self) -> StorageResult:
        stored_images = self._unprocessed_hist + self._processed_hist
        purged = np.concatenate([
            np.zeros(min(self.retention_steps, self.n)),
            self._processed_at[:max(0, self.n - self.retention_steps)]])
        return StorageResult(
            unprocessed_images=self._unprocessed_hist,
            processed_images=self._processed_hist,
            stored_images=stored_images,
            stored_bytes=stored_images * self.image_bytes,
            captured_total=np.cumsum(self._captured_hist),
            processed_total=np.cumsum(self._processed_at),
            purged_total=np.cumsum(purged),
            dropped_images=self.dropped_images,
            capacity_bytes=self.capacity_bytes,
            image_bytes=self.image_bytes,
            processing_period_s=self.processing_period_s,
            retention_s=self.retention_s,
        )
