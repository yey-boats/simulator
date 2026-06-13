"""Resolve bundled package data and the runtime-writable data directory.

Bundled data (polars, marinas, route) ships inside the wheel and is read via
importlib.resources. The GEBCO depth cache is generated at runtime and lives in
a writable DATA_DIR, never inside the installed package.
"""
from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path


def _bundled(name: str) -> Path:
    # Use the parent package + "data" sub-path so it works whether or not
    # the data/ directory has an __init__.py (importlib.resources >= 3.9).
    res = files("yey.boats.simulator").joinpath("data", name)
    with as_file(res) as p:
        return Path(p)


def polar_csv() -> Path:
    return _bundled("beneteau_o45.csv")


def marinas_json() -> Path:
    return _bundled("marinas.json")


def route_kmz() -> Path:
    return _bundled("adriatic.kmz")


def depth_cache_path(data_dir: Path) -> Path:
    """Path to the runtime depth-profile cache inside the writable data dir."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "depth_profile.json"
