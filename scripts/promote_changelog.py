"""Rename CHANGELOG.md's ``## [Unreleased]`` heading to the version being released.

release-please runs with ``skip-changelog``, so it bumps ``pyproject.toml`` but
never touches ``CHANGELOG.md``. ``check_version_sync.py`` requires the newest
release heading to match ``pyproject.toml``, so **every** release PR opened red
and the entry was hand-written afterwards -- 0.9.0 and 0.11.0 both shipped that
way, with the gate still failing at merge.

``release-please-docs.yml`` runs this on the release branch before it regenerates
the docs artifacts, which closes the gap without handing the changelog to
release-please: its generated ``## [x](compare-link) (date)`` heading does not
match the ``## [x] - date`` form ``changelog_to_json.py`` parses, so the release
would silently vanish from ``docs/changelog.json``.

Whatever was curated under ``## [Unreleased]`` during the cycle becomes the
release's entry, and a fresh empty ``## [Unreleased]`` is left for the next one.

Idempotent: the workflow re-runs on its own push, and a tree that already has a
heading for this version is left alone.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
import tomllib
from pathlib import Path

UNRELEASED_HEADING = re.compile(r"^##\s*\[Unreleased\]\s*$", re.M | re.I)


def promote(text: str, version: str, date: str) -> str:
    """Replace the ``## [Unreleased]`` heading with one for ``version``.

    The bullets under it are untouched -- they become the release's entry -- and
    a new empty ``## [Unreleased]`` takes its place above.
    """
    return UNRELEASED_HEADING.sub(
        f"## [Unreleased]\n\n## [{version}] - {date}",
        text,
        count=1,
    )


def main() -> int:
    root = Path.cwd()
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")

    if re.search(rf"^##\s*\[{re.escape(version)}\]", text, re.M):
        print(f"CHANGELOG.md already has a {version} heading; nothing to promote.")
        return 0

    if not UNRELEASED_HEADING.search(text):
        print(
            f"error: CHANGELOG.md has no '## [Unreleased]' heading and no {version} "
            "heading, so this release would ship with no changelog entry. Add the "
            "section back and describe what is being released.",
            file=sys.stderr,
        )
        return 1

    date = dt.datetime.now(dt.UTC).date().isoformat()
    path.write_text(promote(text, version, date), encoding="utf-8")
    print(f"promoted '## [Unreleased]' to '## [{version}] - {date}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
