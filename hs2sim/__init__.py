"""HS-2 CubeSat operations simulation.

A Basilisk-backed model of a 3U CubeSat in an ISS orbit, built to answer six
operational questions: surface illumination for thermal, solar array output for
three candidate geometries, how many payload images are sustainable, ground
station contact statistics, magnetorquer limits on operations, and the CONOPS
that ties them together.
"""

__version__ = "0.1.0"

__all__ = [
    "adcs",
    "comms",
    "config",
    "conops",
    "environment",
    "geometry",
    "power",
    "thermal",
]
