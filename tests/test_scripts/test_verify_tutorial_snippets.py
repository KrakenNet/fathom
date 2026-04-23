import importlib.util
import subprocess
import sys
import textwrap
import types
from pathlib import Path

SCRIPT = Path.cwd() / "scripts" / "verify_tutorial_snippets.py"


def _load_module() -> types.ModuleType:
    import sys as _sys

    spec = importlib.util.spec_from_file_location("verify_tutorial_snippets", str(SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    _sys.modules["verify_tutorial_snippets"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _run(tutorials_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(tutorials_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_good_python_block_passes(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(
        textwrap.dedent("""\
        # t

        ```python
        x = 1 + 1
        assert x == 2
        ```
        """)
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout


def test_bad_python_block_fails(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(
        textwrap.dedent("""\
        ```python
        raise RuntimeError("nope")
        ```
        """)
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "RuntimeError" in r.stderr


def test_no_verify_skipped(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(
        textwrap.dedent("""\
        ```python no-verify
        raise RuntimeError("nope")
        ```
        """)
    )
    r = _run(tmp_path)
    assert r.returncode == 0


def test_consecutive_python_blocks_share_scope(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(
        textwrap.dedent("""\
        ```python
        x = 5
        ```

        ```python
        assert x == 5
        ```
        """)
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout


def test_reset_breaks_scope(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(
        textwrap.dedent("""\
        ```python
        x = 5
        ```

        ```python reset
        assert x == 5
        ```
        """)
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "NameError" in r.stderr


def test_timeout_produces_exit_1_with_message(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "_TIMEOUT_SECONDS", 0.2)

    (tmp_path / "t.md").write_text(
        textwrap.dedent("""\
        ```python
        while True: pass
        ```
        """)
    )

    blocks = mod._extract(tmp_path / "t.md")
    rc, stderr = mod._run_python_group(blocks)
    assert rc == 1
    assert "timed out" in stderr
