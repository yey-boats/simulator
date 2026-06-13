"""Command-line entry point for yey-boats-sim."""
from __future__ import annotations

import argparse
import asyncio

from yey.boats.simulator.config import Settings  # type: ignore[import]


def build_settings(argv: list[str] | None = None) -> Settings:
    p = argparse.ArgumentParser(prog="yey-boats-sim",
                                description="Adriatic sailing boat simulator.")
    p.add_argument("--sink", choices=["signalk", "stdout", "nmea0183", "nmea2000"],
                   default=None, help="primary output sink (default: env SINK or signalk)")
    p.add_argument("--signalk-host", default=None)
    p.add_argument("--signalk-port", type=int, default=None)
    p.add_argument("--signalk-username", default=None)
    p.add_argument("--signalk-password", default=None)
    p.add_argument("--data-dir", default=None, help="writable dir for the depth cache")
    p.add_argument("--no-failover", action="store_true", help="disable sink failover chain")
    args = p.parse_args(argv)
    overrides: dict[str, object] = {
        "sink": args.sink,
        "signalk_host": args.signalk_host,
        "signalk_port": args.signalk_port,
        "signalk_username": args.signalk_username,
        "signalk_password": args.signalk_password,
    }
    if args.data_dir is not None:
        from pathlib import Path
        overrides["data_dir"] = Path(args.data_dir).resolve()
    if args.no_failover:
        overrides["failover"] = False
    return Settings.from_env(**overrides)


def main(argv: list[str] | None = None) -> None:
    settings = build_settings(argv)
    from yey.boats.simulator.engine.runner import run  # type: ignore[import]
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
