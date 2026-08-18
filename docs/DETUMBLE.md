# Detumble and sun acquisition

A Monte Carlo study of the phase before everything in the CONOPS analysis: the
spacecraft separates from the deployer tumbling, and has to stop spinning and
get its solar array facing the Sun using magnetorquers, an IMU and a handful
of photodiodes. This document states the algorithm, the assumptions and what
each is worth.

Run it with:

```
python run_detumble.py                 # 200 trials x 6 h, all three geometries
python run_detumble.py --quick         # smoke test
python run_detumble.py --no-albedo     # the albedo sensitivity case
```

Basilisk is required. The orbit, magnetic field, Sun and eclipse all come from
`hs2sim.environment.propagate` — the same propagation `run_analysis.py` uses,
with the same J2 gravity, the same centred dipole field and the same eclipse
module. This analysis adds attitude and nothing else.

---

## 1. The one thing that makes this hard

A magnetorquer produces a dipole `m` and the field does the rest:

```
tau = m x B
```

The cross product means **there is never any torque about the field
direction**. The vehicle is instantaneously under-actuated in a direction that
sweeps around as the orbit carries it through the field, roughly twice per
revolution at this inclination. No amount of gain makes torque appear along
`B`.

Every control torque in this simulation is formed that way, from a realisable
dipole and the true local field at the true position. Nothing applies a torque
vector directly. That is why the answer had to be simulated: the useful
authority depends on where the field is pointing relative to the axis you want
to turn about, which changes continuously and is different for every trial.

The controller computes a **desired** torque and then asks for the dipole that
comes closest to producing it:

```
m = (B x tau_desired) / |B|^2
```

which is the minimum-norm dipole satisfying `m x B = tau_perpendicular`, and

```
tau_applied = m x B = tau_desired - (tau_desired . Bhat) Bhat
```

The component along `B` is **dropped** — not redirected, not scaled up to
compensate. `tests/test_detumble.py` pins this down directly.

---

## 2. The algorithm

Two modes, one projection. That is the whole of it.

### Mode DETUMBLE — B-cross rate damping

```
tau_desired = -k_detumble * omega_measured
```

`omega_measured` is the IMU gyro. This is the rate-feedback ("B-cross" or
"omega-cross") variant rather than classic B-dot: with a gyro on board there
is no reason to differentiate the magnetometer to estimate the rate, and the
gyro is both quieter and unaffected by the coils' own field.

The applied torque is the perpendicular part of `-k omega`, so
`omega . tau <= 0` always: the law is dissipative by construction and the
rotational kinetic energy can only fall. It cannot be destabilised by bad
geometry, only slowed down by it.

`k_detumble = 1.0e-4 N m s`. With `|B| ~ 3e-5 T` the coils saturate once
`|omega| > 3.4 deg/s`, so the controller is effectively bang-bang through the
whole high-rate phase and becomes linear only in the last few deg/s, which is
where linearity is worth having. This gain barely matters: while saturated the
detumble rate is set by the dipole limit and the field, not by `k`.

### Mode SUN — cross-product acquisition

```
tau_desired = k_p (a x s_measured) - k_d omega_measured
```

`a` is the body axis that wants to face the Sun and `s_measured` is the sun
sensor estimate. `a x s` is the standard two-axis attitude error: its magnitude
is the sine of the pointing error, and it vanishes at both 0 and 180 deg, so
the `-k_d omega` term is what makes 0 deg the stable one and 180 deg the
unstable one. The damping term is load bearing, not decoration.

Rotation **about** `a` is left entirely uncommanded. It does not affect power,
and not controlling it means never spending field authority on something that
buys nothing.

`a` is the power-weighted mean of the array's panel normals. That is not a
heuristic: setting the derivative of `sum_p w_p cos(theta_p)` to zero puts the
optimum exactly along the power-weighted normal when all panels are lit. For
the baseline 135 deg wing plus body panel it lands 30.2 deg off +y, which is
the true optimum to the digit (`test_array_power_axis_is_the_optimum_pointing_direction`).

**The gains were swept, not sized, and the textbook sizing is wrong here.**
Reading the loop as second order — pick a bandwidth from the available torque,
then damp it near critically — gives `k_p = 2e-6 N m`, `zeta = 0.7`, and that
is one of the *worst* combinations in the sweep. The derivation assumes a
fully actuated plant. This one is not: only the part of the demand
perpendicular to `B` is ever delivered, so a heavily damped loop spends its
authority fighting a rotation the proportional term is already struggling to
produce.

| `k_p` (N m) | `zeta` | capture | sun error | dipole used |
|---|---|---|---|---|
| 6e-6 | 0.50 | 0.584 | 54.0 deg | 0.13 |
| 2e-5 | 0.15 | 0.695 | 44.0 deg | 0.28 |
| **2e-5** | **0.25** | **0.669** | **44.7 deg** | **0.22** |
| 2e-5 | 0.50 | 0.612 | 51.7 deg | 0.19 |
| 6e-5 | 0.25 | 0.673 | 45.2 deg | 0.30 |
| 2e-4 | 0.50 | 0.613 | 51.4 deg | 0.37 |

`k_p = 2.0e-5 N m`, `k_d = 5.0e-4 N m s` (`zeta = 0.25`). Capture is flat from
`2e-5` to `6e-5`, so the lower gain is flown because it draws a third less coil
power for the same pointing. `zeta = 0.15` edges the median up but drops the
10th percentile from 0.50 to 0.40 — it wins on the good trials and loses on the
bad ones, which is the wrong way round for an acquisition mode.

Under-damping only goes so far: below `zeta ~ 0.15` the vehicle stops settling
and drifts around the target instead. The optimum is a compromise between
authority spent turning and authority spent stopping, and it sits well below
the value a fully actuated design would use.

### Mode logic

```
DETUMBLE -> SUN    when |omega_measured| < 0.5 deg/s for 60 s continuously
SUN -> DETUMBLE    when |omega_measured| > 2.0 deg/s
```

Two thresholds and a dwell timer. The hysteresis stops a momentary dip during
a tumble from tripping the mode, and the dwell stops chatter at the boundary.

### Eclipse and lost fixes

When the vehicle is in shadow, or fewer than two sun sensor channels are lit,
the `k_p` term is simply dropped:

```
tau_desired = -k_d omega_measured
```

Pure rate damping drives `omega` to zero, which **holds the inertial attitude**
where it was rather than letting it drift. No sun vector is propagated, no
attitude is estimated, nothing is remembered across the eclipse. When the Sun
comes back the error term comes back with it.

### What is deliberately absent

No attitude determination filter, no quaternion estimate, no gyro bias
estimation, no B-dot, no reaction wheels, no momentum management, no albedo
compensation, no sun sensor calibration, no eclipse prediction, no spin
stabilisation. The brief was minimal logic, and the interesting question is
what minimal logic is *worth* — which needs the minimal version simulated, not
argued about.

---

## 3. The sun sensor

**Silonex SLCD-61N8 solderable planar photodiode**, from the supplied
datasheet (104118 REV 0):

| Parameter | Value |
|---|---|
| Sensitive area | 2.7 mm² |
| I_SC | 100 min / 170 typ µA at 25 mW/cm², 2854 K |
| Acceptance half angle | 60 deg |
| Reverse dark current | 1.7 µA max at V_R = 5 V |
| Spectral range | 400–1100 nm, peak 930 nm, 0.55 A/W at 940 nm |

**Angular response.** The datasheet's directional sensitivity plot is quoted
with a 60 deg half angle, and `cos 60 = 0.5` exactly. A flat, unpackaged planar
photodiode should be a cosine (Lambertian) receiver, and the datasheet says it
is one. So:

```
I(theta) = I_sun * max(0, cos theta)
```

with a hard zero past 90 deg, because the die is mounted flush on a body face
and the structure occults anything behind the face plane. No lens, no baffle,
no aperture correction. If the flight part gets a cover glass or a recessed
aperture, this is the first thing to re-measure.

**Solar scaling.** The datasheet stimulus is a 2854 K tungsten lamp. Incident
power on the die at 25 mW/cm² is `250 W/m² × 2.7e-6 m² = 675 µW`, so the
effective responsivity to that source is `170 µA / 675 µW = 0.252 A/W` — well
below the 0.55 A/W quoted at 940 nm, because a 2854 K blackbody puts most of
its energy past 1100 nm where silicon is blind. AM0 sunlight is bluer, and
integrating silicon's response over AM0 lands within roughly 10 % of the same
number, so short-circuit current is scaled linearly with irradiance:

```
I_sun(AM0) = 170 µA × 1361/250 = 926 µA
```

`solar_spectral_factor` in `config/detumble.yaml` is the knob that absorbs the
mismatch; it is 1.0 by default, and it is the second thing to replace with a
measurement.

**Signal chain.** 12-bit ADC, full scale 1.10 mA (19 % headroom on 926 µA, so
a normal-incidence Sun does not clip). A channel counts as lit above 2 % of the
normal-incidence current — 22 µA, comfortably above the 1.7 µA dark current,
corresponding to about 88.6 deg incidence.

### Determining the Sun direction

The entire flight algorithm: take every channel above the dark threshold and
solve

```
minimise over v    sum_lit ( I_i - n_i . v )^2      then    s = v / |v|
```

Each lit channel contributes `I_i = k (n_i . s)`, so the solve recovers `k s`,
and the normalisation removes the unknown gain `k`. That is what makes the
estimate immune to the datasheet's 100-to-170 µA spread, to the solar spectrum
scaling and to the Sun–Earth distance: **none of those need to be known**.

A fix is declared valid when at least two channels are lit and the vehicle is
in sunlight. Nothing else is checked.

---

## 4. The three geometries, and the result that falls out of the geometry alone

| | boresights | sensors | rank |
|---|---|---|---|
| `four_side_faces` | ±x, ±y | 4 | 2 |
| `canted_y_pair` | ±y, ±(−0.707, 0.707, 0) | 4 | 2 |
| `six_faces` | ±x, ±y, ±z | 6 | 3 |

**Both four-sensor layouts have every boresight in the body xy plane.** No
combination of their readings carries any information about the Sun's z
component, for any Sun direction, with any estimator. This is rank, not noise:
it cannot be fixed in software. What the least squares solve returns instead is
the true Sun vector **projected into the xy plane**, which it recovers
essentially exactly.

That projection is not a failure mode to work around. Every solar array option
in `config/spacecraft.yaml` has its panel normals in the body xy plane —
`(-1,0,0)` for options A and B, `(-0.707, 0.707, 0)` and `(0,1,0)` for option C.
A body-fixed array whose normals lie in that plane **cannot be pointed out of
it**, so the in-plane projection is precisely the direction the array should be
turned towards. The unmeasurable component is also the uncontrollable one.

What the four-sensor sets genuinely cost is the ability to know how much power
is available: a Sun 60 deg out of the xy plane looks identical to a Sun in it,
and the array will make `cos 60 = 0.5` of what the controller thinks. Whether
that matters is a power and CONOPS question, not a detumble one.

There is a consolation prize that is not obvious until it is simulated: **the
coplanar sets are partly immune to albedo.** Earth-reflected light pulls the
estimate towards nadir, and the component of that pull perpendicular to the xy
plane is invisible to a layout that cannot see out of the plane. Measured
inside its own sensed subspace, `four_side_faces` is *more* accurate than
`six_faces` (17.4 deg against 19.3 deg median) — it is only blind to the part
of the error it is also blind to the signal in. It still loses overall, because
being unable to tell a 60 deg out-of-plane Sun from an in-plane one costs more
than the albedo immunity is worth.

**The two four-sensor layouts are not equivalent.** Both light exactly two
channels at a time (their normals form two antipodal pairs, so one of each pair
is always lit), and both have the same sky coverage. They differ in
conditioning: `canted_y_pair` puts two of its normals 45 deg apart, so for Sun
directions falling between the pairs it is solving for a direction from what is
effectively one useful reading. The measured noise amplification is 1.85x that
of the orthogonal four-face set, and 1 % reading noise turns into 2.65 deg of
error at the 95th percentile against 1.83 deg. `four_side_faces` dominates
`canted_y_pair` — same part count, same coverage, strictly better conditioning
— so there is no case for the canted layout unless something outside this
analysis forces it.

---

## 5. Assumptions

Ordered by how much they should worry you.

### 5.1 The IMU includes a magnetometer

**This is the load-bearing assumption of the whole analysis.** Every magnetic
control law needs the local field vector, and the vehicle has no other field
sensor. `config/spacecraft.yaml` lists a single `imu` at 0.22 W; a part in that
class is normally a 9-DOF MEMS module with a magnetometer on it, and that is
what is assumed here.

**If the flown IMU is gyro-only, none of the control laws in this document can
be flown as written.** That is a hardware question to settle before anything
else here is worth reading.

### 5.2 Earth albedo is modelled, and it dominates the sun sensor error

Basilisk's eclipse module gives direct sunlight only. Reflected light off Earth
is added on top, as a uniform Lambertian sphere:

```
E = a S sin^2(rho) max(0, cos gamma) (1 + cos z)/2
```

`rho` is Earth's angular radius, `gamma` the angle off nadir, `z` the solar
zenith angle at the sub-satellite point. The last factor is the sunlit fraction
of the visible disc: 1 with the Sun overhead, 1/2 at the terminator, 0 on the
night side.

This is deliberately coarse — a proper model would integrate a gridded
reflectivity map over the visible cap — but the magnitude is not in doubt. At
415 km, `sin^2 rho = 0.88`, so a nadir-facing photodiode over a fully sunlit
sub-satellite point sees `0.3 x 1361 x 0.88 = 360 W/m²`: **a quarter of the
direct solar signal, arriving from a completely different direction.**

It is the largest sun sensor error by an order of magnitude. Running with
`--no-albedo` is the way to price it, and the two cases should be read
together: the difference between them is the value of albedo compensation that
the minimal flight software does not do.

### 5.3 Magnetometer and coils cannot both be on

A 0.2 A m² dipole at 10 cm produces of order 40 µT at the sensor, comparable to
the entire Earth field. The field cannot be measured while the coils are
energised. The simulation interleaves, as real CubeSats do: coils off for the
first 0.25 s of every 1 s control cycle, sample, then hold the commanded dipole
for the remaining 0.75 s. That costs a quarter of the available impulse, and
the cost is modelled rather than assumed away.

### 5.4 Everything else

| Assumption | Value | Why, and what it moves |
|---|---|---|
| Post-deployment tumble | random axis, 2–20 deg/s | Brackets the 10 deg/s in `spacecraft.yaml`; the upper end covers a bad separation tip-off. Sets detumble time roughly linearly. |
| Initial attitude | uniform over SO(3) | Shoemake's method. No preferred deployment orientation is claimed. |
| MT01 z-axis dipole | 0.20 A m² | Not clearly published; assumed equal to the CubeSpace x/y coils. Scales all torques on z. Worth a sweep. |
| Gyro | 0.15 deg/√hr ARW, 8 deg/hr in-run, 60 deg/hr turn-on, 16-bit over ±500 deg/s | Representative MEMS, not a specific part. Turn-on bias redrawn per trial. |
| Magnetometer | 300 nT noise, 800 nT turn-on bias, 2 % scale, 1 deg alignment | The bias is dominated by the bus hard iron, not the part. |
| Magnetorquers | 5 % scale error, 1 deg misalignment, per-axis saturation | Saturation is applied per axis because that is what the hardware does, so a saturated command points slightly differently from the demand — and the truth model propagates that. |
| Photodiode gains | uniform over the 100–170 µA datasheet spread, per channel, uncalibrated | Costs a few degrees of sun vector error, an order of magnitude below albedo — which is the argument for not calibrating. |
| Disturbances | gravity gradient, residual dipole (5 mA m², random direction), aero at 3e-12 kg/m³ | Total roughly 4e-7 N m against 6e-6 N m of control authority, so they slow convergence rather than prevent it. |
| Sun sensor temperature | 20 C, dark current tempco 10 %/C | Only affects the dark offset, which is 0.1 % of a lit reading. Negligible. |
| Integration | RK4 at 0.25 s, environment held over each 1 s control cycle | Free rigid-body momentum and energy hold to a few parts in 10⁶ over 1000 s at 20 deg/s. The *body* field is recomputed at every RK4 stage; only the inertial-frame quantities are held, and over 1 s those move the vehicle 7.6 km out of 6790 km. |
| Environment dispersion | 8 propagations at evenly spaced RAAN, random start time within each | RAAN is what moves the beta angle, which sets eclipse fraction and Sun-to-orbit-plane geometry. 8 cases is a cost knob: each is a full Basilisk run. It is a coarse sampling of the environment — 25 trials share each field history — and is the first thing to raise if the tails look lumpy. |

### 5.5 Known limitations

- **Rigid body, no flexible modes.** The deployable wing is treated as rigid
  and its inertia is inside the solid-box figure in `spacecraft.yaml`. A real
  wing has a first mode low enough that a bang-bang detumble will excite it.
- **The wing is assumed already deployed.** Real sequencing usually detumbles
  stowed, which has a very different inertia tensor. Re-running with a stowed
  inertia is a config change, not a code change.
- **No magnetorquer hysteresis or thermal derating.** Coils are linear up to
  saturation.
- **The albedo model is a single Lambertian sphere**, not a reflectivity map,
  and it has no cloud or surface variability.
- **8 environment cases is coarse.** Sensible for scanning; raise it before
  quoting a 95th percentile as a requirement.

---

## 6. What comes out

`results/detumble_summary.json` carries every number; the figures are:

| Figure | Shows |
|---|---|
| `detumble_rate.png` | Body rate against time, median and 10–90 % band |
| `detumble_time_cdf.png` | Distributions of time-to-detumble and time-to-acquire |
| `detumble_power_capture.png` | Array output against time, as a fraction of the best any attitude could do |
| `detumble_sun_error.png` | Sun vector error, full 3-D and within each layout's sensed subspace |
| `detumble_sky_coverage.png` | Coverage and conditioning from geometry alone, no dynamics |
| `detumble_steady_state.png` | Final-orbit box plots: capture, pointing error, fix availability, dipole use |

Two metric definitions worth knowing before reading them:

- **Capture is normalised by the best any attitude can reach**, not by the
  array's peak rating. A body-fixed array cannot reach its rating unless every
  panel shares a normal: the baseline 135 deg wing plus body panel tops out at
  0.932. Scoring against 1.0 would charge the controller 7 % for geometry it
  cannot do anything about.
- **Sun acquisition is judged on sunlit potential**, with eclipse excluded, so
  a trial that acquires the Sun just before entering shadow counts as having
  acquired it. Eclipse enters the separate orbit-average energy number.


---

## 7. Indicative results

**These numbers were produced against the Basilisk-free test fixture in
`tests/helpers.py`, not against Basilisk**, because Basilisk was not available
where the code was written. The fixture is a circular orbit with a tilted
centred dipole field, a real Sun direction and a cylindrical shadow — close
enough to size the gains against and to establish the ordering of the
geometries, but it has no J2, no penumbra and no orbital eccentricity.
`run_detumble.py` regenerates all of it properly. Expect the ordering to hold
and the second decimal to move.

48 trials, 8 h each, 8 orbit planes, baseline `C_2panel_135_plus_body` array,
albedo on:

| | detumble | acquire | steady capture (p05) | pointing error | Sun estimate error, 3-D / in-plane | orbit-average power |
|---|---|---|---|---|---|---|
| `four_side_faces` | 100 % @ 42 min | 100 % @ 67 min | 0.634 (0.430) | 49.1 deg | 41.1 / 17.4 deg | 0.414 |
| `canted_y_pair` | 100 % @ 42 min | 100 % @ 71 min | 0.597 (0.432) | 51.3 deg | 46.4 / 26.1 deg | 0.377 |
| `six_faces` | 100 % @ 43 min | 100 % @ 67 min | **0.706 (0.508)** | **42.9 deg** | 19.3 / 19.3 deg | **0.484** |

Capture is a fraction of the best any attitude could reach; orbit-average power
is a fraction of the array's peak rating including eclipse.

What it says:

1. **Detumble is easy and the sun sensors are irrelevant to it.** Every trial
   detumbled, in 42 min median and under 85 min worst case, and all three
   geometries are within half a minute of each other — B-cross uses the gyro
   and the magnetometer only. Detumble is not a discriminator for this trade.
   The initial rate barely matters either: the coils are saturated through the
   whole high-rate phase, so the time is set by the momentum to be removed
   divided by an almost constant torque.

2. **Sun acquisition is where the geometries separate**, and `six_faces` wins:
   0.71 of achievable array output against 0.63 and 0.60, and a 5th percentile
   of 0.51 against 0.43. Two extra photodiodes on the z faces buy about 11 %
   more orbit-average power and, more importantly, lift the bad trials.

3. **`four_side_faces` dominates `canted_y_pair`** on every measure — same part
   count, same sky coverage, better conditioning, better pointing. There is no
   case for the canted layout on these results.

4. **Nothing gets close to 1.0, and albedo is why.** Uncompensated Earth albedo
   is a 20 deg bias on the Sun estimate, and it rotates with the orbit rather
   than averaging out. Running `--no-albedo` moves the estimate error from
   20 deg to 4 deg and the capture from 0.61 to 0.69 on an otherwise identical
   case. Roughly half the remaining pointing error is albedo; the other half is
   the under-actuation, which no sun sensor fixes.

5. **Coil use is low.** Median dipole is 0.10-0.17 of what is installed, so the
   magnetorquers are not the binding constraint on acquisition — the field
   geometry is. Bigger coils would not help much; a smarter controller, or
   albedo compensation, would.

### What to look at next

- **Albedo compensation.** The largest single error, and the cheapest to
  attack: a nadir estimate is available from the orbit, and subtracting a
  modelled albedo term is a few lines. Worth roughly 8 points of capture on
  these numbers.
- **A stowed-configuration run.** Real sequencing detumbles before deployment,
  and the inertia tensor is different. Config change, not code.
- **The MT01 z-axis dipole.** Assumed at 0.20 A m². It sets all torque about
  the long axis, which is the low-inertia one, and is the least defensible
  actuator number in the model.
- **More environment cases.** Eight propagations is coarse for quoting a 95th
  percentile.
