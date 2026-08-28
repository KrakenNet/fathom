"""``check_changelog_entry.py`` moves the changelog requirement onto the PR
that causes it, so the release PR is never the first thing to notice.
"""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/check_changelog_entry.py").resolve()

PREAMBLE = "# Changelog\n\nAll notable changes are documented here.\n\n"
BASE_CHANGELOG = PREAMBLE + "## [Unreleased]\n\n## [0.9.0] - 2026-01-01\n\n### Added\n- Old.\n"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def repo_with(tmp_path: Path, *, subject: str, changelog: str | None) -> Path:
    """A repo whose ``base`` branch holds BASE_CHANGELOG and whose HEAD adds one
    commit with ``subject``, optionally rewriting the changelog."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "base")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")
    (repo / "CHANGELOG.md").write_text(BASE_CHANGELOG, encoding="utf-8")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "CHANGELOG.md", "code.py")
    git(repo, "commit", "-qm", "chore: base")

    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
    paths = ["code.py"]
    if changelog is not None:
        (repo / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        paths.append("CHANGELOG.md")
    git(repo, "add", *paths)
    git(repo, "commit", "-qm", subject)
    return repo


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "base", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_fix_with_no_changelog_line_is_refused(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, subject="fix(engine): stop a deny reading as allow", changelog=None)
    result = run(repo)
    assert result.returncode == 1
    assert "fix(engine): stop a deny reading as allow" in result.stderr


def test_a_fix_that_describes_itself_passes(tmp_path: Path) -> None:
    repo = repo_with(
        tmp_path,
        subject="fix(engine): stop a deny reading as allow",
        changelog=PREAMBLE
        + "## [Unreleased]\n\n### Fixed\n- A deny no longer reads as allow.\n\n"
        + "## [0.9.0] - 2026-01-01\n\n### Added\n- Old.\n",
    )
    result = run(repo)
    assert result.returncode == 0, result.stderr


def test_a_chore_branch_is_not_asked_for_one(tmp_path: Path) -> None:
    """Only feat:/fix: reach a release, so only they owe an entry. A gate that
    fired on every branch would be noise, and noise is what gets ignored."""
    repo = repo_with(tmp_path, subject="chore: bump a dev dependency", changelog=None)
    result = run(repo)
    assert result.returncode == 0, result.stderr


def test_a_squash_merge_is_judged_on_its_pull_request_title(tmp_path: Path) -> None:
    """Squash-merge lands the PR title as the release commit, so a branch of
    ``wip`` commits under a ``feat:`` title still owes an entry."""
    repo = repo_with(tmp_path, subject="wip", changelog=None)
    assert run(repo).returncode == 0
    result = run(repo, "feat(api): add a thing")
    assert result.returncode == 1
    assert "feat(api): add a thing" in result.stderr


def test_editing_an_untouched_unreleased_section_is_not_an_entry(tmp_path: Path) -> None:
    """Carrying the section forward unchanged is not describing your change."""
    repo = repo_with(
        tmp_path, subject="fix: something", changelog=BASE_CHANGELOG + "\n<!-- trailing -->\n"
    )
    result = run(repo)
    assert result.returncode == 1
