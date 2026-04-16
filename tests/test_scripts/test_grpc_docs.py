import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_grpc_docs_generated(tmp_path: Path) -> None:
    if shutil.which("protoc") is None or shutil.which("protoc-gen-doc") is None:
        pytest.skip("protoc or protoc-gen-doc not available")
    out = tmp_path / "grpc"
    result = subprocess.run(
        [sys.executable, "scripts/generate_grpc_docs.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    md = (out / "fathom.md").read_text(encoding="utf-8")
    assert "FathomService" in md
    assert "Evaluate" in md
    # Proto file is copied alongside
    assert (out / "fathom.proto").exists()


def test_grpc_docs_are_deterministic(tmp_path: Path) -> None:
    if shutil.which("protoc") is None or shutil.which("protoc-gen-doc") is None:
        pytest.skip("protoc or protoc-gen-doc not available")
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    for out in (out_a, out_b):
        result = subprocess.run(
            [sys.executable, "scripts/generate_grpc_docs.py", str(out)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    assert (out_a / "fathom.md").read_bytes() == (out_b / "fathom.md").read_bytes(), (
        "protoc-gen-doc output differs between regens — flag version or input drift"
    )
    assert (out_a / "fathom.proto").read_bytes() == (out_b / "fathom.proto").read_bytes()
