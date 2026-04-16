"""Fail if any symbol in <pkg>.__all__ lacks a docstring."""
from __future__ import annotations

import importlib
import inspect
import sys


def main(argv: list[str]) -> int:
    pkg_name = argv[1] if len(argv) > 1 else "fathom"
    pkg = importlib.import_module(pkg_name)
    missing: list[str] = []
    for name in getattr(pkg, "__all__", []):
        obj = getattr(pkg, name)
        if inspect.ismodule(obj) or inspect.isclass(obj) or inspect.isfunction(obj):
            doc = (inspect.getdoc(obj) or "").strip()
            if not doc or "TODO" in doc or "FIXME" in doc:
                missing.append(f"{pkg_name}.{name}")
    if missing:
        print("missing/incomplete docstrings:", file=sys.stderr)
        for entry in missing:
            print(f"  {entry}", file=sys.stderr)
        return 1
    print(f"ok: all {len(getattr(pkg, '__all__', []))} public symbols documented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
