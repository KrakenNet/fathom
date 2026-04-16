"""Fail if any symbol in fathom.__all__ has no corresponding generated page.

Reads the concatenated Markdown under docs/reference/python-sdk/ (or
$FATHOM_SDK_DOCS_DIR) and greps for each public symbol name.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import fathom

DEFAULT_DIR = Path("docs/reference/python-sdk")


def main() -> int:
    base = Path(os.environ.get("FATHOM_SDK_DOCS_DIR", str(DEFAULT_DIR)))
    if not base.exists():
        print(f"fail: docs dir does not exist: {base}")
        return 1

    corpus = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in base.rglob("*.md")
    )

    missing: list[str] = []
    for symbol in fathom.__all__:
        if symbol.startswith("_"):
            continue
        if symbol not in corpus:
            missing.append(symbol)

    if missing:
        print(f"fail: {len(missing)} public symbol(s) missing from generated docs:")
        for name in missing:
            print(f"  - {name}")
        return 1

    print(f"ok: all {len(fathom.__all__)} public symbols present in generated docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
