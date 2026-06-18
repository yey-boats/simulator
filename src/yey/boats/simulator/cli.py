"""Command-line entry point for yey-boats-sim."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from yey.boats.simulator.config import Settings  # type: ignore[import]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="yey-boats-sim",
                                description="Adriatic sailing boat simulator.")
    p.add_argument("--sink", choices=["signalk", "stdout", "nmea0183", "nmea2000"],
                   default=None, help="primary output sink (default: env SINK or signalk)")
    p.add_argument("--signalk-host", default=None)
    p.add_argument("--signalk-port", type=int, default=None)
    p.add_argument("--signalk-username", default=None)
    p.add_argument("--signalk-password", default=None)
    p.add_argument("--weather-source", choices=["openmeteo", "signalk"], default=None,
                   help="where weather comes from (default: env WEATHER_SOURCE or openmeteo)")
    p.add_argument("--data-dir", default=None, help="writable dir for the depth cache")
    p.add_argument("--no-failover", action="store_true", help="disable sink failover chain")
    # web admin flags
    p.add_argument("--web-host", default=None)
    p.add_argument("--web-port", type=int, default=None)
    p.add_argument("--web-token", default=None)
    p.add_argument("--no-web", action="store_true", help="disable the web admin UI")
    return p


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


def build_settings(argv: list[str] | None = None) -> Settings:
    args = parse_args(argv)
    overrides: dict[str, object] = {
        "sink": args.sink,
        "signalk_host": args.signalk_host,
        "signalk_port": args.signalk_port,
        "signalk_username": args.signalk_username,
        "signalk_password": args.signalk_password,
        "weather_source": args.weather_source,
    }
    if args.data_dir is not None:
        overrides["data_dir"] = Path(args.data_dir).resolve()
    if args.no_failover:
        overrides["failover"] = False
    # determine data_dir for config.json lookup (prefer explicit arg over env default)
    data_dir = Path(args.data_dir).resolve() if args.data_dir else Settings().data_dir
    config_path = data_dir / "config.json"
    return Settings.from_env(config_path=config_path, **overrides)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = build_settings(argv)
    from yey.boats.simulator.engine.runner import run_with_web  # type: ignore[import]
    asyncio.run(run_with_web(settings, args))


if __name__ == "__main__":
    main()
