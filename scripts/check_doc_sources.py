"""Drift gate: fail if any page's cited sources were modified after
the page's last_verified date, or if a cited source file is missing.

Two scopes. With no arguments every page is checked -- the maintainer sweep,
which answers "what has gone stale anywhere". With ``--changed-vs REF`` only
the sources this branch touched are considered, which is the scope a merge
gate needs: editing a source ages every page citing it, so a whole-repo gate
would fail the next unrelated pull request instead of the one that caused
the drift.

Honors `.git-blame-ignore-revs` (the standard git convention used by
`git blame` and `git config blame.ignoreRevsFile`) so that format-only
or otherwise non-content commits don't trip the gate. Add a SHA to
that file to declare a commit irrelevant for source-doc drift.

Mechanical commits are also ignored automatically: commits authored
by Dependabot or whose subject is a conventional `build(deps)` /
`chore(deps)` bump, and release-please's own `chore(main): release`
and `chore(release):` commits, don't count as content changes. Both
rewrite cited files -- a manifest, a workflow, the version lines in
pyproject.toml / __init__.py / README.md / docs/index.md -- without
changing any documented behavior, and without this the gate aged
every page citing them on every release. The most recent *meaningful*
commit to a cited source is what's compared against last_verified.

Exit codes: 0 clean; 1 drift or missing source; 2 misconfig.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

# Conventional-commit subjects for mechanical commits, e.g.
# "build(deps): bump actions/checkout from 6 to 7",
# "chore(deps-dev): bump typescript",
# "chore(main): release 0.11.0" (release-please's own version bump) and
# "chore(release): regenerate docs artifacts". These touch cited manifest,
# workflow and version files without changing the documented behavior.
_MECHANICAL_SUBJECT = re.compile(
    r"^(?:(?:build|chore)\(deps(?:-dev)?\)|chore\((?:main|release)\): *(?:release|regenerate))",
    re.IGNORECASE,
)


def _is_mechanical(author: str, subject: str) -> bool:
    """True if a commit is a bot bump or a release chore, not a content change."""
    return "dependabot[bot]" in author or bool(_MECHANICAL_SUBJECT.match(subject))


def _read_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError(f"{path}: unterminated frontmatter")
    return yaml.safe_load(text[3:end]) or {}


def _read_ignore_revs(repo: Path) -> set[str]:
    """Return the set of commit SHAs from `.git-blame-ignore-revs`.

    Same format `git blame` honors: one SHA per line, `#` comments and
    blank lines are skipped, only the first whitespace-separated token
    on each line is treated as a SHA.
    """
    f = repo / ".git-blame-ignore-revs"
    if not f.exists():
        return set()
    revs: set[str] = set()
    for raw in f.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        revs.add(line.split()[0])
    return revs


def _last_commit_date(
    source: Path, repo: Path, ignore: set[str]
) -> tuple[date | None, bool]:
    """Return (date of last meaningful commit, was-the-source-tracked).

    Commits listed in `.git-blame-ignore-revs` and mechanical dependency
    bumps (see `_is_mechanical`) are skipped. The date is None when the
    source has no commits at all (untracked) or when every commit was
    skipped; `tracked` disambiguates the two for the caller.
    """
    sep = "\x1f"
    result = subprocess.run(
        ["git", "log", f"--format=%H{sep}%cI{sep}%an{sep}%s",
         "--", str(source.relative_to(repo))],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None, False
    saw_commit = False
    for raw in result.stdout.splitlines():
        parts = raw.split(sep)
        if len(parts) != 4:
            continue
        sha, iso, author, subject = parts
        if not sha:
            continue
        saw_commit = True
        if sha in ignore or _is_mechanical(author, subject):
            continue
        if not iso.strip():
            return None, True
        return datetime.fromisoformat(iso.strip()).date(), True
    return None, saw_commit


def _check_page(
    page: Path,
    repo: Path,
    ignore: set[str],
    scope: set[str] | None = None,
) -> list[str]:
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
        if scope is not None and src not in scope:
            continue
        src_path = repo / src
        if not src_path.exists():
            errors.append(f"{page}: cited source {src!r} does not exist")
            continue
        last, tracked = _last_commit_date(src_path, repo, ignore)
        if last is None:
            if not tracked:
                errors.append(f"{page}: {src!r} is not tracked by git")
            # else: every commit was a skipped/mechanical change — no
            # meaningful modification to compare against last_verified.
            continue
        if last > verified:
            errors.append(
                f"{page}: {src} last modified {last}, "
                f"verified {verified} — re-verify and bump last_verified"
            )
    return errors


def _changed_files(repo: Path, base: str) -> set[str] | None:
    """Repo-relative paths that differ between *base* and the working tree.

    Returns None if the diff cannot be taken (unknown ref, shallow clone),
    which the caller treats as "check everything" rather than "check nothing":
    a gate that silently passes on a bad ref is worse than a noisy one.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument(
        "--changed-vs",
        metavar="REF",
        help=(
            "only report pages whose cited sources this branch actually changed "
            "since REF. Without it every page is checked, which is the right "
            "shape for a maintainer sweep but the wrong one for a merge gate: "
            "a source edit ages every page citing it, and the failure would "
            "land on whoever opens the next unrelated pull request."
        ),
    )
    args = parser.parse_args(argv[1:])

    repo = Path(args.repo).resolve()
    docs = repo / "docs"
    if not docs.is_dir():
        print(f"error: {docs} not a directory", file=sys.stderr)
        return 2

    scope: set[str] | None = None
    if args.changed_vs:
        scope = _changed_files(repo, args.changed_vs)
        if scope is None:
            print(
                f"warning: cannot diff against {args.changed_vs!r}; checking every page",
                file=sys.stderr,
            )

    ignore = _read_ignore_revs(repo)
    had_errors = False
    for page in sorted(docs.rglob("*.md")):
        if "/superpowers/" in page.as_posix():
            continue
        errors = _check_page(page, repo, ignore, scope)
        for e in errors:
            print(e, file=sys.stderr)
        if errors:
            had_errors = True
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
