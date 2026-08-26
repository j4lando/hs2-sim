# HS-2 Concept of Operations

How the spacecraft is flown, why each rule is the way it is, and what the
simulation says it delivers.

---

## 0. Provenance — read this first

Two independent sources are quoted below, and they are labelled throughout.

**[BSK]** — `results/summary.json`, from a Basilisk propagation: 3 days at a 5 s
step, 46.6 orbits, real IGRF-class field, real ephemeris, real station
geometry. This is the authoritative environment model.

**[SIM]** — this session's runs of the same production code
(`geometry.solve_experiment_pointing` → `conops.simulate`) on an analytic
ISS-like orbit with J2 nodal regression and a moving Sun, 3 days at 15 s,
96-azimuth attitude search, 0.5 Hz payload cadence.

> **`results/` is stale.** It was generated before the mode-entry energy budget,
> the image-store model, the pointing selector, the manoeuvre gates, the link
> margin change and array geometries D and E existed. Re-run
> `python run_analysis.py` under Basilisk to refresh it. Until then:
>
> - **Quoted freely:** environment, comms and the link budget, ADCS authority,
>   payload limits, mode power tables, the exclusion sweep. None of these depend
>   on the scheduler.
> - **Quoted with a caveat:** the single-node thermal model, which is driven by
>   the *flown attitude* and so has shifted. Directionally valid, not current.
> - **Not used:** `conops_baseline` and `binding_constraints`. They describe a
>   scheduler that no longer exists.

Where the two overlap they agree closely, which is the main reason to trust
[SIM] for the scheduler numbers:

| | [BSK] | [SIM] |
|---|---|---|
| orbit period | 92.75 min | 92.9 min |
| eclipse fraction | 38.9 % | 38.4 % |
| passes per day | 61.3 | 60.0 |
| mean pass duration | 5.14 min | 5.36 min |
| contact minutes per day | 315 | 321 |
| downlink capacity | 1032 MB/day | 1093 MB/day |
| experiment feasibility | 50.07 % | 50.8 % |
| link margin, 9.6 kbit/s, patch edge-on | 17.4 dB | 16.8 dB |

---

## 1. Vehicle and mission

A 3U CubeSat in an ISS-like orbit carrying two cameras behind one USB 2.0 bus.
An **experiment** is one FOUND frame and one LOST frame taken together, plus
122 bytes of numerical product. The science objective is to image the **sunlit
limb of the Earth**; the numerical product is downlinked and the imagery stays
on board.

Attitude control is **magnetorquer-only**. This is the single fact that shapes
the entire concept of operations: the vehicle cannot turn quickly, so every
attitude change is a scheduling commitment measured in minutes, not a reaction.

| | value | source |
|---|---|---|
| Mean altitude | 408.3 km | [BSK] |
| Orbit period | 92.75 min | [BSK] |
| Inclination | 51.64° | config |
| Eclipse fraction | 38.9 % (max 36.1 min) | [BSK] |
| Earth angular radius | 70.0° | [BSK] |
| Battery | 75.6 Wh, 80 % DoD → 20 % floor | config |
| Payload store | 128 GB = 195,312 frames | config |
| Image size | 655,360 B compressed | [BSK] |
| USB 2.0 ceiling | 13.73 experiments/s | [BSK] |
| Payload cadence (baseline) | 0.5 Hz | config |

---

## 2. Operating environment

**Beta angle.** The Basilisk run sits at low beta (0–12.8°). Feasibility was
separately swept across the **whole ±75° range** a 51.64° orbit reaches and
stays between **49.4 % and 54.7 %** [SIM]. At high |beta| the orbit is fully
sunlit so dark-limb rejections collapse from 41 % to 3 %, while FOUND's Sun
keep-out rises from 8 % to 45 %; the two almost exactly cancel. **Science
opportunity is effectively constant all year** — season is not an operational
driver.

**Ground network.** 15 Leaf Space locations. 61 passes/day, mean 5.1 min, mean
maximum elevation 34.1°, 315 contact minutes/day, 1032 MB/day of capacity
[BSK]. The mission uses 2–4 MB/day of it. **Downlink capacity is
over-provisioned by roughly 300×** and is not a mission constraint.

**Magnetic field.** Mean 35,583 nT, giving a mean control torque of 12.1 µN·m
[BSK]. Slew performance, against the real field history about the actual
eigenaxis:

| manoeuvre | best | median | p90 | worst | worst axis (along B) |
|---|---|---|---|---|---|
| 90° | 1.7 min | 3.8 min | 5.3 min | 10.0 min | 6.8 min |
| 180° | 2.6 min | 5.4 min | 7.2 min | 12.0 min | 8.6 min |

Detumble from 10 °/s takes 0.5 h. Secular momentum accumulation needs 124 s per
orbit of dumping, a 2.2 % duty cycle — negligible. [BSK]

---

## 3. Modes

| mode | load | attitude | purpose |
|---|---|---|---|
| **SAFE** | 5.94 W | Sun-pointing | survival only |
| **STANDBY** | 6.97 W | Sun-pointing | charge, wait |
| **SLEW** | 11.59 W | in transit | reorienting |
| **EXPERIMENT** | 11.32 W | FOUND on the sunlit limb | science |
| **DOWNLINK** | 20.61 W | *whatever is already held* | transmit |

[BSK] Priority is SAFE > DOWNLINK > EXPERIMENT > STANDBY, except that **a
manoeuvre already begun is committed** — only the battery may interrupt it. A
rate-limited follower chasing a target that keeps being re-decided never arrives
at any of them; this rule is what stopped whole orbits disappearing into SLEW.

Safe mode points at the Sun: the survival attitude and the charging attitude are
the same one, which is the point of retreating to it.

---

## 4. Energy: how the mode thresholds are derived

No SOC threshold in this CONOPS is a chosen number. Each is the cost of an
activity **plus the recovery from it**, worst case, in the dark, times a margin
(`--soc-margin`, default 2.00 = 200 %, applied per excursion and not
compounded). Worst-case inputs: 180° slew 12.0 min, longest eclipse 36.2 min,
longest pass 6.8 min. [SIM, `hs2sim/energy.py`]

**Survive an eclipse and recover — 5.91 Wh, 7.8 % SOC**
| | | |
|---|---|---|
| longest eclipse on safe loads | 36.2 min × 5.94 W | 3.59 Wh |
| worst slew back to sun-pointing | 12.0 min × 11.59 W | 2.32 Wh |

**Worst-case contact — 6.96 Wh, 9.2 % SOC**
| | | |
|---|---|---|
| worst slew to the downlink attitude | 12.0 min × 11.59 W | 2.32 Wh |
| longest pass transmitting | 6.8 min × 20.61 W | 2.32 Wh |
| worst slew back to sun-pointing | 12.0 min × 11.59 W | 2.32 Wh |

**Worst-case science block — 11.48 Wh, 15.2 % SOC**
| | | |
|---|---|---|
| worst slew to the experiment attitude | 12.0 min × 11.59 W | 2.32 Wh |
| science block (longest eclipse) | 36.2 min × 11.32 W | 6.84 Wh |
| worst slew back to sun-pointing | 12.0 min × 11.59 W | 2.32 Wh |

Stacked on the 20 % cell floor:

| threshold | SOC | meaning |
|---|---|---|
| **SAFE entry** | **35.6 %** | below this, survival loads only |
| **STANDBY / downlink affordable** | **54.1 %** | a whole contact and the recovery from it is funded |
| **EXPERIMENT entry** | **84.4 %** | a whole science block and the recovery from it is funded |

Because the standby threshold is the safe threshold *plus* a whole worst-case
contact, **a downlink begun from standby can never drive the vehicle into safe
mode.** That is what it is for.

The battery is integrated honestly: SOC is **not** clamped at the DoD floor.
Clamping there would keep charging each mode's full load while inventing the
energy to pay for it. SOC is allowed through the floor, dropping through the
survival reserve is what commands SAFE, and a battery reaching zero fails the
mission and says so.

---

## 5. Science operations

### 5.1 When a legal attitude exists

Experiment mode must satisfy four constraints at once: FOUND (+x, 74° FOV) on a
**sunlit** limb; Sun >70° off FOUND's boresight; neither Earth nor Sun inside
the 40° keep-out on +z (LOST and the star tracker); every cone padded by the
**1.1° pointing margin** (control 1.0° + knowledge 0.1°), because a commanded
attitude sitting exactly on a boundary is a coin flip, not a legal attitude.

A legal attitude exists **50.1 % of the time** [BSK] / **50.8 %** [SIM], and
this is **identical for every array geometry** — it depends only on the cameras,
the Earth and the Sun. Windows are long: median **46 min**, alternating with
46 min gaps. Rejections: no sunlit limb 41 %, Sun in FOUND 8 %, no legal roll
**0.0 %**.

### 5.2 Entry and exit

| | condition |
|---|---|
| **Enter** | legal attitude exists **and** SOC ≥ 84.4 % **and** room on the store for an observation worth the turn |
| **Stay** | SOC ≥ 54.1 % and the store is not full |
| **Arm** | reaching 84.4 % arms science for the **rest of the orbit** |

Entry and exit are deliberately different decisions. Starting a science block
needs the whole worst-case block funded up front; *staying* in one only needs
enough left to afford a contact and the recovery from it. Without that gap the
scheduler chattered on the entry level — drop out, turn to the Sun, charge a few
tenths of a percent, turn back — paying two multi-minute slews for a minute of
imaging.

The orbit-scoped arming exists because charge does not vary within an orbit the
way pointing windows do. Re-earning the entry level after every gap in
feasibility barred the vehicle from windows it had the energy for, purely
because it had spent the last one observing.

### 5.3 Manoeuvre discipline

Three rules, all reading quantities the ephemeris already knows, so this is
scheduling rather than reaction:

1. **A manoeuvre in progress is committed.** Only the battery interrupts it.
2. **Do not begin a manoeuvre whose reason expires before it ends.** The slew is
   priced against the real field first; if the destination will not still be
   valid on arrival for at least as long as the turn takes, it is declined and
   the vehicle holds sun-pointing. For science, validity is *not* "does a legal
   attitude exist" — feasibility can hold for a whole 46-minute window while the
   planned attitude inside it jumps every couple of minutes — so the window is
   cut wherever the plan itself steps by more than a tracking rate.
3. **A slew overrunning its priced duration by 2× is abandoned** to sun-pointing.
   The gate refuses what is foreseeably hopeless; this catches what only reveals
   itself once under way.

Declined manoeuvres are counted (`slews_skipped`) so the rule cannot hide how
often it fires: over 3 days, 19 for geometry C and 748 for B, which is itself
the signal that B lives on the SOC boundary.

**Maximum tracking rate is 0.33 °/s** across all geometries [SIM] — at the top
of the 0.26–0.36 °/s the magnetorquers deliver. This is the closest thing to a
margin violation in the whole concept and is flagged in §9.

---

## 6. Payload data flow

```
capture ──► unprocessed ──► [OBC reduction] ──► processed ──► [48 h] ──► purged
 0.5 Hz       on store        1 pair / 3 min      on store              freed
              │
              └─► 122 B numerical product ──► downlink queue ──► ground
```

Frames never leave over the link. Only the numerical product and two debug
images a day are downlinked.

**The reduction cadence, not the flash, is the real limit.** The OBC reduces one
FOUND and one LOST frame every 3 minutes — 960 frames/day. At 0.5 Hz the payload
captures eight to forty times that, so the unprocessed population grows at the
difference and the 128 GB is **days to weeks of buffer**, not a margin:

| geometry | backlog growth | store after 3 days | store full |
|---|---|---|---|
| A_2panel_90 | +6,772 frames/day | 14.7 GB | day 29 |
| B_3panel_90 | +22,287 frames/day | 45.1 GB | day 9 |
| C_2panel_135_plus_body | +36,463 frames/day | 73.0 GB | **day 5** |
| E_2panel_135_no_body | +13,301 frames/day | 27.4 GB | day 15 |

("store full" is 195,312 frames divided by the growth rate — linear, and it is
the growth rate of a vehicle that is still imaging freely. The better a geometry
performs, the sooner it stops.)

[SIM] A capture with nowhere to go does not happen: the scheduler declines to
enter experiment mode without room to sustain an observation worth the turn, and
an observation already under way runs until the store is genuinely full.

**Operational consequence:** at 0.5 Hz the mission becomes reduction-limited in
under a week on the recommended geometry, and inside a month on the weakest one
that still flies. The levers are the payload cadence, the 3-minute reduction
period, and the 48-hour retention — and only the first is free.

---

## 7. Communications

**Contacts are not flown antenna-on-station.** Turning the vehicle to put the +x
patch on a station justifies the −3 dB nominal pointing loss instead of the
−10 dB worst case, and costs a magnetorquer manoeuvre at each end. It is not
needed: at 9.6 kbit/s, from the 10° elevation mask, **with the patch edge-on**,
the link shows **17.4 dB of margin** [BSK] / 16.8 dB [SIM].

The repoint would buy *rate* — 500 kbit/s pointed against 128 kbit/s edge-on at
long range — and the mission generates 2–4 MB/day against 1032 MB/day of
capacity. So every contact is flown from whatever attitude is already held,
charged at the worst-case pointing loss so the saving is real rather than
assumed. This deleted **every comms manoeuvre in the concept.**

The requirement itself is the demodulator threshold plus **50 % more power** =
10·log₁₀(1.5) = 1.76 dB, so GFSK's 14 dB threshold becomes 15.8 dB.

Contact time is 0.10–0.20 % of the mission. The vehicle sends 2–4 MB/day and
the residual queue grows by under 0.1 MB/day, ending the 3-day run below 0.3 MB
— the queue is kept clear and the mission is not downlink-bound.

**This flips if** a faster fixed rate is commanded (at 1 Mbit/s the edge-on link
fails by 6 dB at 10° elevation and every contact needs pointing again), or if
imagery ever has to go down the link.

---

## 8. Simulated performance

3 days, 0.5 Hz, 96-azimuth search, per array geometry. [SIM]

| | peak W | observing | median obs. | images/day | slews/day | mean SOC | margin |
|---|---|---|---|---|---|---|---|
| A_2panel_90 | 14.8 | 8.9 % | 22.8 min | 7,730 | 15 | 80.2 % | +0.09 W |
| B_3panel_90 | 22.0 | 26.9 % | 26.8 min | 23,245 | 40 | 86.7 % | +0.40 W |
| **C_2panel_135_plus_body** | 22.3 | **43.3 %** | 28.2 min | **37,420** | 37 | 97.6 % | **+1.65 W** |
| E_2panel_135_no_body | 14.8 | 16.5 % | 27.5 min | 14,260 | 21 | 81.1 % | +0.03 W |

Mode split for the recommended geometry C: experiment 43.3 %, standby 46.8 %,
slew 9.6 %, downlink 0.20 %, **safe 0.00 %**.

**C is the recommended configuration.** It converts 85 % of the pointing
opportunity every geometry shares, is the only one with real energy margin, and
never enters safe mode.

**A and E have no energy margin** (+0.09 W and +0.03 W). They fly without
entering safe mode in this run but have nothing in hand for degradation.

A fifth option, `D_2panel_135_minus_x` — a single deployable wing on the -x
face folded to a 135° dihedral — was evaluated and **removed** from the config.
It traded peak power for tolerance to Sun direction, which a vehicle that can
point at the Sun has no use for, and it was the worst of the set by a wide
margin. It is gone; this section records that it was tried.

Two results worth carrying into the design review:

- **The body-mounted panel is worth 2.6× the science.** C against E: 7.5 W of
  extra peak power (a third more) turns 14,260 images/day into 37,420, because
  the 84.4 % entry threshold is a cliff and modest power differences are
  amplified across it.
- **Where the array sits relative to FOUND's boresight is worth about as much as
  a third panel.** A and E are the *same* flat 14.8 W surface in different body
  orientations — identical in standby, since the vehicle turns to face the Sun
  either way. In experiment mode the attitude is pinned by the cameras, and A's
  normal is exactly opposite FOUND's boresight, so whenever FOUND is on the limb
  the array points as far from useful as possible. E's normal sits 45° off and
  gets nearly twice the images from the same panel.

---

## 9. Constraints, margins and watch items

| constraint | status |
|---|---|
| Pointing feasibility (50 %) | **Hard ceiling.** Set by the cameras and the orbit; identical for all geometries; flat across the whole beta range. |
| On-board reduction (960 frames/day) | **Binding within weeks** at 0.5 Hz. The real limit on total science. |
| Energy | **Binding for D** (−0.58 W). **Marginal for A and E** (under +0.1 W). Thin for B (+0.40 W). Comfortable only for C (+1.65 W). |
| Slew rate | **Watch item.** Peak tracking demand 0.33 °/s against 0.26–0.36 °/s available. |
| Downlink capacity | Not binding. ~300× over-provisioned. |
| USB 2.0 bus | Not binding. 13.7 experiments/s against 0.5 Hz commanded. |
| Flash capacity | Not binding *directly* — the reduction backlog reaches it first. |
| Thermal | Comfortable. Geometry C runs +0.5 °C to +30.7 °C with battery margins of 10.5 °C cold and 14.3 °C hot; the coldest case across geometries is B at −6.9 °C (3.1 °C of cold margin). [BSK], on the superseded attitude history — see §0. |
| Momentum | Not binding. 2.2 % duty cycle. |

### Exclusion angles

Of the three keep-out cones, **only FOUND's Sun exclusion binds.**

- **FOUND Sun (70°)** — the only sensitive one. −74.9 images/day per degree
  loosened [BSK]. Relaxing 70° → 30° recovers 5.7 points of feasibility.
- **+z Sun (40°, LOST and star tracker)** — **exactly zero sensitivity.**
  Feasibility is unchanged from 20° through 60°, and the "no legal roll"
  rejection is 0.0 % throughout: the roll freedom about FOUND's boresight always
  finds somewhere legal for +z. Tightening this cone is free.
- **+z Earth (40°)** — 30° of slack. First bites at 70°, hurts at 80°.

Even with a 30° FOUND cone the ceiling is about 58 %, because ~41 % of the time
there is no sunlit limb at all. That is eclipse and geometry, and no optical
requirement touches it.

---

## 10. Contingencies

| event | response |
|---|---|
| SOC < 35.6 % | SAFE latches; survival loads; sun-pointing. Exits at 45.6 % (10 % hysteresis) — not at the entry level, so it cannot chatter. |
| SOC reaches 0 | Mission failed. Recorded with the time and the unserved demand; nothing after it is meaningful. |
| Store full | Experiment mode is not entered. Imaging resumes as retention frees room for an observation worth the turn. |
| Slew will not converge | Declined before starting if foreseeable; abandoned to sun-pointing at 2× its priced duration otherwise. Both counted. |
| Field geometry blocks a manoeuvre | Counted as `slews_unreachable` (0 in every run to date). |
| Detumble | 0.5 h from 10 °/s. |

---

## 11. Recommendations

1. **Fly geometry C.** It is the only configuration with meaningful energy
   margin, and it delivers 1.6× geometry B.
2. **Re-run `run_analysis.py` under Basilisk.** The scheduler numbers in §4–§6
   and §8 are all [SIM]; `results/` predates every one of the changes behind
   them, and this document should be reissued against a refreshed
   `summary.json`.
3. **Decide the payload cadence against the reduction cadence, not the flash.**
   0.5 Hz makes the mission reduction-limited in under a week on geometry C.
   Either lower the cadence, speed up reduction, or accept a duty-cycled
   campaign.
4. **Confirm the 0.33 °/s tracking demand is flyable**, or raise
   `intra_mode_slew_threshold_deg` and accept more charged manoeuvres.
5. **Do not spend engineering on the +z keep-out.** It has measurably zero effect
   on science. Every degree of optical work belongs on FOUND's Sun exclusion, or
   on the 1.1° pointing budget, which enters the same inequality.

---

## Further reading

- [POINTING.md](POINTING.md) — why geometries differ, and where the slewing went
- [LINK_BUDGET.md](LINK_BUDGET.md) — the margin, and why pointing at stations stopped
- [IMAGE_STORE.md](IMAGE_STORE.md) — capture, reduction and the purge
- [BATTERY_POWER.md](BATTERY_POWER.md) — the per-orbit power and charge figures
- [DASHBOARD.md](DASHBOARD.md) — the interactive timeline and flight view
- [VIZARD.md](VIZARD.md) — 3D playback
