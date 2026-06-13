"""Build the configured sink (and failover chain) from Settings."""
from __future__ import annotations

from yey.boats.simulator.adapters.failover import SinkChain  # type: ignore[import]
from yey.boats.simulator.config import Settings  # type: ignore[import]
from yey.boats.simulator.sinks.nmea0183 import NMEA0183Sink  # type: ignore[import]
from yey.boats.simulator.sinks.nmea2000 import NMEA2000Sink  # type: ignore[import]
from yey.boats.simulator.sinks.signalk import SignalKSink  # type: ignore[import]
from yey.boats.simulator.sinks.stdout_json import StdoutJsonSink  # type: ignore[import]


def _make(kind: str, settings: Settings):  # type: ignore[return]
    if kind == "signalk":
        return SignalKSink(
            settings.signalk_host,
            settings.signalk_port,
            settings.signalk_username,
            settings.signalk_password,
        )
    if kind == "stdout":
        return StdoutJsonSink()
    if kind == "nmea0183":
        return NMEA0183Sink()
    if kind == "nmea2000":
        return NMEA2000Sink()
    raise ValueError(f"unknown sink kind: {kind!r}")


def build_sink_chain(settings: Settings) -> SinkChain:
    primary = _make(settings.sink, settings)
    if not settings.failover:
        return SinkChain([primary])
    chain = [primary]
    # Failover: SignalK@localhost, then stdout (skip duplicates of primary).
    if settings.sink != "signalk":
        chain.append(
            SignalKSink(
                "localhost",
                3000,
                settings.signalk_username,
                settings.signalk_password,
            )
        )
    elif settings.signalk_host != "localhost":
        chain.append(
            SignalKSink(
                "localhost",
                settings.signalk_port,
                settings.signalk_username,
                settings.signalk_password,
            )
        )
    if settings.sink != "stdout":
        chain.append(StdoutJsonSink())
    return SinkChain(chain)
