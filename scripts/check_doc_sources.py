"""Drift gate: fail if any page's cited sources were modified after
the page's last_verified date, or if a cited source file is missing.

Exit codes: 0 clean; 1 drift or missing source; 2 misconfig.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


def _read_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError(f"{path}: unterminated frontmatter")
    return yaml.safe_load(text[3:end]) or {}


def _last_commit_date(source: Path, repo: Path) -> date | None:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", str(source.relative_to(repo))],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return datetime.fromisoformat(result.stdout.strip()).date()


def _check_page(page: Path, repo: Path) -> list[str]:
    try:
        fm = _read_frontmatter(page)
    except ValueError as exc:
        return [f"{page}: {exc}"]
    sources = fm.get("sources")
    if not sources:
        return []
    verified = fm.get("last_verified")
    if isinstance(verified, str):
        verified = date.fromisoformat(verified)
    if not isinstance(verified, date):
        return [f"{page}: last_verified missing or not a date"]
    errors: list[str] = []
    for src in sources:
        src_path = repo / src
        if not src_path.exists():
            errors.append(f"{page}: cited source {src!r} does not exist")
            continue
        last = _last_commit_date(src_path, repo)
        if last is None:
            errors.append(f"{page}: {src!r} is not tracked by git")
            continue
        if last > verified:
            errors.append(
                f"{page}: {src} last modified {last}, "
                f"verified {verified} — re-verify and bump last_verified"
            )
    return errors


def main(argv: list[str]) -> int:
    repo = Path(argv[1] if len(argv) > 1 else ".").resolve()
    docs = repo / "docs"
    if not docs.is_dir():
        print(f"error: {docs} not a directory", file=sys.stderr)
        return 2
    had_errors = False
    for page in sorted(docs.rglob("*.md")):
        if "/superpowers/" in page.as_posix():
            continue
        errors = _check_page(page, repo)
        for e in errors:
            print(e, file=sys.stderr)
        if errors:
            had_errors = True
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
