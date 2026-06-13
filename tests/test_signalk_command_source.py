from yey.boats.simulator.sources.signalk_command import SignalKCommandSource  # type: ignore[import]


class FakeAutopilot:
    def __init__(self) -> None:
        self.applied: list = []

    def apply(self, action: str, arg: object,
              current_heading_deg: float | None = None,
              twd_deg: float | None = None) -> None:
        self.applied.append((action, arg))


def test_command_source_routes_delta_to_autopilot() -> None:
    ap = FakeAutopilot()
    src = SignalKCommandSource(
        host="h", port=3000, token="t",  # noqa: S106
        autopilot=ap, wind_fn=lambda: (90.0, 130.0),
    )
    src.handler.on_delta({"updates": [{"$source": "other", "values": [
        {"path": "steering.autopilot.command",
         "value": {"action": "engage", "value": None}}]}]})
    assert ap.applied == [("engage", None)]  # noqa: S101
