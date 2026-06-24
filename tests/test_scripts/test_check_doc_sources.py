import os
import subprocess
import sys
from pathlib import Path


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path.cwd() / "scripts" / "check_doc_sources.py"), str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)


def _commit(root: Path, msg: str, author: str | None = None, when: str | None = None) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    cmd = ["git", "commit", "-q", "-m", msg]
    if author is not None:
        cmd.append(f"--author={author}")
    env = dict(os.environ)
    if when is not None:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    subprocess.run(cmd, cwd=root, check=True, env=env)


PAGE_TEMPLATE = """---
title: Example
summary: x
audience: [app-developers]
diataxis: explanation
status: stable
last_verified: {verified}
sources:
  - src/module.py
---

body
"""


def test_clean_repo_exits_zero(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("x = 1\n")
    _commit(tmp_path, "src")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(PAGE_TEMPLATE.format(verified="2099-01-01"))
    _commit(tmp_path, "docs")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout


def test_source_modified_after_verified_fails(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    src = tmp_path / "src" / "module.py"
    src.write_text("x = 1\n")
    _commit(tmp_path, "src v1")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(PAGE_TEMPLATE.format(verified="2000-01-01"))
    _commit(tmp_path, "docs")
    src.write_text("x = 2\n")
    _commit(tmp_path, "src v2")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "last modified" in result.stderr


def test_missing_source_fails(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(PAGE_TEMPLATE.format(verified="2099-01-01"))
    _commit(tmp_path, "docs")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_dependency_bump_commit_does_not_trip_gate(tmp_path: Path) -> None:
    # A `build(deps)` bump to a cited source AFTER last_verified must be
    # ignored — it's a mechanical version bump, not a content change. The
    # last meaningful commit (src v1) predates last_verified.
    _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    src = tmp_path / "src" / "module.py"
    src.write_text("x = 1\n")
    _commit(tmp_path, "src v1", when="2020-01-01T00:00:00")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(PAGE_TEMPLATE.format(verified="2020-06-01"))
    _commit(tmp_path, "docs", when="2020-06-01T00:00:00")
    src.write_text("x = 2\n")
    _commit(tmp_path, "build(deps): bump module from 1 to 2", when="2026-06-24T00:00:00")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout


def test_dependabot_authored_commit_does_not_trip_gate(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    src = tmp_path / "src" / "module.py"
    src.write_text("x = 1\n")
    _commit(tmp_path, "src v1", when="2020-01-01T00:00:00")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(PAGE_TEMPLATE.format(verified="2020-06-01"))
    _commit(tmp_path, "docs", when="2020-06-01T00:00:00")
    src.write_text("x = 2\n")
    _commit(
        tmp_path,
        "bump dep",
        author="dependabot[bot] <bot@users.noreply.github.com>",
        when="2026-06-24T00:00:00",
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout


def test_meaningful_commit_after_verified_still_fails(tmp_path: Path) -> None:
    # A real (non-mechanical) edit after last_verified must still be
    # caught even if a later dep bump sits on top of it.
    _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    src = tmp_path / "src" / "module.py"
    src.write_text("x = 1\n")
    _commit(tmp_path, "src v1", when="2020-01-01T00:00:00")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(PAGE_TEMPLATE.format(verified="2020-06-01"))
    _commit(tmp_path, "docs", when="2020-06-01T00:00:00")
    src.write_text("x = 2  # real change\n")
    _commit(tmp_path, "feat: change behavior", when="2021-01-01T00:00:00")
    src.write_text("x = 3\n")
    _commit(tmp_path, "build(deps): bump module from 2 to 3", when="2026-06-24T00:00:00")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "last modified" in result.stderr


def test_page_without_sources_is_skipped(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(
        "---\ntitle: x\nsummary: x\naudience: [app-developers]\n"
        "diataxis: landing\nstatus: stable\nlast_verified: 2099-01-01\n---\n"
    )
    _commit(tmp_path, "docs")
    result = _run(tmp_path)
    assert result.returncode == 0
