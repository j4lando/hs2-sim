"""Configuration loading for the HS-2 operations simulation.

All mission inputs live in the YAML files under ``config/``. Nothing in the
analysis code hard-codes a spacecraft number: if a value matters, it is in the
YAML and can be swept.
"""

from __future__ import annotations

import copy
import pathlib
from typing import Any, Iterator

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
RESULTS_DIR = REPO_ROOT / "results"


class AttrDict(dict):
    """Dict that also supports attribute access, recursively.

    Keeps the YAML readable as plain nested dicts while letting analysis code
    write ``cfg.orbit.altitude_km`` instead of ``cfg["orbit"]["altitude_km"]``.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - programming error
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def _wrap(obj: Any) -> Any:
    if isinstance(obj, dict):
        return AttrDict({k: _wrap(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_wrap(v) for v in obj]
    return obj


def load_yaml(path: pathlib.Path) -> AttrDict:
    with open(path, "r", encoding="utf-8") as handle:
        return _wrap(yaml.safe_load(handle))


class MissionConfig:
    """Bundle of every configuration file, loaded once and passed around."""

    def __init__(self, config_dir: pathlib.Path | None = None):
        config_dir = pathlib.Path(config_dir or CONFIG_DIR)
        self.config_dir = config_dir
        self.mission = load_yaml(config_dir / "mission.yaml")
        self.spacecraft = load_yaml(config_dir / "spacecraft.yaml")
        self.ground = load_yaml(config_dir / "ground_stations.yaml")
        # Detumble/sun-acquisition inputs. Optional: the CONOPS analysis never
        # touches them, so an installation without the file still runs.
        detumble_path = config_dir / "detumble.yaml"
        self.detumble = (load_yaml(detumble_path) if detumble_path.exists()
                         else None)

    # -- convenient shortcuts -------------------------------------------------
    @property
    def orbit(self) -> AttrDict:
        return self.mission.orbit

    @property
    def sim(self) -> AttrDict:
        return self.mission.simulation

    @property
    def env(self) -> AttrDict:
        return self.mission.environment

    @property
    def power(self) -> AttrDict:
        return self.spacecraft.power

    @property
    def payload(self) -> AttrDict:
        return self.spacecraft.payload

    @property
    def radio(self) -> AttrDict:
        return self.ground.radio

    def array_options(self) -> Iterator[tuple[str, AttrDict]]:
        """Yield (option_name, option_config) for each solar array geometry."""
        for name, option in self.spacecraft.solar_array_options.items():
            yield name, option

    def sensor_geometries(self) -> Iterator[tuple[str, AttrDict]]:
        """Yield (name, geometry) for each sun sensor layout under trade."""
        if self.detumble is None:
            return
        for name, geometry in self.detumble.sensor_geometries.items():
            yield name, geometry

    def stations(self) -> list[AttrDict]:
        """Ground stations with defaults filled in."""
        defaults = self.ground.defaults
        out = []
        for station in self.ground.stations:
            merged = AttrDict(copy.deepcopy(dict(defaults)))
            merged.update(station)
            out.append(merged)
        return out

    def copy_with(self, **overrides: Any) -> "MissionConfig":
        """Shallow clone with dotted-path overrides, e.g. ``orbit.raan_deg=90``.

        Used by the RAAN / payload-rate sweeps so a single run function can be
        reused without mutating shared state.
        """
        clone = copy.deepcopy(self)
        for dotted, value in overrides.items():
            target: Any = clone
            parts = dotted.split(".")
            for part in parts[:-1]:
                target = getattr(target, part) if hasattr(target, part) else target[part]
            target[parts[-1]] = value
        return clone
