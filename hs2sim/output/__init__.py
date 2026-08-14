"""Presentation layer: figures and Vizard export/validation.

Everything here consumes results already computed by the physics modules in
``hs2sim`` (config, environment, adcs, comms, conops, ...) and adds no
analysis of its own -- it only renders or exports them.
"""

__all__ = ["plots", "vizard", "vizcheck"]
