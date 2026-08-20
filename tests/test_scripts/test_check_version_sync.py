import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/check_version_sync.py").resolve()


def run_script(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_passes_when_versions_match(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    pkg = tmp_path / "src" / "fathom"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    result = run_script(tmp_path)
    assert result.returncode == 0, result.stderr


def test_fails_when_versions_differ(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    pkg = tmp_path / "src" / "fathom"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.4"\n', encoding="utf-8")
    result = run_script(tmp_path)
    assert result.returncode != 0
    assert "version" in result.stderr.lower()


def _tree(
    tmp_path: Path,
    py: str,
    init: str,
    ts: str | None = None,
    readme: str | None = None,
    index: str | None = None,
    changelog: str | None = None,
) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{py}"\n', encoding="utf-8"
    )
    pkg = tmp_path / "src" / "fathom"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(f'__version__ = "{init}"\n', encoding="utf-8")
    if ts is not None:
        sdk = tmp_path / "packages" / "fathom-ts"
        sdk.mkdir(parents=True)
        (sdk / "package.json").write_text(
            f'{{"name": "@fathom-rules/sdk", "version": "{ts}"}}\n', encoding="utf-8"
        )
    if readme is not None:
        (tmp_path / "README.md").write_text(
            f"# x\n\n**Current version:** {readme} <!-- x-release-please-version -->\n",
            encoding="utf-8",
        )
    if index is not None:
        docs = tmp_path / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "index.md").write_text(
            f"# x\n\nCurrent release: `fathom-rules` {index} (requires Python 3.12+).\n",
            encoding="utf-8",
        )
    if changelog is not None:
        (tmp_path / "CHANGELOG.md").write_text(
            f"# Changelog\n\n## [{changelog}] - 2026-01-01\n\n### Added\n- x\n",
            encoding="utf-8",
        )
    return tmp_path


def test_fails_when_ts_sdk_version_lags(tmp_path: Path) -> None:
    """The TS SDK ships on the same tag, so a stale package.json is skew.

    It sat at 0.1.0 through every release before this was enforced, which
    meant each tag asked npm to republish a version that already existed.
    """
    result = run_script(_tree(tmp_path, "1.2.3", "1.2.3", ts="0.1.0"))
    assert result.returncode != 0
    assert "packages/fathom-ts/package.json=0.1.0" in result.stderr


def test_passes_when_ts_sdk_version_matches(tmp_path: Path) -> None:
    result = run_script(_tree(tmp_path, "1.2.3", "1.2.3", ts="1.2.3"))
    assert result.returncode == 0, result.stderr


def test_absent_ts_sdk_is_not_skew(tmp_path: Path) -> None:
    """A missing source is skipped -- absence is not disagreement."""
    result = run_script(_tree(tmp_path, "1.2.3", "1.2.3"))
    assert result.returncode == 0, result.stderr


def test_reports_every_skewed_source_at_once(tmp_path: Path) -> None:
    result = run_script(_tree(tmp_path, "1.2.3", "1.2.4", ts="0.1.0"))
    assert result.returncode != 0
    assert "src/fathom/__init__.py=1.2.4" in result.stderr
    assert "packages/fathom-ts/package.json=0.1.0" in result.stderr


def test_fails_when_readme_prose_version_lags(tmp_path: Path) -> None:
    """The exact drift this was written for: prose said 0.7.0, PyPI had 0.7.4."""
    result = run_script(_tree(tmp_path, "1.2.3", "1.2.3", readme="1.2.0"))
    assert result.returncode == 1
    assert "README.md=1.2.0" in result.stderr


def test_fails_when_docs_index_prose_version_lags(tmp_path: Path) -> None:
    result = run_script(_tree(tmp_path, "1.2.3", "1.2.3", index="1.2.0"))
    assert result.returncode == 1
    assert "docs/index.md=1.2.0" in result.stderr


def test_passes_when_prose_versions_match(tmp_path: Path) -> None:
    result = run_script(_tree(tmp_path, "1.2.3", "1.2.3", readme="1.2.3", index="1.2.3"))
    assert result.returncode == 0, result.stderr


def test_reworded_version_line_fails_loudly(tmp_path: Path) -> None:
    """A prose file that no longer carries a version line is a broken gate.

    Silently skipping it would leave the check passing forever after an
    innocuous README rewrite -- which is how the drift started.
    """
    tree = _tree(tmp_path, "1.2.3", "1.2.3", readme="1.2.3")
    (tree / "README.md").write_text("# x\n\nVersion: 1.2.3\n", encoding="utf-8")
    result = run_script(tree)
    assert result.returncode != 0
    assert "no version line matching" in result.stderr


def test_fails_when_changelog_has_no_entry_for_the_release(tmp_path: Path) -> None:
    """The release PR bumps pyproject; the entry has to be written by hand."""
    result = run_script(_tree(tmp_path, "1.2.3", "1.2.3", changelog="1.2.2"))
    assert result.returncode == 1
    assert "CHANGELOG.md=1.2.2" in result.stderr


def test_passes_when_changelog_documents_the_release(tmp_path: Path) -> None:
    result = run_script(_tree(tmp_path, "1.2.3", "1.2.3", changelog="1.2.3"))
    assert result.returncode == 0, result.stderr


def test_unreleased_heading_is_not_the_newest_release(tmp_path: Path) -> None:
    """An `## [Unreleased]` block must not satisfy the check for a shipped version."""
    tree = _tree(tmp_path, "1.2.3", "1.2.3", changelog="1.2.3")
    (tree / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- x\n\n"
        "## [1.2.2] - 2026-01-01\n\n### Added\n- y\n",
        encoding="utf-8",
    )
    result = run_script(tree)
    assert result.returncode == 1
    assert "CHANGELOG.md=1.2.2" in result.stderr
