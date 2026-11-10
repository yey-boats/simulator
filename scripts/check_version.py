#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Release gate: the pushed tag must match the version stamped everywhere.

    python scripts/check_version.py v0.1.0 [--root DIR] [--changelog FILE]

Checks that the tag is ``v<version>`` where <version> is pyproject.toml's
[project].version, that src/yey/boats/simulator/__init__.py ``__version__`` and
signalk-plugin/package.json ``version`` are the same, and that CHANGELOG.md has
a dated ``## <version> — YYYY-MM-DD`` section (not "unreleased"). Run by
.github/workflows/release.yml before anything is published.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path


def problems(tag: str, root: Path, changelog: Path) -> list[str]:
    out: list[str] = []
    version = str(tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"])
    if tag != f"v{version}":
        out.append(f"tag {tag!r} does not match pyproject.toml version {version!r} "
                   f"(expected tag 'v{version}')")
    init = (root / "src/yey/boats/simulator/__init__.py").read_text()
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', init, flags=re.M)
    if not m or m.group(1) != version:
        out.append(f"__init__.__version__ {m.group(1) if m else None!r} != {version!r}")
    plugin = json.loads((root / "signalk-plugin/package.json").read_text())["version"]
    if plugin != version:
        out.append(f"signalk-plugin/package.json version {plugin!r} != {version!r}")
    heading = re.compile(rf"^## {re.escape(version)} — \d{{4}}-\d{{2}}-\d{{2}}\s*$", flags=re.M)
    if not heading.search(changelog.read_text()):
        out.append(f"CHANGELOG has no dated '## {version} — YYYY-MM-DD' section "
                   "(rename the '— unreleased' heading to the release date)")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tag", help="the git tag being released, e.g. v0.1.0")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--changelog", type=Path, default=None)
    args = ap.parse_args(argv)
    found = problems(args.tag, args.root, args.changelog or args.root / "CHANGELOG.md")
    for p in found:
        print(f"::error::{p}")
    if not found:
        print(f"{args.tag}: versions agree")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
