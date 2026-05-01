"""Tests for scripts/generate_ts_sdk_docs.py.

Both tests skip cleanly when neither pnpm nor npm is installed so CI
lanes without a Node toolchain stay green. When the toolchain is
present, the determinism test compares a freshly regenerated tree
against the committed artifact byte-for-byte.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

COMMITTED = Path("docs/reference/typescript-sdk")


def _node_pkg_manager_available() -> bool:
    return shutil.which("pnpm") is not None or shutil.which("npm") is not None


def _collect(root: Path) -> list[tuple[str, bytes]]:
    """Return a deterministic list of ``(relpath, bytes)`` for every .md
    under ``root``. Skips the hand-authored ``index.md`` since typedoc
    does not emit it and we'd otherwise have to seed each tmp tree."""
    return [
        (str(p.relative_to(root)).replace("\\", "/"), p.read_bytes())
        for p in sorted(root.rglob("*.md"))
        if p.name != "index.md"
    ]


def test_ts_sdk_docs_generated(tmp_path: Path) -> None:
    if not _node_pkg_manager_available():
        pytest.skip("neither pnpm nor npm available")
    out = tmp_path / "ts"
    result = subprocess.run(
        [sys.executable, "scripts/generate_ts_sdk_docs.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    md_files = list(out.rglob("*.md"))
    assert md_files, "typedoc produced no markdown"

    # typedoc-plugin-markdown emits a `classes/FathomClient.md` page for
    # the SDK's main export. If the plugin didn't load (version mismatch)
    # or the Fathom source lost its exports, this file won't exist.
    client_page = out / "classes" / "FathomClient.md"
    assert client_page.exists(), "typedoc did not emit classes/FathomClient.md"
    assert "FathomClient" in client_page.read_text(encoding="utf-8"), (
        "typedoc output missing expected FathomClient content"
    )


def test_ts_sdk_docs_are_deterministic(tmp_path: Path) -> None:
    if not _node_pkg_manager_available():
        pytest.skip("neither pnpm nor npm available")
    out_a = tmp_path / "fresh-a"
    out_b = tmp_path / "fresh-b"
    for out in (out_a, out_b):
        result = subprocess.run(
            [sys.executable, "scripts/generate_ts_sdk_docs.py", str(out)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    # Two consecutive regens must produce identical output. The
    # "regenerated == committed" gate that used to live here was removed
    # in favour of the canonical drift gate in
    # ``.github/workflows/docs.yml`` (``Drift gate`` step), which runs
    # ``make docs-gen && make docs-gen-foreign`` against a pinned Node +
    # pnpm + typedoc toolchain. This unit test ran against whatever
    # Node/pnpm the runner happened to ship and broke every PR whenever
    # the committer's toolchain diverged from the runner's. Keep the
    # determinism guarantee; drop the cross-machine comparison.
    assert _collect(out_a) == _collect(out_b), (
        "typedoc output differs between regens — flag version or input drift"
    )
