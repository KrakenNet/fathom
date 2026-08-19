"""Fail if the versions that ship together have drifted apart.

Sources, all of which release-please writes on a release:

- ``pyproject.toml`` ``[project].version`` — the authority
- ``src/fathom/__init__.py`` ``__version__``
- ``packages/fathom-ts/package.json`` ``version`` — the TS SDK versions in
  lockstep with the engine, because it is the client for the engine's API and
  ``npm-publish.yml`` fires on the same ``v*.*.*`` tag. It sat at 0.1.0 across
  every release before that was wired up, so each tag would have republished
  the same version.
- ``CHANGELOG.md`` — the newest version heading. release-please runs with
  ``skip-changelog``, so nothing writes this file automatically and it had
  stopped at 0.3.0 while 0.7.4 was on PyPI. Requiring a heading for the
  version being released turns that silent gap into a red release PR.
- ``README.md`` and ``docs/index.md`` — prose, but the first version number a
  reader sees on GitHub and on the docs site. Both carried 0.7.0 while 0.7.4
  was on PyPI. release-please rewrites them through the
  ``x-release-please-version`` markers on those lines; this check is what
  notices if a marker is dropped or a line is reworded out from under it.

A source that is absent is skipped rather than fatal: the script is run
against synthetic trees in the tests, and a missing file is not version skew.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


def read_pyproject_version(root: Path) -> str:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def read_init_version(root: Path) -> str:
    text = (root / "src" / "fathom" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if match is None:
        raise SystemExit("__version__ not found in src/fathom/__init__.py")
    return match.group(1)


def read_ts_sdk_version(root: Path) -> str | None:
    path = root / "packages" / "fathom-ts" / "package.json"
    if not path.exists():
        return None
    version = json.loads(path.read_text(encoding="utf-8")).get("version")
    if not isinstance(version, str):
        raise SystemExit("version not found in packages/fathom-ts/package.json")
    return version


#: The newest release heading in CHANGELOG.md, e.g. ``## [0.8.0] - 2026-08-19``.
CHANGELOG_HEADING = re.compile(r"^##\s*\[(?!Unreleased)([^\]]+)\]", re.M | re.I)


def read_changelog_version(root: Path) -> str | None:
    path = root / "CHANGELOG.md"
    if not path.exists():
        return None
    match = CHANGELOG_HEADING.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit("no release heading found in CHANGELOG.md")
    return match.group(1)


#: The version line each prose file publishes. Group 1 is the version.
PROSE_SOURCES: dict[str, re.Pattern[str]] = {
    "README.md": re.compile(r"^\*\*Current version:\*\*\s*(\S+)", re.M),
    "docs/index.md": re.compile(r"^Current release: `fathom-rules`\s*(\S+)", re.M),
}


def read_prose_version(root: Path, name: str) -> str | None:
    path = root / name
    if not path.exists():
        return None
    match = PROSE_SOURCES[name].search(path.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"no version line matching {PROSE_SOURCES[name].pattern!r} in {name}")
    return match.group(1)


def main() -> int:
    root = Path.cwd()
    expected = read_pyproject_version(root)

    others = {
        "src/fathom/__init__.py": read_init_version(root),
        "packages/fathom-ts/package.json": read_ts_sdk_version(root),
        "CHANGELOG.md": read_changelog_version(root),
        **{name: read_prose_version(root, name) for name in PROSE_SOURCES},
    }
    skewed = {
        name: found for name, found in others.items() if found is not None and found != expected
    }
    if skewed:
        detail = " ".join(f"{name}={found}" for name, found in sorted(skewed.items()))
        print(f"version skew: pyproject.toml={expected} {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
