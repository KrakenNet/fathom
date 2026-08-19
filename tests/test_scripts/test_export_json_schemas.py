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


def test_committed_schemas_are_in_sync(tmp_path: Path) -> None:
    """The published schemas must agree with the loader about unknown keys."""
    out_dir = tmp_path / "schemas"
    result = subprocess.run(
        [sys.executable, "scripts/export_json_schemas.py", str(out_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    published = Path("docs/reference/yaml/schemas")
    for generated in sorted(out_dir.glob("*.schema.json")):
        committed = published / generated.name
        assert committed.exists(), f"{generated.name} is not published"
        assert json.loads(generated.read_text(encoding="utf-8")) == json.loads(
            committed.read_text(encoding="utf-8")
        ), f"{committed} is stale — run `python scripts/export_json_schemas.py {published}`"


def test_schemas_forbid_unknown_keys() -> None:
    """The loader rejects unknown keys, so the published schema must too.

    Without object-level ``additionalProperties: false`` an external
    validator blessed a typo like ``saliance: 100`` that ``Engine.from_rules``
    then refused — the published contract contradicted the runtime one.
    """
    published = Path("docs/reference/yaml/schemas")
    for name in ("template", "rule", "module", "function", "hierarchy"):
        schema = json.loads((published / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert schema.get("additionalProperties") is False, name
        for def_name, defn in schema.get("$defs", {}).items():
            if defn.get("type") == "object" and "properties" in defn:
                assert defn.get("additionalProperties") is False, f"{name}.{def_name}"
