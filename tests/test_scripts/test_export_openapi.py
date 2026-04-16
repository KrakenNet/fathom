import json
import subprocess
import sys
from pathlib import Path


def test_export_writes_valid_openapi(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    result = subprocess.run(
        [sys.executable, "scripts/export_openapi.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["openapi"].startswith("3.")
    assert "Fathom" in data["info"]["title"]
    assert "paths" in data and len(data["paths"]) > 0
