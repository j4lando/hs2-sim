# The link, and why the vehicle stops pointing at the ground station

`hs2sim/comms.py`, and the **Link margin** chart on
[the dashboard](DASHBOARD.md).

## What the link has to show

A demodulator needs a certain Eb/N0 to hit its bit-error rate: 11 dB for
coherent BPSK, about 14 dB for GFSK, which is ~3 dB worse because non-coherent
envelope detection has no matched filter to exploit. On top of that the run
demands a margin, and the margin is configured as a **linear power ratio**:

```yaml
required_margin_factor: 1.5     # the noise floor plus 50 %
```

50 % more *power*, which is 10·log₁₀(1.5) = **1.76 dB**. That is the reading
that makes sense of the requirement: it puts GFSK's 14 dB threshold at 15.8 dB,
which is the 14–15 dB the radio actually needs. Reading "50 %" as 50 % more
decibels would give 21 dB — a *harder* requirement than the flat 6 dB it
replaces, which is the opposite of relaxing it. There is a test asserting the
power-ratio reading.

The old flat 6 dB from the UNP budget is still in the file, unused, and is what
you get back by deleting the factor.

## Reading the margin chart

The curve hugs zero, and that is not a marginal link — it is the rate solver
working. The radio picks the fastest rate that closes, so spare margin is spent
on bitrate rather than banked, and a link with 17 dB in hand and one with 0.5 dB
both read about the same at the rate they end up flying.

The number that says how much is really in hand is the margin at the **slowest
commandable rate with the patch edge-on**, which the chart's note states:
**16.8 dB at 9.6 kbit/s**, worst case over the run. That is the figure the next
section rests on.

## Pointing the antenna is not worth two slews

Turning the vehicle to put the +x patch on the station is what justifies the
−3 dB nominal pointing loss instead of the −10 dB worst case where the patch is
edge-on. It also costs a magnetorquer manoeuvre at each end, and this vehicle
takes minutes over one.

So: does the link need it? Measured at 9.6 kbps, Eb/N0 against a 15.8 dB
requirement:

| elevation | slant range | pointed (−3 dB) | **edge-on (−10 dB)** |
|---|---|---|---|
| 10° | 1479 km | 36.6 dB | **29.6 dB** |
| 30° | 765 km | 42.3 dB | **35.3 dB** |
| 90° | 415 km | 47.6 dB | **40.6 dB** |

Even at the elevation mask, with the antenna in its worst orientation, the link
closes with **13.8 dB to spare**. The repoint is not buying a link. It buys
*rate* — 500 kbit/s pointed against 128 kbit/s edge-on at 1479 km — and the
mission generates about 1.7 MB a day against roughly 1000 MB a day of contact
capacity, so that rate has nothing to do.

`comms.downlink_needs_pointing` therefore answers the question from the budget
rather than from policy: a contact is flown antenna-on-station only where the
edge-on link does **not** close. With this radio that is nowhere, so the
scheduler flies every contact from whatever attitude it is already holding —
charging the worst-case pointing loss, which is what keeps it honest — and
spends no manoeuvres on comms at all. Starve the transmitter until the 7 dB
between the two cases straddles the threshold and the repoints come back, with
nothing else changed; there is a test for both directions.

This was the single largest source of wasted slewing. Before it, a contact cost
two multi-minute manoeuvres plus the lead-in, and the vehicle repointed for
passes whose useful fraction it then arrived too late for.

## What would change the answer

- **A faster fixed rate.** At 1 Mbps the edge-on link fails by 6 dB at 10°
  elevation, so pointing becomes the link and every contact needs it again.
- **A real backlog.** If imagery ever went down the link rather than staying on
  board, the 4× rate a repoint buys at low elevation would start to matter.
- **A worse antenna.** The −10 dB figure is the budget's tumbling worst case
  for two opposed patches; a single patch on one face would be worse than that
  for half the sky.
