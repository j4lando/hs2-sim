# The battery power figure

`results/battery_power_01.png`, `_02.png`, … — written by `run_analysis.py` for
the array geometry with the best energy margin, which is the same reference
rule the exclusion sweep uses.

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

**Mode shading.** A background wash per flown mode, through both panels.
Experiment, downlink and standby take the three categorical hues that stay
separable under colour-vision deficiency in any pairing, since the scheduler
can put any two modes next to each other. Slew is deliberately neutral: it is a
transition between identities rather than one of its own, and it abuts every
other mode. Safe takes the status-critical red.

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

**The charge panel** carries SOC in percent against the configured
depth-of-discharge floor, which is what the two power curves integrate to and
the constraint the scheduler is actually flying against. The floor stays in
frame even when the vehicle never approaches it, because how much margin is
being held is the point of the panel. Each orbit's minimum SOC is printed in
its header rather than being left to be read off the curve.
