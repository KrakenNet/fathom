import subprocess
import sys
from pathlib import Path


def test_python_sdk_docs_generated(tmp_path: Path) -> None:
    out_dir = tmp_path / "python-sdk"
    result = subprocess.run(
        [sys.executable, "scripts/generate_python_sdk_docs.py", str(out_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    # Landing page + one stub per public symbol
    assert (out_dir / "index.md").exists()
    assert (out_dir / "engine.md").exists()
    all_md = list(out_dir.rglob("*.md"))
    flat = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in all_md)
    assert "Engine" in flat, "expected Engine stub"
    assert "EvaluationResult" in flat, "expected EvaluationResult stub"
    # Every stub must contain a mkdocstrings directive
    assert ":::" in flat, "expected mkdocstrings ::: directive"
