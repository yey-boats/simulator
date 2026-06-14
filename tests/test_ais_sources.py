from yey.boats.simulator.engine.snapshot import AisContact  # type: ignore[import]
from yey.boats.simulator.sources.ais import SyntheticAISSource, AISStreamSource  # type: ignore[import]


def test_synthetic_get_contacts_returns_contacts():
    src = SyntheticAISSource(get_pos=lambda: (45.0, 13.0))
    src.seed(45.0, 13.0)
    contacts = src.get_contacts(45.0, 13.0)
    assert len(contacts) >= 1  # noqa: S101
    assert all(isinstance(c, AisContact) for c in contacts)  # noqa: S101
    assert all(c.mmsi for c in contacts)  # noqa: S101


def test_synthetic_advance_moves_vessels():
    src = SyntheticAISSource(get_pos=lambda: (45.0, 13.0))
    src.seed(45.0, 13.0)
    before = src.get_contacts(45.0, 13.0)[0]
    for _ in range(50):
        src.advance(45.0, 13.0)
    after = src.get_contacts(45.0, 13.0)[0]
    assert (before.lat, before.lon) != (after.lat, after.lon)  # noqa: S101


def test_aisstream_get_contacts_filters_range():
    src = AISStreamSource(get_pos=lambda: (45.0, 13.0))
    src._contacts = {
        "111": AisContact("111", 45.05, 13.05, 90.0, 10.0, "Near", 70),
        "222": AisContact("222", 48.0, 16.0, 90.0, 10.0, "Far", 70),
    }
    out = src.get_contacts(45.0, 13.0)
    mmsis = {c.mmsi for c in out}
    assert "111" in mmsis  # noqa: S101
    assert "222" not in mmsis  # noqa: S101
