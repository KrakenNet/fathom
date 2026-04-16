import json
import subprocess
import sys
from pathlib import Path


def test_exports_known_schemas(tmp_path: Path) -> None:
    out_dir = tmp_path / "schemas"
    result = subprocess.run(
        [sys.executable, "scripts/export_json_schemas.py", str(out_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for name in ("template", "rule", "module", "function"):
        path = out_dir / f"{name}.schema.json"
        assert path.exists(), f"missing {name}.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert "$schema" in schema
        assert schema.get("title") or schema.get("$defs") or "properties" in schema
