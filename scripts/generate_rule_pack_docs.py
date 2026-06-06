"""Generate one Markdown page per rule pack plus a machine-readable catalog.

Walks src/fathom/rule_packs/<pack>/{templates,rules,modules}/*.yaml and
emits docs/reference/rule-packs/<pack-id>.md and rule-packs.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

PACK_ROOT = Path("src/fathom/rule_packs")
DEFAULT_OUT = Path("docs/reference/rule-packs")

# Stable mapping from on-disk pack dirname → public id slug (matches old nav)
PACK_ID = {
    "owasp_agentic": "owasp-agentic",
    "nist_800_53": "nist-800-53",
    "hipaa": "hipaa",
    "cmmc": "cmmc",
    "ssvc": "ssvc",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _pack_summary(pack_dir: Path) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    modules: set[str] = set()
    templates: set[str] = set()

    rules_dir = pack_dir / "rules"
    if rules_dir.exists():
        for yf in sorted(rules_dir.glob("*.yaml")):
            data = _load_yaml(yf)
            mod = data.get("module")
            if mod:
                modules.add(mod)
            for rule in data.get("rules") or []:
                rules.append(
                    {
                        "name": rule.get("name", ""),
                        "salience": rule.get("salience", 0),
                        "action": (rule.get("then") or {}).get("action", ""),
                        "reason": (rule.get("then") or {}).get("reason", ""),
                        "source": yf.as_posix(),
                    }
                )

    tmpl_dir = pack_dir / "templates"
    if tmpl_dir.exists():
        for yf in sorted(tmpl_dir.glob("*.yaml")):
            data = _load_yaml(yf)
            for t in data.get("templates") or []:
                if t.get("name"):
                    templates.add(t["name"])

    return {
        "rules": rules,
        "modules": sorted(modules),
        "templates": sorted(templates),
    }


def _pack_version(pack_dir: Path) -> str:
    rules_dir = pack_dir / "rules"
    if not rules_dir.exists():
        return "0.0"
    for yf in sorted(rules_dir.glob("*.yaml")):
        data = _load_yaml(yf)
        v = data.get("version")
        if v is not None:
            return str(v)
    return "0.0"


def _render_page(pack_id: str, pack_dir: Path, summary: dict[str, Any]) -> str:
    import ast
    init_text = (pack_dir / "__init__.py").read_text(encoding="utf-8")
    module_ast = ast.parse(init_text)
    docstring = ast.get_docstring(module_ast) or ""
    description = docstring.split("\n\n", 1)[0].strip()

    lines = [
        "---",
        f"title: {pack_id}",
        f"summary: Rule pack — {pack_id}",
        "audience: [rule-authors, app-developers]",
        "diataxis: reference",
        "status: stable",
        "last_verified: 2026-04-15",
        "---",
        "",
        f"# Rule Pack: `{pack_id}`",
        "",
        description,
        "",
        f"**Pack version:** `{_pack_version(pack_dir)}`  ",
        f"**Rule count:** {len(summary['rules'])}  ",
        f"**Modules:** {', '.join(f'`{m}`' for m in summary['modules']) or '_none_'}  ",
        f"**Templates:** {', '.join(f'`{t}`' for t in summary['templates']) or '_none_'}",
        "",
        "## Rules",
        "",
        "| Name | Salience | Action | Reason | Source |",
        "|---|---|---|---|---|",
    ]
    for r in summary["rules"]:
        reason = (r["reason"] or "").replace("|", "\\|")
        lines.append(
            f"| `{r['name']}` | {r['salience']} | `{r['action']}` | {reason} | `{r['source']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog: list[dict[str, Any]] = []

    for dirname, pack_id in sorted(PACK_ID.items()):
        pack_dir = PACK_ROOT / dirname
        if not pack_dir.exists():
            print(f"skip: {pack_dir} missing", file=sys.stderr)
            continue
        summary = _pack_summary(pack_dir)
        (out_dir / f"{pack_id}.md").write_text(
            _render_page(pack_id, pack_dir, summary),
            encoding="utf-8",
            newline="\n",
        )
        catalog.append(
            {
                "id": pack_id,
                "version": _pack_version(pack_dir),
                "source": f"src/fathom/rule_packs/{dirname}",
                "modules": summary["modules"],
                "templates": summary["templates"],
                "rules": [
                    {k: r[k] for k in ("name", "salience", "action")}
                    for r in summary["rules"]
                ],
            }
        )

    (out_dir / "rule-packs.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(catalog)} rule pack page(s) and rule-packs.json under {out_dir}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
