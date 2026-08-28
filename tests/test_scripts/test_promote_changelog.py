"""``promote_changelog.py`` is what makes a release PR green on arrival.

The end-to-end case is ``test_a_release_bump_goes_from_red_to_green``: it
reproduces the exact failure every release PR through 0.11.0 hit, then shows
the promotion clearing it.
"""

import subprocess
import sys
from pathlib import Path

PROMOTE = Path("scripts/promote_changelog.py").resolve()
VERSION_SYNC = Path("scripts/check_version_sync.py").resolve()
TO_JSON = Path("scripts/changelog_to_json.py").resolve()

PREAMBLE = "# Changelog\n\nAll notable changes are documented here.\n\n"


def run(script: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def tree(tmp_path: Path, version: str, changelog: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8"
    )
    pkg = tmp_path / "src" / "fathom"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return tmp_path


def test_a_release_bump_goes_from_red_to_green(tmp_path: Path) -> None:
    """The 0.12.0 release PR, reproduced: version-sync red, then green.

    release-please bumps pyproject.toml to the new version and leaves
    CHANGELOG.md alone, so the gate reports skew against the *previous*
    release's heading. Promoting the Unreleased section is what clears it.
    """
    root = tree(
        tmp_path,
        "0.12.0",
        PREAMBLE + "## [Unreleased]\n\n### Fixed\n- A real fix.\n\n## [0.11.0] - 2026-08-26\n\n"
        "### Added\n- Something older.\n",
    )

    before = run(VERSION_SYNC, root)
    assert before.returncode == 1
    assert "CHANGELOG.md=0.11.0" in before.stderr

    promoted = run(PROMOTE, root)
    assert promoted.returncode == 0, promoted.stderr

    after = run(VERSION_SYNC, root)
    assert after.returncode == 0, after.stderr


def test_the_bullets_survive_and_a_fresh_unreleased_is_left(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        "1.0.0",
        PREAMBLE
        + "## [Unreleased]\n\n### Fixed\n- Kept this bullet.\n\n## [0.9.0] - 2026-01-01\n",
    )
    assert run(PROMOTE, root).returncode == 0

    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## [")]
    assert headings[0] == "## [Unreleased]"
    assert headings[1].startswith("## [1.0.0] - ")
    assert "- Kept this bullet." in text.split(headings[1])[1]


def test_the_promoted_heading_is_the_form_the_docs_parser_reads(tmp_path: Path) -> None:
    """A heading the docs pipeline cannot parse drops the release from the site.

    release-please's own ``## [x](compare-link) (date)`` form is exactly that:
    ``changelog_to_json.py`` skips it silently, so the release would vanish from
    ``docs/changelog.json`` while every gate stayed green. Promotion must emit
    the Keep-a-Changelog form instead.
    """
    root = tree(
        tmp_path,
        "2.3.4",
        PREAMBLE + "## [Unreleased]\n\n### Fixed\n- Parsed bullet.\n\n## [2.3.3] - 2026-01-01\n",
    )
    assert run(PROMOTE, root).returncode == 0
    assert run(TO_JSON, root, "CHANGELOG.md", "out.json").returncode == 0

    import json

    entries = json.loads((root / "out.json").read_text(encoding="utf-8"))
    assert entries[0]["version"] == "2.3.4"
    assert entries[0]["fixed"] == ["Parsed bullet."]


def test_a_second_run_changes_nothing(tmp_path: Path) -> None:
    """The workflow re-runs on its own push, so promotion must be idempotent."""
    root = tree(
        tmp_path,
        "1.0.0",
        PREAMBLE + "## [Unreleased]\n\n### Fixed\n- One.\n\n## [0.9.0] - 2026-01-01\n",
    )
    assert run(PROMOTE, root).returncode == 0
    once = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    second = run(PROMOTE, root)
    assert second.returncode == 0, second.stderr
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == once


def test_a_release_with_nothing_to_say_is_refused(tmp_path: Path) -> None:
    """No Unreleased heading and no heading for this version means the release
    would ship with no entry at all. Better to say so than to invent one."""
    root = tree(tmp_path, "1.0.0", PREAMBLE + "## [0.9.0] - 2026-01-01\n\n### Added\n- Old.\n")
    result = run(PROMOTE, root)
    assert result.returncode == 1
    assert "no changelog entry" in result.stderr
