"""CI must run every test suite in the repo, not just the Python one (#13)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_ci_runs_signalk_plugin_tests() -> None:
    plugin_tests = sorted((ROOT / "signalk-plugin" / "test").glob("*.test.js"))
    assert plugin_tests, "signalk-plugin has no tests; drop this guard"
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "working-directory: signalk-plugin" in ci, (
        "ci.yml does not run the signalk-plugin node tests"
    )
