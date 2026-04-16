"""Introspect FathomMCPServer and emit manifest.json + per-tool Markdown pages."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_OUT = Path("docs/reference/mcp")


def _collect_tools() -> list[dict[str, Any]]:
    from fathom.integrations.mcp_server import FathomMCPServer

    server = FathomMCPServer()
    tool_objs: list[Any] = []
    mcp = getattr(server, "_mcp", None) or getattr(server, "mcp", None)
    if mcp is not None:
        mgr = getattr(mcp, "_tool_manager", None)
        if mgr is not None and hasattr(mgr, "list_tools"):
            tool_objs = list(mgr.list_tools())
    if not tool_objs:
        tool_objs = list(getattr(server, "_tools", []) or [])

    out: list[dict[str, Any]] = []
    for t in tool_objs:
        name = getattr(t, "name", "")
        desc = getattr(t, "description", "") or ""
        input_schema = (
            getattr(t, "inputSchema", None)
            or getattr(t, "input_schema", None)
            or getattr(t, "parameters", None)
            or {}
        )
        out.append(
            {
                "name": name,
                "description": desc.strip(),
                "input_schema": input_schema,
            }
        )
    out.sort(key=lambda entry: entry["name"])
    return out


def _render_tool_page(tool: dict[str, Any]) -> str:
    short_name = tool["name"].split(".", 1)[-1]
    schema_block = json.dumps(tool["input_schema"], indent=2, sort_keys=True)
    return "\n".join(
        [
            "---",
            f"title: {tool['name']}",
            f"summary: MCP tool — {tool['name']}",
            "audience: [agent-engineers]",
            "diataxis: reference",
            "status: stable",
            "last_verified: 2026-04-15",
            "---",
            "",
            f"# `{tool['name']}`",
            "",
            tool["description"] or "_No description._",
            "",
            "## Input schema",
            "",
            "```json",
            schema_block,
            "```",
            "",
            f"[↩ Back to MCP tool index](./index.md) · short name: `{short_name}`",
            "",
        ]
    )


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    tools = _collect_tools()
    manifest = {"version": "1.0", "tools": tools}
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for tool in tools:
        short_name = tool["name"].split(".", 1)[-1]
        (out_dir / f"{short_name}.md").write_text(
            _render_tool_page(tool), encoding="utf-8", newline="\n"
        )

    index = [
        "---",
        "title: MCP Tool Manifest",
        "summary: Machine-readable index of Fathom MCP tools",
        "audience: [agent-engineers]",
        "diataxis: reference",
        "status: stable",
        "last_verified: 2026-04-15",
        "---",
        "",
        "# MCP Tool Manifest",
        "",
        "Raw manifest: [`manifest.json`](manifest.json)",
        "",
        "| Tool | Description |",
        "|---|---|",
    ]
    for t in tools:
        short = t["name"].split(".", 1)[-1]
        desc = t["description"].replace("|", "\\|").splitlines()[0] if t["description"] else ""
        index.append(f"| [`{t['name']}`]({short}.md) | {desc} |")
    index.append("")
    (out_dir / "index.md").write_text("\n".join(index), encoding="utf-8", newline="\n")
    print(f"wrote manifest.json + {len(tools)} tool page(s) under {out_dir}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
