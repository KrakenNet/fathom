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


def _tree(tmp_path: Path, py: str, init: str, ts: str | None = None) -> Path:
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
