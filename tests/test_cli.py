from yey.boats.simulator.cli import build_settings  # type: ignore[import]


def test_cli_args_override_env(monkeypatch):
    monkeypatch.setenv("SINK", "signalk")
    s = build_settings(["--sink", "stdout", "--signalk-host", "h", "--no-failover"])
    assert s.sink == "stdout"  # noqa: S101
    assert s.signalk_host == "h"  # noqa: S101
    assert s.failover is False  # noqa: S101


def test_cli_defaults_to_env(monkeypatch):
    monkeypatch.setenv("SINK", "stdout")
    monkeypatch.setenv("SIGNALK_PORT", "3005")
    s = build_settings([])
    assert s.sink == "stdout"  # noqa: S101
    assert s.signalk_port == 3005  # noqa: S101
