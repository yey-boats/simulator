from yey.boats.simulator import resources  # type: ignore[import]


def test_data_files_resolve_to_existing_paths():
    assert resources.polar_csv().is_file()  # noqa: S101
    assert resources.marinas_json().is_file()  # noqa: S101
    assert resources.route_kmz().is_file()  # noqa: S101


def test_depth_cache_path_is_in_data_dir(tmp_path):
    p = resources.depth_cache_path(tmp_path)
    assert p == tmp_path / "depth_profile.json"  # noqa: S101
