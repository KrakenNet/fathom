"""Fail if the versions that ship together have drifted apart.

Sources, all of which release-please writes on a release:

- ``pyproject.toml`` ``[project].version`` — the authority
- ``src/fathom/__init__.py`` ``__version__``
- ``packages/fathom-ts/package.json`` ``version`` — the TS SDK versions in
  lockstep with the engine, because it is the client for the engine's API and
  ``npm-publish.yml`` fires on the same ``v*.*.*`` tag. It sat at 0.1.0 across
  every release before that was wired up, so each tag would have republished
  the same version.

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


def main() -> int:
    root = Path.cwd()
    expected = read_pyproject_version(root)

    others = {
        "src/fathom/__init__.py": read_init_version(root),
        "packages/fathom-ts/package.json": read_ts_sdk_version(root),
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
