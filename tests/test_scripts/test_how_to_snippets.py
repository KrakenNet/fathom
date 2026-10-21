"""How-to pages whose Python blocks run as written, from the repository root."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "verify_tutorial_snippets", ROOT / "scripts" / "verify_tutorial_snippets.py"
)
assert _spec is not None and _spec.loader is not None
_snippets = importlib.util.module_from_spec(_spec)
sys.modules["verify_tutorial_snippets"] = _snippets
_spec.loader.exec_module(_snippets)


@pytest.mark.parametrize("page", ["embed-sdk.md", "fleet.md"])
def test_how_to_python_blocks_run(page: str) -> None:
    blocks = [
        b
        for b in _snippets._extract(ROOT / "docs" / "how-to" / page)
        if b.lang == "python" and "no-verify" not in b.tags
    ]
    program = "\n".join(b.body for b in blocks)
    r = subprocess.run(
        [sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, r.stderr
