# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""One version, stamped everywhere (#15).

pyproject.toml is the source of truth. The package's __version__, the
signalk-plugin package.json and the CHANGELOG must agree with it, and the
tag-triggered release refuses a tag that does not match.
"""
import json
import re
import tomllib
from pathlib import Path

import pytest  # type: ignore[import]

from yey.boats.simulator import __version__  # type: ignore[import]
from yey.boats.simulator.cli import main  # type: ignore[import]

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def _pyproject_version() -> str:
    return str(tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"])


def test_pyproject_version_is_semver() -> None:
    assert SEMVER.match(_pyproject_version())


def test_package_version_matches_pyproject() -> None:
    assert __version__ == _pyproject_version()


def test_signalk_plugin_version_matches_pyproject() -> None:
    pkg = json.loads((ROOT / "signalk-plugin" / "package.json").read_text())
    assert pkg["version"] == _pyproject_version()


def test_changelog_top_section_is_the_current_version_or_unreleased() -> None:
    # Between releases the top section is "## <version> — unreleased" (the next
    # version, already set in pyproject) or "## Unreleased"; at release time it
    # becomes "## <version> — YYYY-MM-DD" (checked by scripts/check_version.py).
    text = (ROOT / "CHANGELOG.md").read_text()
    headings = [h.strip() for h in re.findall(r"^## (.+)$", text, flags=re.M)]
    assert headings, "CHANGELOG has no version sections"
    version = _pyproject_version()
    assert headings[0].startswith(version) or headings[0].lower() == "unreleased", headings[0]
    assert any(h.startswith(version) for h in headings), (
        f"CHANGELOG has no '## {version}' section")


def test_check_version_requires_a_dated_changelog_section(tmp_path: Path) -> None:
    import subprocess
    import sys
    v = _pyproject_version()
    (tmp_path / "CHANGELOG.md").write_text(f"# Changelog\n\n## {v} — unreleased\n- x\n")
    script = ROOT / "scripts" / "check_version.py"
    res = subprocess.run([sys.executable, str(script), f"v{v}", "--root", str(ROOT),
                          "--changelog", str(tmp_path / "CHANGELOG.md")],
                         capture_output=True, text=True)
    assert res.returncode != 0
    assert "CHANGELOG" in res.stdout + res.stderr
    (tmp_path / "CHANGELOG.md").write_text(f"# Changelog\n\n## {v} — 2026-11-10\n- x\n")
    res = subprocess.run([sys.executable, str(script), f"v{v}", "--root", str(ROOT),
                          "--changelog", str(tmp_path / "CHANGELOG.md")],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


def test_cli_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"yey-boats-sim {__version__}"


def test_release_workflow_runs_on_v_tags_and_checks_the_version() -> None:
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert re.search(r'tags:\s*\[\s*"v\*"\s*\]', wf)
    # A version-check job gates both publish jobs.
    assert "scripts/check_version.py" in wf
    assert wf.count("needs: version") == 2
    # The image carries the version as a tag and an OCI label, and a release
    # does not move :latest (ci.yml owns :latest = main).
    assert "type=semver,pattern={{version}}" in wf
    assert "labels: ${{ steps.meta.outputs.labels }}" in wf
    assert "VERSION=" in wf
    assert "value=latest" not in wf
    assert ":latest" not in wf


def test_dockerfile_stamps_the_version() -> None:
    df = (ROOT / "Dockerfile").read_text()
    assert "ARG VERSION" in df
    assert "org.opencontainers.image.version" in df


def test_check_version_rejects_a_tag_that_does_not_match() -> None:
    import subprocess
    import sys
    script = ROOT / "scripts" / "check_version.py"
    bad = subprocess.run([sys.executable, str(script), "v9.9.9", "--root", str(ROOT)],
                         capture_output=True, text=True)
    assert bad.returncode != 0
    assert "9.9.9" in bad.stdout + bad.stderr
    # Without the "v" prefix it is not a release tag at all.
    v = _pyproject_version()
    nov = subprocess.run([sys.executable, str(script), v, "--root", str(ROOT)],
                         capture_output=True, text=True)
    assert nov.returncode != 0
