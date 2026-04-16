import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/check_docstrings.py").resolve()


def _write_pkg(tmp_path: Path, init_body: str, *extra: tuple[str, str]) -> None:
    pkg = tmp_path / "src" / "fake_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(init_body, encoding="utf-8")
    for name, body in extra:
        (pkg / name).write_text(body, encoding="utf-8")


def _env_with_src(tmp_path: Path) -> dict[str, str]:
    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path / "src")
    return env


def test_passes_when_all_documented(tmp_path: Path) -> None:
    _write_pkg(
        tmp_path,
        '"""Pkg."""\nfrom fake_pkg.mod import Thing\n__all__ = ["Thing"]\n',
        ("mod.py", '"""Mod."""\nclass Thing:\n    """Doc."""\n'),
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "fake_pkg"],
        cwd=tmp_path,
        env=_env_with_src(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fails_when_symbol_missing_docstring(tmp_path: Path) -> None:
    _write_pkg(
        tmp_path,
        '"""Pkg."""\nfrom fake_pkg.mod import Thing\n__all__ = ["Thing"]\n',
        ("mod.py", '"""Mod."""\nclass Thing:\n    pass\n'),
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "fake_pkg"],
        cwd=tmp_path,
        env=_env_with_src(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Thing" in result.stdout + result.stderr
