# The battery power figure

`results/battery_power_<geometry>_01.png`, `_02.png`, … — written by
`run_analysis.py` for **every** array geometry, so the three candidates can be
compared orbit by orbit rather than only through their averages.

## What it draws

Each orbit gets a tall **power panel** over a short **state-of-charge panel**
on the same x axis. Power and charge are different quantities, so they get
different axes rather than being crushed onto one axis with two scales;
stacking them keeps the flow and the level readable against each other anyway.

**Orbit splitting.** One orbit per panel pair, six orbits per figure, cut at
ascending-node crossings. The x axis is minutes since that node, and every
panel of a given kind shares its x and y range, so a feature can be read
straight down the column across successive orbits. The run does not start on a
node, so the leading fragment is back-dated rather than slid to zero — it sits
at the phase it was actually flown at.

**Shared ranges across geometries.** The power range and the charge range are
held common across all three geometries, not just within one. Letting each
autoscale to its own data would redraw a starved timeline to fill its axis and
make it look like a healthy one — and comparing the geometries is the whole
reason three of them are drawn.

**Mode shading.** A background wash per flown mode, through both panels.
Experiment, downlink and standby take the three categorical hues that stay
separable under colour-vision deficiency in any pairing, since the scheduler
can put any two modes next to each other. Slew is deliberately neutral: it is a
transition between identities rather than one of its own, and it abuts every
other mode. Safe takes the status-critical red.

**Downlink contacts** additionally get a ▼ marker above the power panel. The
downlink budget is enormously over-provisioned — the vehicle generates about
1.7 MB/day against roughly 1000 MB/day of contact capacity — so a contact
clears the backlog in seconds, and a truthful wash for one is a single sample:
sub-pixel on a 90-minute axis, and easily read as "it never downlinked at
all". The marker makes the contact findable; the wash still shows only how
long it actually lasted.

**Eclipse.** Its own track above the washes on the power panel, not a fourth
background colour — light track is sunlit, dark is umbra (`shadow_factor <
0.5`, the same test `environment.summarise` uses). A dotted hairline drops
through both panels at each terminator crossing, so a dip ties to it by eye.

**The two power curves,** both in watts:

- **generation − load** — the power balance, what the battery is being asked to
  absorb or supply.
- **into battery** — what the battery actually took, differenced from the SOC
  history. It departs from the balance wherever the model clamps: round-trip
  losses on charge, the array shunted at a full battery, the discharge floor.
  The gap between the two curves is exactly where stored energy is not the
  thing limiting the vehicle — a flat run at zero while the balance is well
  positive means the array is being shunted.

**The charge panel** carries SOC in percent against the cell-protection floor
(red dashed) and the mode-entry thresholds the run was scheduled on (grey
dotted): safe entry, the level a downlink is affordable from, and the level a
science block is affordable from. Those come from `hs2sim/energy.py`, which
prices each activity plus the recovery from it at worst case in the dark, so
the gaps between the lines *are* the excursions the vehicle can pay for. The
floor and the thresholds stay in frame even when the vehicle never approaches
them, because how much margin is being held is the point of the panel — except
for a threshold above 100 %, which is unreachable by definition and would
flatten the curve to no purpose; the legend still reports its value. Each
orbit's minimum SOC is printed in its header rather than being left to be read
off the curve.

A pink **safe** band means the reserve ran out and the vehicle dropped to
survival loads. SOC is never propped up at the floor, so a curve that goes
through it is the model telling the truth about a deficit rather than hiding
one; if it reaches zero the run is marked as a failed mission.
