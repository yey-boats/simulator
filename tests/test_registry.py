# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Unit tests for build_sink_chain branching logic."""
from yey.boats.simulator.config import Settings  # type: ignore[import]
from yey.boats.simulator.sinks.registry import build_sink_chain  # type: ignore[import]


def _names(chain):
    return [s.name for s in chain._sinks]


def test_signalk_remote_has_localhost_then_stdout_fallback():
    s = Settings(sink="signalk", signalk_host="signalk-server", failover=True)
    chain = build_sink_chain(s)
    assert _names(chain) == ["signalk", "signalk", "stdout"]  # noqa: S101


def test_signalk_localhost_has_no_duplicate_localhost():
    s = Settings(sink="signalk", signalk_host="localhost", failover=True)
    chain = build_sink_chain(s)
    assert _names(chain) == ["signalk", "stdout"]  # noqa: S101


def test_stdout_primary_has_signalk_fallback_no_duplicate_stdout():
    s = Settings(sink="stdout", failover=True)
    chain = build_sink_chain(s)
    assert _names(chain) == ["stdout", "signalk"]  # noqa: S101


def test_failover_disabled_yields_single_sink():
    s = Settings(sink="stdout", failover=False)
    chain = build_sink_chain(s)
    assert _names(chain) == ["stdout"]  # noqa: S101
