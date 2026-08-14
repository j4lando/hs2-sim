"""Shared colours for the figures.

The values are a validated categorical palette: the hue ordering is the
colour-vision-deficiency safety mechanism, not decoration, so slots are
assigned in order and never cycled. The older per-figure colours in
``overview.py`` predate this module and are left alone -- they are single
figures with their own fixed legends, not a shared encoding.
"""

from __future__ import annotations

# Background wash per flown mode. Blue, orange and aqua are the first three
# slots of the categorical palette -- the three that stay separable under
# colour-vision deficiency when every pair can appear together, which is the
# case here because the scheduler can put any two modes side by side. SLEW is
# deliberately neutral: it is a transition between identities rather than one
# of its own, and it abuts every other mode, so giving it a hue would put two
# saturated washes against each other at every mode change. SAFE takes the
# status-critical red.
MODE_WASH = {
    "safe": "#d03b3b",
    "standby": "#1baf7a",
    "slew": "#898781",
    "experiment": "#2a78d6",
    "downlink": "#eb6834",
}
MODE_WASH_ALPHA = 0.22

# The washes stop short of the top of the axes; the strip above them carries
# eclipse, which is a separate channel and must not be confused with a mode.
WASH_TOP = 0.94
SUNLIT_TRACK = "#e1e0d9"

INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
BASELINE = "#c3c2b7"
LIMIT_LINE = "#d03b3b"          # status-critical: a line you must not cross
