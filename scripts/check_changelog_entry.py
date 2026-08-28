"""Fail a PR that releases something but adds nothing to the changelog.

``release-please`` derives a release from ``feat:`` and ``fix:`` commits, and
``promote_changelog.py`` turns whatever sits under ``## [Unreleased]`` into that
release's entry. Nothing connected the two: a branch could add ten ``fix:``
commits and no changelog line, and the omission only showed up on the release
PR -- as a version-skew failure naming the wrong file, days later, on a PR
nobody wrote.

This runs on the PR that introduces the change, while the author still has the
context to describe it. A PR with no ``feat:``/``fix:`` commits is not releasable
and is skipped.

Both merge styles are covered: squash-merge lands the PR title as the commit
subject, merge-commit lands each subject as written, so both are checked.

Usage::

    python scripts/check_changelog_entry.py <base-ref> [pr-title]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

#: Conventional-commit types release-please turns into a release entry.
RELEASABLE = re.compile(r"^(?:feat|fix)(?:\([^)]*\))?!?:", re.I)

UNRELEASED_SECTION = re.compile(
    r"^##\s*\[Unreleased\]\s*$(.*?)(?=^##\s|\Z)",
    re.M | re.I | re.S,
)


def unreleased_body(text: str) -> str:
    """The prose under ``## [Unreleased]``, or "" if the heading is absent."""
    match = UNRELEASED_SECTION.search(text)
    return match.group(1).strip() if match else ""


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def main(argv: list[str]) -> int:
    base = argv[1] if len(argv) > 1 else "origin/main"
    subjects = git("log", "--format=%s", f"{base}..HEAD").splitlines()
    if len(argv) > 2 and argv[2]:
        subjects.append(argv[2])

    releasable = [s for s in subjects if RELEASABLE.match(s)]
    if not releasable:
        print("no feat:/fix: commits; changelog entry not required.")
        return 0

    head = unreleased_body(Path("CHANGELOG.md").read_text(encoding="utf-8"))
    try:
        before = unreleased_body(git("show", f"{base}:CHANGELOG.md"))
    except subprocess.CalledProcessError:
        before = ""

    if head and head != before:
        print(f"changelog entry present for {len(releasable)} releasable commit(s).")
        return 0

    print(
        "error: this branch has releasable commits but adds nothing under "
        "'## [Unreleased]' in CHANGELOG.md:\n  "
        + "\n  ".join(releasable)
        + "\n\nAdd a bullet describing the change. It becomes the entry for the "
        "next release: promote_changelog.py renames that heading to the version "
        "when release-please opens the release PR.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
