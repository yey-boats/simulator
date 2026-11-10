# Releasing

Releases are cut by pushing a git tag `v<version>`. Pushing the tag runs
`.github/workflows/release.yml`. Nothing else publishes a version.

## What publishes what

| Trigger | Workflow | Publishes |
|---|---|---|
| push to `main` (green CI) | `ci.yml` `publish-image` | `ghcr.io/yey-boats/simulator:latest`, `:main`, `:sha-<short>` (image version label: `dev`) |
| push of tag `v<x.y.z>` | `release.yml` | `ghcr.io/yey-boats/simulator:<x.y.z>`, `:<x.y>`, `:v<x.y.z>` (multi-arch, labelled `org.opencontainers.image.version=<x.y.z>`, env `SIM_VERSION=<x.y.z>`); the wheel and sdist go to PyPI only when the repo variable `PUBLISH_PYPI=true` (environment `release`) |

A release does **not** move `:latest`. `:latest` follows `main`, and the demo
boat and the board pull it (navigator `SIM_IMAGE_TAG`, default `latest`). To run
a fixed release there, set `SIM_IMAGE_TAG=<x.y.z>`.

## The version

`pyproject.toml` `[project].version` is the source of truth. These copies must
match it, and `tests/test_version.py` checks them on every CI run:

- `src/yey/boats/simulator/__init__.py` `__version__`
- `signalk-plugin/package.json` `version` (navigator vendors the plugin, so the
  version tells you which copy it has)
- `CHANGELOG.md`: the top section is `## <version> — unreleased` while work
  is still being added to it

We use SemVer. While we are on `0.x`, a breaking change bumps the minor version.

## Cutting a release

1. On a branch, make sure the version in the files above is the one you are
   releasing. Rename the CHANGELOG heading `## <version> — unreleased` to
   `## <version> — YYYY-MM-DD`. Open a PR and merge it once CI is green.
2. Tag the merge commit on `main` and push the tag:

   ```sh
   git fetch origin && git tag -a v<version> origin/main -m "v<version>"
   git push origin v<version>
   ```

3. `release.yml` first runs `scripts/check_version.py v<version>`. It stops
   before publishing anything if the tag doesn't match the files or the
   CHANGELOG section is still `unreleased`. You can run the same check locally
   first with `python scripts/check_version.py v<version>`.
4. Start the next cycle: bump the version in all three places to the next
   planned version and add a new `## <next> — unreleased` section at the top of
   `CHANGELOG.md`.

Don't move or re-push a tag that was already published. If a release is bad,
fix it and release the next patch version.
