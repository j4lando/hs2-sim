"""The payload image store: capture, reduction cadence, and the purge."""

from __future__ import annotations

import numpy as np

from helpers import orbit_env
from hs2sim import adcs, comms, conops, geometry, power, storage
from hs2sim.config import MissionConfig


def a_store(cfg, n, dt):
    return storage.ImageStore(cfg, dt, n)


def test_capture_and_reduction_run_at_their_own_rates():
    """Frames arrive when the payload images; they leave on the OBC's clock."""
    cfg = MissionConfig()
    dt, n = 60.0, 200
    store = a_store(cfg, n, dt)
    per_period = float(cfg.payload.processing_period_s)
    per_experiment = int(cfg.payload.n_cameras)

    # One experiment per step for the first ten steps, then nothing.
    for i in range(n):
        store.offer(i, 1.0 if i < 10 else 0.0)
    out = store.result()

    assert out.captured_total[-1] == 10 * per_experiment
    # Reduction is a fixed cadence, not a per-image cost: over the whole run it
    # can only have got through n*dt/period frames per camera.
    ceiling = per_experiment * n * dt / per_period
    assert out.processed_total[-1] <= ceiling + 1e-9
    # And it never processes more than was captured.
    assert out.processed_total[-1] <= out.captured_total[-1] + 1e-9


def test_a_processed_frame_still_occupies_the_disc_until_its_retention_expires():
    """Processing is not deletion. The store has to hold both populations."""
    cfg = MissionConfig()
    dt = 600.0
    retention_s = float(cfg.payload.processed_retention_h) * 3600.0
    n = int(3 * retention_s / dt)
    store = a_store(cfg, n, dt)
    for i in range(n):
        store.offer(i, 1.0 if i == 0 else 0.0)
    out = store.result()

    hold = int(round(retention_s / dt))
    # Everything captured is reduced almost at once at this step size, but it
    # is still resident right up to the retention boundary...
    assert out.stored_images[hold - 1] > 0
    # ... and gone after it.
    assert out.stored_images[-1] == 0
    assert np.isclose(out.purged_total[-1], out.processed_total[-1])


def test_the_store_refuses_what_it_has_no_room_for():
    cfg = MissionConfig().copy_with(**{"payload.storage_gb": 0.01})
    dt, n = 60.0, 400
    store = a_store(cfg, n, dt)
    for i in range(n):
        store.offer(i, 5.0)
    out = store.result()

    assert out.dropped_images > 0, "an unbounded store is not a store"
    assert np.max(out.stored_bytes) <= out.capacity_bytes + 1e-6
    # What was taken is what was offered minus what was refused.
    offered = 5.0 * int(cfg.payload.n_cameras) * n
    assert np.isclose(out.captured_total[-1] + out.dropped_images, offered)


def test_a_full_store_stops_the_scheduler_imaging():
    """Pointing and power are not the only ways to be unable to image."""
    cfg = MissionConfig()
    n, dt, period = 900, 10.0, 5580.0
    env = orbit_env(n, dt, period)
    env.shadow_factor[:] = 1.0
    ang = 2 * np.pi * env.t_s / period
    env.b_field_N = 3.5e-5 * np.stack(
        [np.cos(ang), np.sin(ang), 0.3 * np.ones_like(ang)], axis=1)
    array = power.all_array_geometries(cfg)[0]
    standby = np.tile(np.eye(3), (n, 1, 1))
    # Always legal to image, and always the attitude already held, so nothing
    # except the store can stop it.
    pointing = geometry.PointingResult(
        feasible=np.ones(n, bool), dcm_BN=standby.copy(),
        x_axis_N=np.tile([1.0, 0, 0], (n, 1)),
        z_axis_N=np.tile([0, 0, 1.0], (n, 1)),
        roll_used=np.zeros(n), array_power_frac=np.zeros(n),
        reject_reason=np.zeros(n, int))
    authority = adcs.torque_authority(cfg, env)

    roomy = conops.simulate(cfg, env, array, pointing, standby, authority,
                            0.2, [])
    # Room for a couple of hundred frames: enough that the store is a store
    # rather than a rounding error, small enough to fill inside the run.
    cramped_cfg = cfg.copy_with(**{"payload.storage_gb": 0.13})
    cramped = conops.simulate(cramped_cfg, env, array, pointing, standby,
                              authority, 0.2, [])

    assert roomy.experiments.sum() > cramped.experiments.sum(), \
        "filling the disc did not slow the payload down"
    assert cramped.store is not None
    assert np.max(cramped.store.stored_bytes) <= \
        cramped.store.capacity_bytes + 1e-6
    # It stopped by declining to enter experiment mode, not by going on
    # capturing into a full disc and throwing the frames away. The store can
    # still fill part way through a sample, so the odd fraction of a frame is
    # refused at the boundary -- but that is a rounding effect, not a policy.
    one_sample = 0.2 * env.dt_s * int(cfg.payload.n_cameras)
    assert cramped.store.dropped_images <= one_sample
    assert np.sum(cramped.mode == conops.MODE_EXPERIMENT) < \
        np.sum(roomy.mode == conops.MODE_EXPERIMENT)


def test_the_configured_cadence_is_what_is_flown():
    """One FOUND frame and one LOST frame per period -- as configured."""
    cfg = MissionConfig()
    dt = float(cfg.payload.processing_period_s)
    n = 50
    store = a_store(cfg, n, dt)
    for i in range(n):
        store.offer(i, 100.0 if i == 0 else 0.0)   # deep backlog to work off
    out = store.result()
    # One step is exactly one period, so exactly one frame per camera per step.
    per_step = np.diff(out.processed_total)
    assert np.allclose(per_step, int(cfg.payload.n_cameras))


def test_only_the_numerical_product_is_queued_for_downlink():
    """The frames stay on board; a 640 kB image never enters the link budget."""
    cfg = MissionConfig()
    n, dt, period = 400, 10.0, 5580.0
    env = orbit_env(n, dt, period)
    env.shadow_factor[:] = 1.0
    ang = 2 * np.pi * env.t_s / period
    env.b_field_N = 3.5e-5 * np.stack(
        [np.cos(ang), np.sin(ang), 0.3 * np.ones_like(ang)], axis=1)
    array = power.all_array_geometries(cfg)[0]
    standby = np.tile(np.eye(3), (n, 1, 1))
    pointing = geometry.PointingResult(
        feasible=np.ones(n, bool), dcm_BN=standby.copy(),
        x_axis_N=np.tile([1.0, 0, 0], (n, 1)),
        z_axis_N=np.tile([0, 0, 1.0], (n, 1)),
        roll_used=np.zeros(n), array_power_frac=np.zeros(n),
        reject_reason=np.zeros(n, int))
    flown = conops.simulate(cfg, env, array, pointing, standby,
                            adcs.torque_authority(cfg, env), 0.2, [])

    experiments = float(flown.experiments.sum())
    assert experiments > 0
    image_share = experiments * int(cfg.payload.n_cameras) * comms.image_bytes(cfg)
    assert flown.queue_bytes[-1] < image_share * 0.01, \
        "imagery leaked into the downlink queue"


def test_a_nearly_full_store_will_not_start_an_observation_on_a_trickle():
    """The room gate needs hysteresis for the same reason the SOC gate does.

    A full store does not stay full: processed frames age out of retention and
    free a little space. Starting an observation on that means turning to the
    limb, filling it in seconds and turning back -- two multi-minute slews for
    a fraction of a minute of imaging. Measured before this gate existed, at
    0.5 Hz on the best geometry, the median observation was 0.8 minutes and the
    vehicle slewed 82 times a day.
    """
    cfg = MissionConfig().copy_with(**{"payload.storage_gb": 1.0})
    dt = 60.0
    retention_s = float(cfg.payload.processed_retention_h) * 3600.0
    n = int(retention_s / dt) + 60
    store = a_store(cfg, n, dt)

    # Fill it, then let it sit so the earliest frames age out and free a
    # trickle -- exactly the state the gate exists for.
    i = 0
    while store.has_room() and i < n:
        store.offer(i, 1000.0)
        i += 1
    filled_at = i
    assert filled_at < n, "the store never filled"
    for j in range(filled_at, n):
        store.offer(j, 0.0)

    freed = store.room_images()
    assert freed > 0, "retention never freed anything"
    # There is room for a frame...
    assert store.has_room(1.0)
    # ...but not enough to be worth turning the spacecraft for.
    wanted = freed / int(cfg.payload.n_cameras) * 4.0
    assert not store.has_room_to_start(wanted)


def test_the_start_gate_never_demands_more_than_the_store_holds():
    """The rule is about chatter, not about refusing to image at all.

    On a vehicle whose flash holds less than one observation, asking for a
    whole one would decline every capture the mission ever tried to make.
    """
    cfg = MissionConfig().copy_with(**{"payload.storage_gb": 0.01})
    store = a_store(cfg, 10, 60.0)
    capacity_experiments = store.capacity_images / store.per_experiment
    # An empty store must accept a request far larger than it could ever hold.
    assert store.has_room_to_start(1e6)
    # And once genuinely full it must not.
    store.offer(0, capacity_experiments * 2)
    assert not store.has_room_to_start(1e6)
