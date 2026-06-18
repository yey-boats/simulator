# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from yey.boats.simulator.engine.snapshot import AisContact, TelemetrySnapshot  # type: ignore[import]


def test_ais_contact_fields():
    c = AisContact(mmsi="247100111", lat=45.1, lon=13.2, cog_deg=90.0,
                   sog_kts=11.0, name="MV Adriatic Star", ship_type=70)
    assert c.mmsi == "247100111"  # noqa: S101
    assert c.ship_type == 70  # noqa: S101


def test_snapshot_ais_contacts_defaults_empty():
    from datetime import datetime, timezone
    snap = TelemetrySnapshot(
        nav=object(), elec=object(), sys=object(), lights=object(), wx=object(),
        state=object(), utc_now=datetime.now(timezone.utc), temps={},
        next_wp=None, route_href="", point_index=0)
    assert snap.ais_contacts == []  # noqa: S101
