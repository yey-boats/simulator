# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
from yey.boats.simulator import resources  # type: ignore[import]


def test_data_files_resolve_to_existing_paths():
    assert resources.polar_csv().is_file()  # noqa: S101
    assert resources.marinas_json().is_file()  # noqa: S101
    assert resources.route_kmz().is_file()  # noqa: S101
