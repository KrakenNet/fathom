"""Fail if pyproject.toml version != fathom.__init__.__version__."""
from __future__ import annotations

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


def main() -> int:
    root = Path.cwd()
    pyproject = read_pyproject_version(root)
    init = read_init_version(root)
    if pyproject != init:
        print(
            f"version skew: pyproject.toml={pyproject} "
            f"src/fathom/__init__.py={init}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
