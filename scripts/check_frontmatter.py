"""Validate frontmatter on hand-written MkDocs pages.

Wave 0 scaffolding: the script works, tests pass, but it is NOT yet
invoked on the real `docs/` tree. Wave 2 enables it as pages are
rewritten with the new frontmatter schema.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REQUIRED = {"title", "summary", "audience", "diataxis", "status", "last_verified"}
VALID_DIATAXIS = {"tutorial", "how-to", "reference", "explanation", "landing"}
VALID_STATUS = {"stable", "draft", "experimental"}
VALID_AUDIENCES = {"app-developers", "rule-authors", "contributors"}
NARRATIVE_DIATAXIS = {"tutorial", "how-to", "explanation"}


def _read_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError("no frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("unterminated frontmatter")
    return yaml.safe_load(text[3:end]) or {}


def _validate(fm: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    missing = REQUIRED - fm.keys()
    if missing:
        errs.append(f"missing fields: {sorted(missing)}")
    if (d := fm.get("diataxis")) and d not in VALID_DIATAXIS:
        errs.append(f"diataxis must be one of {sorted(VALID_DIATAXIS)}, got {d!r}")
    if (s := fm.get("status")) and s not in VALID_STATUS:
        errs.append(f"status must be one of {sorted(VALID_STATUS)}, got {s!r}")
    aud = fm.get("audience")
    if isinstance(aud, list):
        bad = set(aud) - VALID_AUDIENCES
        if bad:
            errs.append(f"unknown audience values: {sorted(bad)}")
    d = fm.get("diataxis")
    needs_sources = d in NARRATIVE_DIATAXIS or (
        d == "reference" and not fm.get("generated")
    )
    if needs_sources:
        srcs = fm.get("sources")
        if not isinstance(srcs, list) or not srcs:
            errs.append("sources: required and must be a non-empty list")
    return errs


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv[1:]]
    if not paths:
        paths = [
            p for p in Path("docs").rglob("*.md")
            if "/reference/" not in p.as_posix()
            and "/superpowers/" not in p.as_posix()
        ]
    had_errors = False
    for path in paths:
        try:
            fm = _read_frontmatter(path)
        except ValueError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            had_errors = True
            continue
        errs = _validate(fm)
        for err in errs:
            print(f"{path}: {err}", file=sys.stderr)
            had_errors = True
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
