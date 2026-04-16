import subprocess
import sys
from pathlib import Path

import pytest

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
    (pkg / "__init__.py").write_text(
        '__version__ = "1.2.3"\n', encoding="utf-8"
    )
    result = run_script(tmp_path)
    assert result.returncode == 0, result.stderr


def test_fails_when_versions_differ(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    pkg = tmp_path / "src" / "fathom"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        '__version__ = "1.2.4"\n', encoding="utf-8"
    )
    result = run_script(tmp_path)
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
