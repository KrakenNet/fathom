import json
import subprocess
import sys
from pathlib import Path


def test_mcp_manifest_has_all_tools(tmp_path: Path) -> None:
    out = tmp_path / "mcp"
    result = subprocess.run(
        [sys.executable, "scripts/generate_mcp_manifest.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    tools = manifest["tools"]
    names = {t["name"] for t in tools}
    assert {
        "fathom.evaluate",
        "fathom.assert_fact",
        "fathom.query",
        "fathom.retract",
    }.issubset(names), f"got {names}"

    for tool in tools:
        assert tool["description"], f"tool {tool['name']} missing description"
        assert "input_schema" in tool

    for name in ("evaluate", "assert_fact", "query", "retract"):
        page = out / f"{name}.md"
        assert page.exists(), f"missing per-tool page: {page}"
        assert f"fathom.{name}" in page.read_text(encoding="utf-8")
