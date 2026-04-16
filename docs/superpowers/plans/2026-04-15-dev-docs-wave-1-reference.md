# Dev Docs — Wave 1 (Reference Generation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate every SDK/API reference (Python, Go, TypeScript, REST, gRPC, MCP, CLI, rule packs, JSON Schemas, VSCode snippets) from source at build time, consolidate them under `docs/reference/*` in the MkDocs nav, redirect the legacy `docs/api/*`, `docs/integrations/*`, and `docs/rule-packs/*` URLs to the new locations, and ship a `docs-deploy.yml` workflow that publishes versioned docs to GitHub Pages via `mike`.

**Architecture:** Each generator is a thin Python script (`scripts/generate_*.py`) that reads the canonical source (Python `__all__`, Typer app, `FathomMCPServer` tool registry, rule-pack YAML tree, FastAPI OpenAPI, `.proto` file) and writes deterministic Markdown or JSON under `docs/reference/`. Foreign-toolchain generators (gomarkdoc, typedoc, protoc-gen-doc, openapi-to-postmanv2) are invoked from a `scripts/generate_foreign_docs.sh` wrapper that is skipped locally when the toolchain is absent and always run in CI. The `docs-gen` Makefile target orchestrates everything; the drift gate in `.github/workflows/docs.yml` guarantees committed artifacts match generated artifacts.

**Tech Stack:** Python 3.14 + `uv`, MkDocs Material, `pdoc`, `mike`, `mkdocs-redirects`, `mkdocs-swagger-ui-tag`, `gomarkdoc` (Go), `typedoc` + `typedoc-plugin-markdown` (Node/pnpm), `protoc` + `protoc-gen-doc`, `openapi-to-postmanv2` (npx).

**Assumes Wave 0 landed:** all 20 Wave 0 commits on `master` through `3a75ada`, CI green, stubs in place at `scripts/generate_cli_docs.py`, `scripts/generate_rule_pack_docs.py`, `scripts/generate_mcp_manifest.py`.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `scripts/generate_python_sdk_docs.py` | Shell out to `pdoc`, write Markdown tree under `docs/reference/python-sdk/`. |
| `scripts/generate_foreign_docs.sh` | Idempotent wrapper for gomarkdoc + typedoc + protoc-gen-doc + postman conversion; tolerant of missing toolchains. |
| `scripts/check_sdk_coverage.py` | Fails CI if any `fathom.__all__` symbol has no generated page. |
| `docs/reference/rest/index.md` | REST landing page with Redoc embed + "Run in Postman" link. |
| `docs/reference/rest/try.md` | Swagger UI interactive try-it, embedded via `<swagger-ui>` tag. |
| `docs/reference/grpc/index.md` | gRPC landing page linking the generated `fathom.md` and raw `.proto`. |
| `docs/reference/yaml/index.md` | JSON Schemas download landing page with VSCode setup snippet. |
| `docs/reference/tooling/vscode/fathom.code-snippets` | Static VSCode snippets for templates/rules/modules/functions. |
| `docs/reference/tooling/vscode/index.md` | Landing page explaining installation and schema association. |
| `.github/workflows/docs-deploy.yml` | On tag push / manual dispatch, builds + deploys via `mike` to `gh-pages`. |
| `tests/test_scripts/test_python_sdk_docs.py` | Asserts pdoc run emits one file per `__all__` symbol. |
| `tests/test_scripts/test_sdk_coverage.py` | Asserts coverage script fails cleanly when page missing. |
| `tests/test_scripts/test_mcp_manifest_real.py` | Asserts real MCP manifest has 4 tools with non-empty schemas. |
| `tests/test_scripts/test_cli_docs_real.py` | Asserts CLI generator emits one page per `@app.command`. |
| `tests/test_scripts/test_rule_pack_docs_real.py` | Asserts rule-pack generator emits one page per pack + rule-packs.json. |

### Modified files

| Path | Change |
|---|---|
| `scripts/generate_cli_docs.py` | Replace stub with real Typer-introspection emitter. |
| `scripts/generate_rule_pack_docs.py` | Replace stub with real rule-pack walker. |
| `scripts/generate_mcp_manifest.py` | Replace stub with real `FathomMCPServer` introspector + per-tool page emitter. |
| `Makefile` | Add new generator invocations to `docs-gen`; add `docs-gen-foreign` target. |
| `mkdocs.yml` | Add Reference section to nav; add redirect_maps; add swagger-ui-tag plugin. |
| `pyproject.toml` | Add `mkdocs-swagger-ui-tag` to `docs` extra. |
| `.github/workflows/docs.yml` | Add Go / Node / protoc setup; run foreign-docs generator; extend drift gate globs. |

### Deleted / retired files (nav-level only; files stay on disk until Wave 2)

Old legacy pages stay physically present but disappear from nav and gain `redirect_maps` entries. No `git rm` in this wave.

---

## Task Dependency

```
1 (pyproject + mkdocs plugin)
├─► 2 (Python SDK via pdoc)
│   └─► 3 (coverage gate)
├─► 4 (rule-pack generator)
├─► 5 (MCP manifest generator)
├─► 6 (CLI generator)
├─► 7 (REST Swagger/Redoc landing)
├─► 8 (Postman collection)
├─► 9 (gRPC via protoc-gen-doc)
├─► 10 (Go SDK via gomarkdoc)
├─► 11 (TS SDK via typedoc)
├─► 12 (VSCode snippets + JSON Schema landing)
├─► 13 (Makefile orchestration + foreign wrapper)
├─► 14 (mkdocs.yml nav flip + redirects)
├─► 15 (docs.yml CI: foreign toolchains + drift gate extension)
└─► 16 (docs-deploy.yml via mike)
    └─► 17 (Wave 1 completion record)
```

Tasks 2–12 are mostly independent and can be tackled in any order after Task 1. Task 13 gates on 2–12. Task 14 gates on 2–6 (the Python-native generators that produce landing pages). Task 15 gates on 9/10/11. Task 16 is last before the completion record.

---

## Task 1: Install Wave 1 build plugins

**Files:**
- Modify: `pyproject.toml` — `docs` optional-dependency group
- Modify: `mkdocs.yml` — plugin list

- [ ] **Step 1: Add `mkdocs-swagger-ui-tag` to docs extra**

Edit `pyproject.toml`, inside `[project.optional-dependencies].docs`, after `"codespell>=2.2",` add:

```toml
    "mkdocs-swagger-ui-tag>=0.6",
```

- [ ] **Step 2: Register the plugin in mkdocs.yml**

Edit `mkdocs.yml`, in the `plugins:` list (currently contains `search`, `redirects`, `mkdocstrings`), add `swagger-ui-tag` as a new list item after `redirects`:

```yaml
  - swagger-ui-tag
```

- [ ] **Step 3: Sync deps and verify**

Run:
```bash
uv sync --extra docs --extra server
uv run mkdocs build --strict
```

Expected: build succeeds; no "plugin not found" error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml mkdocs.yml
git commit -m "build(docs): add mkdocs-swagger-ui-tag for Wave 1 REST reference"
```

---

## Task 2: Python SDK reference via mkdocstrings stubs

**Background:** pdoc v14+ dropped its Markdown output format (HTML-only now). The project already depends on `mkdocstrings[python]` and has the handler registered in `mkdocs.yml` with `paths: [src]`. We therefore generate one tiny Markdown stub per public symbol in `fathom.__all__`; each stub contains a `:::` directive that mkdocstrings expands at `mkdocs build` time using the live docstrings and type hints. This keeps the file-per-symbol IA, survives Python version changes, and has no drift-gate risk (stubs are deterministic because `__all__` is stable).

**Files:**
- Create: `scripts/generate_python_sdk_docs.py`
- Create: `tests/test_scripts/test_python_sdk_docs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scripts/test_python_sdk_docs.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
uv run pytest tests/test_scripts/test_python_sdk_docs.py -v
```

Expected: FAIL with "No such file or directory: 'scripts/generate_python_sdk_docs.py'".

- [ ] **Step 3: Implement the script**

Create `scripts/generate_python_sdk_docs.py`:

```python
"""Generate Python SDK reference stubs under docs/reference/python-sdk/.

Reads ``fathom.__all__`` and writes one short Markdown stub per public
symbol. Each stub uses a ``:::`` mkdocstrings directive so the actual
API reference (signatures, docstrings, type hints) is rendered at
``mkdocs build`` time from live source. Also writes an ``index.md``
landing page that links every symbol.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fathom

DEFAULT_OUT = Path("docs/reference/python-sdk")


def _stub_body(qualname: str) -> str:
    return f"# `fathom.{qualname}`\n\n::: fathom.{qualname}\n"


def _index_body(symbols: list[str]) -> str:
    lines = [
        "# Python SDK Reference",
        "",
        "Generated from `fathom.__all__` at docs-build time via mkdocstrings.",
        "",
        "## Public symbols",
        "",
    ]
    lines.extend(f"- [`{s}`]({s.lower()}.md)" for s in symbols)
    lines.append("")
    return "\n".join(lines)


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear previous run so deleted symbols don't leave orphan pages
    for child in out_dir.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            # No nested dirs expected; be tolerant
            for sub in child.rglob("*"):
                if sub.is_file():
                    sub.unlink()
            child.rmdir()
        else:
            child.unlink()

    symbols = [s for s in fathom.__all__ if not s.startswith("_")]
    for name in symbols:
        (out_dir / f"{name.lower()}.md").write_text(_stub_body(name), encoding="utf-8")
    (out_dir / "index.md").write_text(_index_body(symbols), encoding="utf-8")

    print(f"wrote {len(symbols) + 1} Python SDK stubs under {out_dir}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
uv run pytest tests/test_scripts/test_python_sdk_docs.py -v
```

Expected: PASS.

- [ ] **Step 5: Real-repo run**

Run:
```bash
uv run python scripts/generate_python_sdk_docs.py
ls docs/reference/python-sdk/
```

Expected: `index.md` + one stub per non-dunder entry in `fathom.__all__` (currently 7: `engine.md`, `compilationerror.md`, `evaluationerror.md`, `validationerror.md`, `assertspec.md`, `assertedfact.md`, `evaluationresult.md`). 8 total files.

- [ ] **Step 6: Verify mkdocs build still succeeds**

Run:
```bash
uv run mkdocs build --strict
```

Expected: exit 0. mkdocstrings expands the `:::` directives without error. If build warns about missing docstrings, that is the `check_docstrings.py` gate's job in Wave 0 — not this task's concern.

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_python_sdk_docs.py tests/test_scripts/test_python_sdk_docs.py docs/reference/python-sdk/
git commit -m "feat(docs): generate Python SDK stubs via mkdocstrings directives"
```

---

## Task 3: SDK coverage gate

**Files:**
- Create: `scripts/check_sdk_coverage.py`
- Create: `tests/test_scripts/test_sdk_coverage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scripts/test_sdk_coverage.py`:

```python
import subprocess
import sys
from pathlib import Path


def test_coverage_passes_against_real_generated_tree() -> None:
    # Generate first to ensure tree exists
    subprocess.run(
        [sys.executable, "scripts/generate_python_sdk_docs.py"],
        check=True,
    )
    result = subprocess.run(
        [sys.executable, "scripts/check_sdk_coverage.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"SDK coverage failed:\n{result.stdout}\n{result.stderr}"


def test_coverage_fails_when_page_missing(tmp_path: Path) -> None:
    # Point the checker at an empty directory via env override
    import os

    env = os.environ.copy()
    env["FATHOM_SDK_DOCS_DIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "scripts/check_sdk_coverage.py"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode != 0, "expected failure when docs dir is empty"
    assert "Engine" in result.stdout + result.stderr
```

- [ ] **Step 2: Run tests to verify failure**

Run:
```bash
uv run pytest tests/test_scripts/test_sdk_coverage.py -v
```

Expected: FAIL with "No such file or directory: 'scripts/check_sdk_coverage.py'".

- [ ] **Step 3: Implement the checker**

Create `scripts/check_sdk_coverage.py`:

```python
"""Fail if any symbol in fathom.__all__ has no corresponding generated page.

Reads the concatenated Markdown under docs/reference/python-sdk/ (or
$FATHOM_SDK_DOCS_DIR) and greps for each public symbol name.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import fathom

DEFAULT_DIR = Path("docs/reference/python-sdk")


def main() -> int:
    base = Path(os.environ.get("FATHOM_SDK_DOCS_DIR", str(DEFAULT_DIR)))
    if not base.exists():
        print(f"fail: docs dir does not exist: {base}")
        return 1

    corpus = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in base.rglob("*.md")
    )

    missing: list[str] = []
    for symbol in fathom.__all__:
        if symbol.startswith("_"):
            continue
        if symbol not in corpus:
            missing.append(symbol)

    if missing:
        print(f"fail: {len(missing)} public symbol(s) missing from generated docs:")
        for name in missing:
            print(f"  - {name}")
        return 1

    print(f"ok: all {len(fathom.__all__)} public symbols present in generated docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify pass**

Run:
```bash
uv run pytest tests/test_scripts/test_sdk_coverage.py -v
```

Expected: PASS (both tests).

- [ ] **Step 5: Real-repo run**

Run:
```bash
uv run python scripts/check_sdk_coverage.py
```

Expected: `ok: all 8 public symbols present in generated docs`.

- [ ] **Step 6: Commit**

```bash
git add scripts/check_sdk_coverage.py tests/test_scripts/test_sdk_coverage.py
git commit -m "feat(docs): add SDK coverage gate for fathom.__all__"
```

---

## Task 4: Real rule-pack documentation generator

**Files:**
- Modify: `scripts/generate_rule_pack_docs.py` (replace stub)
- Create: `tests/test_scripts/test_rule_pack_docs_real.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scripts/test_rule_pack_docs_real.py`:

```python
import json
import subprocess
import sys
from pathlib import Path


def test_rule_pack_generator_emits_per_pack_pages(tmp_path: Path) -> None:
    out = tmp_path / "rule-packs"
    result = subprocess.run(
        [sys.executable, "scripts/generate_rule_pack_docs.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    expected = {"owasp-agentic.md", "nist-800-53.md", "hipaa.md", "cmmc.md"}
    actual = {p.name for p in out.glob("*.md")}
    assert expected.issubset(actual), f"missing: {expected - actual}"

    catalog = json.loads((out / "rule-packs.json").read_text(encoding="utf-8"))
    assert isinstance(catalog, list) and len(catalog) >= 4
    ids = {entry["id"] for entry in catalog}
    assert {"owasp-agentic", "nist-800-53", "hipaa", "cmmc"}.issubset(ids)

    owasp = (out / "owasp-agentic.md").read_text(encoding="utf-8")
    assert "detect-prompt-injection" in owasp
    assert "salience" in owasp.lower()
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv run pytest tests/test_scripts/test_rule_pack_docs_real.py -v
```

Expected: FAIL (current stub writes a single `index.md`, not per-pack pages).

- [ ] **Step 3: Replace the stub with the real generator**

Overwrite `scripts/generate_rule_pack_docs.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run:
```bash
uv run pytest tests/test_scripts/test_rule_pack_docs_real.py -v
```

Expected: PASS.

- [ ] **Step 5: Real-repo run**

```bash
uv run python scripts/generate_rule_pack_docs.py
ls docs/reference/rule-packs/
cat docs/reference/rule-packs/rule-packs.json | head -30
```

Expected: 4 `.md` pages + `rule-packs.json` with 4 entries.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_rule_pack_docs.py tests/test_scripts/test_rule_pack_docs_real.py docs/reference/rule-packs/
git commit -m "feat(docs): generate per-pack rule reference + catalog"
```

---

## Task 5: Real MCP manifest + per-tool pages

**Files:**
- Modify: `scripts/generate_mcp_manifest.py` (replace stub)
- Create: `tests/test_scripts/test_mcp_manifest_real.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scripts/test_mcp_manifest_real.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv run pytest tests/test_scripts/test_mcp_manifest_real.py -v
```

Expected: FAIL (current stub writes empty tools array).

- [ ] **Step 3: Replace the stub**

Overwrite `scripts/generate_mcp_manifest.py`:

```python
"""Introspect FathomMCPServer and emit manifest.json + per-tool Markdown pages."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_OUT = Path("docs/reference/mcp")


def _collect_tools() -> list[dict[str, Any]]:
    # Import lazily so the script doesn't require the MCP extra to be present
    # when only running other generators.
    from fathom.integrations.mcp_server import FathomMCPServer

    server = FathomMCPServer()
    # The MCP SDK exposes registered tools via the underlying server's
    # _tool_manager.list_tools(). Fall back to the ``_tools`` attribute if
    # the attribute tree changes across MCP SDK versions.
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
```

- [ ] **Step 4: Run to verify pass**

Run:
```bash
uv run pytest tests/test_scripts/test_mcp_manifest_real.py -v
```

Expected: PASS. If it fails because `FathomMCPServer` cannot be instantiated without the MCP extra, install it:

```bash
uv sync --extra mcp --extra docs --extra server
```

…and re-run. If the attribute path `_mcp._tool_manager.list_tools()` is not present in this MCP SDK version, report BLOCKED with the actual attribute tree found via `dir(FathomMCPServer())`; the controller will update the attribute path before re-dispatching.

- [ ] **Step 5: Real-repo run**

```bash
uv run python scripts/generate_mcp_manifest.py
ls docs/reference/mcp/
```

Expected: `manifest.json`, `index.md`, and 4 per-tool `.md` files.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_mcp_manifest.py tests/test_scripts/test_mcp_manifest_real.py docs/reference/mcp/
git commit -m "feat(docs): generate real MCP manifest + per-tool pages"
```

---

## Task 6: Real CLI reference generator

**Files:**
- Modify: `scripts/generate_cli_docs.py` (replace stub)
- Create: `tests/test_scripts/test_cli_docs_real.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scripts/test_cli_docs_real.py`:

```python
import subprocess
import sys
from pathlib import Path


def test_cli_docs_generator_emits_per_command_pages(tmp_path: Path) -> None:
    out = tmp_path / "cli"
    result = subprocess.run(
        [sys.executable, "scripts/generate_cli_docs.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    expected = {"validate.md", "compile.md", "info.md", "test.md", "bench.md", "repl.md"}
    actual = {p.name for p in out.glob("*.md")}
    assert expected.issubset(actual), f"missing: {expected - actual}"

    validate = (out / "validate.md").read_text(encoding="utf-8")
    assert "fathom validate" in validate.lower()
    assert "Usage" in validate or "usage" in validate
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv run pytest tests/test_scripts/test_cli_docs_real.py -v
```

Expected: FAIL (stub writes only `index.md`).

- [ ] **Step 3: Replace the stub**

Overwrite `scripts/generate_cli_docs.py`:

```python
"""Generate per-command CLI reference by invoking `fathom <cmd> --help`.

One Markdown page per Typer @app.command() in fathom.cli.app.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Pin terminal width BEFORE Typer/Rich imports. Rich reads COLUMNS at Console
# construction time; without this the drift gate fails on any machine whose
# terminal differs from CI's default width.
os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("TERMINAL_WIDTH", "100")

DEFAULT_OUT = Path("docs/reference/cli")


def _help_for(command_name: str | None) -> str:
    # Render Typer help without ANSI styles via Typer's CliRunner.
    from typer.testing import CliRunner

    from fathom.cli import app

    runner = CliRunner()
    args = [command_name, "--help"] if command_name else ["--help"]
    result = runner.invoke(app, args)
    if result.exit_code != 0:
        raise RuntimeError(
            f"fathom {command_name} --help failed "
            f"(exit {result.exit_code}): {result.output}"
        )
    return result.output


def _page(command_name: str, help_text: str) -> str:
    return "\n".join(
        [
            "---",
            f"title: fathom {command_name}",
            f"summary: CLI reference for `fathom {command_name}`",
            "audience: [app-developers, rule-authors]",
            "diataxis: reference",
            "status: stable",
            "last_verified: 2026-04-15",
            "---",
            "",
            f"# `fathom {command_name}`",
            "",
            "```",
            help_text.rstrip(),
            "```",
            "",
        ]
    )


def _index(commands: list[str]) -> str:
    lines = [
        "---",
        "title: CLI Reference",
        "summary: Index of `fathom` CLI commands",
        "audience: [app-developers, rule-authors]",
        "diataxis: reference",
        "status: stable",
        "last_verified: 2026-04-15",
        "---",
        "",
        "# CLI Reference",
        "",
        "| Command | |",
        "|---|---|",
    ]
    for cmd in commands:
        lines.append(f"| [`fathom {cmd}`]({cmd}.md) | |")
    lines.append("")
    return "\n".join(lines)


def main(out_dir: Path) -> int:
    from fathom.cli import app

    out_dir.mkdir(parents=True, exist_ok=True)
    # Typer stores the explicit name on CommandInfo.name; when registered via a
    # bare @app.command() decorator, that is None and the CLI name is derived
    # from the callback's __name__. Our six commands are single-word functions,
    # so __name__ matches the Typer-rendered command name.
    commands = sorted(
        (cmd.name or (cmd.callback.__name__ if cmd.callback else ""))
        for cmd in app.registered_commands
    )
    commands = [c for c in commands if c]

    for name in commands:
        help_text = _help_for(name)
        (out_dir / f"{name}.md").write_text(_page(name, help_text), encoding="utf-8", newline="\n")

    (out_dir / "index.md").write_text(_index(commands), encoding="utf-8", newline="\n")
    print(f"wrote CLI reference for {len(commands)} command(s) under {out_dir}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
```

- [ ] **Step 4: Run to verify pass**

Run:
```bash
uv run pytest tests/test_scripts/test_cli_docs_real.py -v
```

Expected: PASS.

- [ ] **Step 5: Real-repo run**

```bash
uv run python scripts/generate_cli_docs.py
ls docs/reference/cli/
```

Expected: `index.md` + 6 per-command pages (validate, compile, info, test, bench, repl).

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_cli_docs.py tests/test_scripts/test_cli_docs_real.py docs/reference/cli/
git commit -m "feat(docs): generate real CLI reference from Typer app"
```

---

## Task 7: REST reference — Redoc landing + Swagger UI try-it

**Files:**
- Create: `docs/reference/rest/index.md`
- Create: `docs/reference/rest/try.md`

- [ ] **Step 1: Write the landing page**

Create `docs/reference/rest/index.md`:

```markdown
---
title: REST API
summary: Fathom REST API reference, try-it console, and client exports
audience: [app-developers]
diataxis: reference
status: draft
last_verified: 2026-04-15
---

# REST API

Fathom exposes the engine over HTTP via FastAPI. The canonical schema is
exported at [`openapi.json`](openapi.json) and is regenerated on every
build.

## Quick links

- **Interactive try-it:** [Swagger UI](try.md)
- **Raw schema:** [`openapi.json`](openapi.json)
- **Postman collection:** exported during `make docs-gen` (see Task 8).
- **Insomnia:** use *Import from URL* pointed at `openapi.json`.

## Reference

<swagger-ui src="./openapi.json"/>
```

- [ ] **Step 2: Write the try-it page**

Create `docs/reference/rest/try.md`:

```markdown
---
title: REST API — Try It
summary: Interactive Swagger UI against the Fathom REST API
audience: [app-developers]
diataxis: reference
status: draft
last_verified: 2026-04-15
---

# Try It — REST API

<swagger-ui src="./openapi.json"/>
```

- [ ] **Step 3: Build and verify**

Run:
```bash
uv run mkdocs build --strict
```

Expected: zero warnings. Open `site/reference/rest/index.html` and confirm a Swagger UI block renders (locally this requires opening the built file; confirm via `grep 'swagger-ui' site/reference/rest/index.html`).

- [ ] **Step 4: Commit**

```bash
git add docs/reference/rest/index.md docs/reference/rest/try.md
git commit -m "docs(reference): add REST landing page with embedded Swagger UI"
```

---

## Task 8: Postman collection export

**Files:**
- Create: `scripts/generate_postman_collection.py`
- Create: `tests/test_scripts/test_postman.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scripts/test_postman.py`:

```python
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_postman_collection_generated(tmp_path: Path) -> None:
    if shutil.which("npx") is None:
        pytest.skip("npx not available on this environment")
    out = tmp_path / "fathom.postman_collection.json"
    result = subprocess.run(
        [sys.executable, "scripts/generate_postman_collection.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "info" in data
    assert "item" in data
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv run pytest tests/test_scripts/test_postman.py -v
```

Expected: FAIL or SKIP (if no npx). If SKIP, proceed — CI will have npx.

- [ ] **Step 3: Implement the script**

Create `scripts/generate_postman_collection.py`:

```python
"""Convert docs/reference/rest/openapi.json → Postman v2 collection via npx."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_IN = Path("docs/reference/rest/openapi.json")
DEFAULT_OUT = Path("docs/reference/rest/fathom.postman_collection.json")


def main(out_path: Path) -> int:
    if not DEFAULT_IN.exists():
        print(f"fail: {DEFAULT_IN} not found; run export_openapi.py first", file=sys.stderr)
        return 1
    if shutil.which("npx") is None:
        print("fail: npx not on PATH; install Node 18+ and re-run", file=sys.stderr)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "npx",
        "-y",
        "openapi-to-postmanv2@5",
        "-s",
        str(DEFAULT_IN),
        "-o",
        str(out_path),
        "-p",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
```

- [ ] **Step 4: Run to verify pass (or skip if npx absent)**

Run:
```bash
uv run pytest tests/test_scripts/test_postman.py -v
```

Expected: PASS if npx on PATH, otherwise SKIP.

- [ ] **Step 5: Real-repo run (only if npx available locally)**

```bash
uv run python scripts/generate_postman_collection.py
ls docs/reference/rest/
```

Expected: `fathom.postman_collection.json` created.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_postman_collection.py tests/test_scripts/test_postman.py docs/reference/rest/
git commit -m "feat(docs): export Postman collection from OpenAPI via npx"
```

---

## Task 9: gRPC reference via protoc-gen-doc

**Files:**
- Create: `scripts/generate_grpc_docs.py`
- Create: `docs/reference/grpc/index.md`
- Create: `tests/test_scripts/test_grpc_docs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scripts/test_grpc_docs.py`:

```python
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_grpc_docs_generated(tmp_path: Path) -> None:
    if shutil.which("protoc") is None:
        pytest.skip("protoc not available")
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
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv run pytest tests/test_scripts/test_grpc_docs.py -v
```

Expected: FAIL ("No such file or directory") or SKIP (no protoc locally).

- [ ] **Step 3: Implement the script**

Create `scripts/generate_grpc_docs.py`:

```python
"""Run protoc with protoc-gen-doc to emit Markdown reference for fathom.proto."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROTO = Path("protos/fathom.proto")
DEFAULT_OUT = Path("docs/reference/grpc")


def main(out_dir: Path) -> int:
    if not PROTO.exists():
        print(f"fail: {PROTO} not found", file=sys.stderr)
        return 1
    if shutil.which("protoc") is None:
        print("fail: protoc not on PATH", file=sys.stderr)
        return 1
    plugin_path = shutil.which("protoc-gen-doc")
    if plugin_path is None:
        print("fail: protoc-gen-doc not on PATH", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROTO, out_dir / "fathom.proto")

    cmd = [
        "protoc",
        f"--plugin=protoc-gen-doc={plugin_path}",
        f"--doc_out={out_dir}",
        "--doc_opt=markdown,fathom.md",
        f"-I{PROTO.parent}",
        str(PROTO),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode
    print(f"wrote {out_dir}/fathom.md and {out_dir}/fathom.proto")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
```

- [ ] **Step 4: Write the landing page**

Create `docs/reference/grpc/index.md`:

```markdown
---
title: gRPC API
summary: Fathom gRPC service reference, generated from protos/fathom.proto
audience: [app-developers]
diataxis: reference
status: generated
last_verified: auto
---

# gRPC API

Fathom's gRPC service is defined in
[`protos/fathom.proto`](https://github.com/KrakenNet/fathom/blob/master/protos/fathom.proto).

- **Generated reference:** [`fathom.md`](fathom.md)
- **Raw `.proto`:** [`fathom.proto`](fathom.proto)

The Go SDK's typed client wraps this service — see
[Go SDK reference](../go-sdk/index.md).
```

- [ ] **Step 5: Run to verify pass (or skip if protoc absent)**

Run:
```bash
uv run pytest tests/test_scripts/test_grpc_docs.py -v
```

Expected: PASS if `protoc` and `protoc-gen-doc` on PATH, else SKIP.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_grpc_docs.py tests/test_scripts/test_grpc_docs.py docs/reference/grpc/
git commit -m "feat(docs): generate gRPC reference via protoc-gen-doc"
```

---

## Task 10: Go SDK reference via gomarkdoc

**Files:**
- Create: `scripts/generate_go_sdk_docs.py`
- Create: `docs/reference/go-sdk/index.md`
- Create: `tests/test_scripts/test_go_sdk_docs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scripts/test_go_sdk_docs.py`:

```python
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_go_sdk_docs_generated(tmp_path: Path) -> None:
    if shutil.which("go") is None:
        pytest.skip("go not available")
    out = tmp_path / "go-sdk"
    result = subprocess.run(
        [sys.executable, "scripts/generate_go_sdk_docs.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    md = (out / "fathom-go.md").read_text(encoding="utf-8")
    # gomarkdoc includes the package name at the top
    assert "package" in md.lower()
```

- [ ] **Step 2: Implement the script**

Create `scripts/generate_go_sdk_docs.py`:

```python
"""Run gomarkdoc over packages/fathom-go to emit Markdown reference."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

GO_PKG = Path("packages/fathom-go")
DEFAULT_OUT = Path("docs/reference/go-sdk")


def main(out_dir: Path) -> int:
    if shutil.which("go") is None:
        print("fail: go not on PATH", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "fathom-go.md"

    # Install gomarkdoc into a module-local bin so we don't pollute GOPATH.
    env = os.environ.copy()
    install = subprocess.run(
        ["go", "install", "github.com/princjef/gomarkdoc/cmd/gomarkdoc@latest"],
        cwd=GO_PKG,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if install.returncode != 0:
        sys.stderr.write(install.stdout + install.stderr)
        return install.returncode

    gobin = os.environ.get("GOBIN") or str(Path.home() / "go" / "bin")
    gomarkdoc = shutil.which("gomarkdoc") or str(Path(gobin) / "gomarkdoc")
    if not Path(gomarkdoc).exists():
        print(f"fail: gomarkdoc not found at {gomarkdoc}", file=sys.stderr)
        return 1

    cmd = [gomarkdoc, "--output", str(out_file.resolve()), "./..."]
    result = subprocess.run(cmd, cwd=GO_PKG, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode
    print(f"wrote {out_file}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
```

- [ ] **Step 3: Write the landing page**

Create `docs/reference/go-sdk/index.md`:

```markdown
---
title: Go SDK
summary: Fathom Go client reference (generated from godoc via gomarkdoc)
audience: [app-developers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# Go SDK

Module path: `github.com/KrakenNet/fathom-go`

- **Generated reference:** [`fathom-go.md`](fathom-go.md)
- **Source:** [`packages/fathom-go`](https://github.com/KrakenNet/fathom/tree/master/packages/fathom-go)
- **pkg.go.dev:** [pkg.go.dev/github.com/KrakenNet/fathom-go](https://pkg.go.dev/github.com/KrakenNet/fathom-go)
```

- [ ] **Step 4: Run to verify**

Run:
```bash
uv run pytest tests/test_scripts/test_go_sdk_docs.py -v
```

Expected: PASS if `go` on PATH (installs gomarkdoc), else SKIP.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_go_sdk_docs.py tests/test_scripts/test_go_sdk_docs.py docs/reference/go-sdk/
git commit -m "feat(docs): generate Go SDK reference via gomarkdoc"
```

---

## Task 11: TypeScript SDK reference via typedoc

**Files:**
- Create: `scripts/generate_ts_sdk_docs.py`
- Modify: `packages/fathom-ts/package.json` — add `docs` script
- Create: `docs/reference/typescript-sdk/index.md`
- Create: `tests/test_scripts/test_ts_sdk_docs.py`

- [ ] **Step 1: Add `docs` script and devDeps to packages/fathom-ts/package.json**

Add to `scripts`:

```json
    "docs": "typedoc --plugin typedoc-plugin-markdown --out ../../docs/reference/typescript-sdk src/index.ts"
```

Add to `devDependencies`:

```json
    "typedoc": "^0.26",
    "typedoc-plugin-markdown": "^4"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_scripts/test_ts_sdk_docs.py`:

```python
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_ts_sdk_docs_generated(tmp_path: Path) -> None:
    if shutil.which("pnpm") is None and shutil.which("npm") is None:
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
```

- [ ] **Step 3: Implement the script**

Create `scripts/generate_ts_sdk_docs.py`:

```python
"""Run typedoc via pnpm (preferred) or npm to emit TS SDK reference Markdown."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

TS_PKG = Path("packages/fathom-ts")
DEFAULT_OUT = Path("docs/reference/typescript-sdk")


def main(out_dir: Path) -> int:
    tool = "pnpm" if shutil.which("pnpm") else ("npm" if shutil.which("npm") else None)
    if tool is None:
        print("fail: neither pnpm nor npm on PATH", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    install_args = ["install", "--ignore-scripts"] if tool == "pnpm" else ["install", "--no-audit"]
    install = subprocess.run(
        [tool, *install_args], cwd=TS_PKG, capture_output=True, text=True, check=False
    )
    if install.returncode != 0:
        sys.stderr.write(install.stdout + install.stderr)
        return install.returncode

    run_args = ["run", "docs"]
    result = subprocess.run(
        [tool, *run_args], cwd=TS_PKG, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    # `pnpm run docs` writes to ../../docs/reference/typescript-sdk by default.
    # If caller passed a different out_dir, copy the produced tree over.
    produced = Path("docs/reference/typescript-sdk")
    if produced.resolve() != out_dir.resolve():
        for p in produced.rglob("*"):
            if p.is_file():
                rel = p.relative_to(produced)
                tgt = out_dir / rel
                tgt.parent.mkdir(parents=True, exist_ok=True)
                tgt.write_bytes(p.read_bytes())
    print(f"wrote TS SDK docs under {out_dir}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
```

- [ ] **Step 4: Write the landing page**

Create `docs/reference/typescript-sdk/index.md`:

```markdown
---
title: TypeScript SDK
summary: Fathom TS client reference (generated from TSDoc via typedoc)
audience: [app-developers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# TypeScript SDK

Package path: `packages/fathom-ts`

- **Generated reference:** see module pages alongside this index.
- **Source:** [`packages/fathom-ts/src`](https://github.com/KrakenNet/fathom/tree/master/packages/fathom-ts/src)
```

- [ ] **Step 5: Run to verify**

Run:
```bash
uv run pytest tests/test_scripts/test_ts_sdk_docs.py -v
```

Expected: PASS if pnpm/npm on PATH and devDeps install, else SKIP.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_ts_sdk_docs.py tests/test_scripts/test_ts_sdk_docs.py packages/fathom-ts/package.json docs/reference/typescript-sdk/
git commit -m "feat(docs): generate TypeScript SDK reference via typedoc"
```

---

## Task 12: VSCode snippets + JSON Schema landing

**Files:**
- Create: `docs/reference/tooling/vscode/fathom.code-snippets`
- Create: `docs/reference/tooling/vscode/index.md`
- Create: `docs/reference/yaml/index.md`

- [ ] **Step 1: Write `fathom.code-snippets`**

Create `docs/reference/tooling/vscode/fathom.code-snippets`:

```json
{
  "Fathom template": {
    "scope": "yaml",
    "prefix": "fathom-template",
    "body": [
      "templates:",
      "  - name: ${1:agent}",
      "    description: \"${2:An AI agent}\"",
      "    slots:",
      "      - name: ${3:id}",
      "        type: ${4|string,symbol,float|}",
      "        required: true"
    ],
    "description": "Fathom template skeleton"
  },
  "Fathom rule": {
    "scope": "yaml",
    "prefix": "fathom-rule",
    "body": [
      "rules:",
      "  - name: ${1:rule-name}",
      "    salience: ${2:100}",
      "    when:",
      "      - template: ${3:agent}",
      "        conditions:",
      "          - slot: ${4:id}",
      "            expression: \"${5:eq(alice)}\"",
      "    then:",
      "      action: ${6|allow,deny,escalate|}",
      "      reason: \"${7:reason}\""
    ],
    "description": "Fathom rule skeleton"
  },
  "Fathom module": {
    "scope": "yaml",
    "prefix": "fathom-module",
    "body": [
      "modules:",
      "  - name: ${1:governance}",
      "    description: \"${2:Policy module}\"",
      "    priority: ${3:1}"
    ],
    "description": "Fathom module skeleton"
  },
  "Fathom function": {
    "scope": "yaml",
    "prefix": "fathom-function",
    "body": [
      "functions:",
      "  - name: ${1:fn-name}",
      "    params: [${2:x}]",
      "    body: \"${3:(+ ?x 1)}\""
    ],
    "description": "Fathom function skeleton"
  },
  "Fathom schema header": {
    "scope": "yaml",
    "prefix": "fathom-schema",
    "body": [
      "# yaml-language-server: $schema=https://fathom-rules.dev/reference/yaml/schemas/${1|rule,template,module,function|}.schema.json"
    ],
    "description": "Associate this file with a Fathom JSON Schema"
  }
}
```

- [ ] **Step 2: Write VSCode landing page**

Create `docs/reference/tooling/vscode/index.md`:

```markdown
---
title: VSCode Tooling
summary: Snippets and JSON Schema association for Fathom YAML files
audience: [rule-authors]
diataxis: reference
status: draft
last_verified: 2026-04-15
---

# VSCode Tooling

## Snippets

Download [`fathom.code-snippets`](fathom.code-snippets) and drop it
into `.vscode/` at your repo root. Available prefixes:

- `fathom-template` — template skeleton
- `fathom-rule` — rule skeleton
- `fathom-module` — module skeleton
- `fathom-function` — function skeleton
- `fathom-schema` — `yaml-language-server` schema association header

## JSON Schema association

Add to your workspace `.vscode/settings.json`:

```json
{
  "yaml.schemas": {
    "https://fathom-rules.dev/reference/yaml/schemas/rule.schema.json": "rules/*.yaml",
    "https://fathom-rules.dev/reference/yaml/schemas/template.schema.json": "templates/*.yaml",
    "https://fathom-rules.dev/reference/yaml/schemas/module.schema.json": "modules/*.yaml",
    "https://fathom-rules.dev/reference/yaml/schemas/function.schema.json": "functions/*.yaml"
  }
}
```

Or add the `yaml-language-server` header to the top of any YAML file:

```yaml
# yaml-language-server: $schema=https://fathom-rules.dev/reference/yaml/schemas/rule.schema.json
```
```

- [ ] **Step 3: Write the YAML reference landing**

Create `docs/reference/yaml/index.md`:

```markdown
---
title: YAML Reference
summary: JSON Schemas for Fathom YAML constructs
audience: [rule-authors]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# YAML Reference

Fathom's YAML authoring surface has one JSON Schema per construct.
Schemas are regenerated from `fathom.models` on every docs build.

## Downloads

| Construct | Schema |
|---|---|
| Template | [`template.schema.json`](schemas/template.schema.json) |
| Rule | [`rule.schema.json`](schemas/rule.schema.json) |
| Module | [`module.schema.json`](schemas/module.schema.json) |
| Function | [`function.schema.json`](schemas/function.schema.json) |
| Hierarchy | [`schemas/hierarchy.schema.json`](schemas/hierarchy.schema.json) |

See [VSCode tooling](../tooling/vscode/index.md) for editor setup.
```

- [ ] **Step 4: Verify strict build**

Run:
```bash
uv run mkdocs build --strict
```

Expected: zero warnings.

- [ ] **Step 5: Commit**

```bash
git add docs/reference/tooling/vscode/ docs/reference/yaml/index.md
git commit -m "docs(reference): add VSCode snippets and YAML schema landing"
```

---

## Task 13: Makefile orchestration

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Extend `docs-gen` and add `docs-gen-foreign`**

Replace the `docs-gen:` target in `Makefile` with:

```makefile
# Generators - native Python, run in every environment.
docs-gen:
	uv run python scripts/export_openapi.py
	uv run python scripts/export_json_schemas.py
	uv run python scripts/generate_cli_docs.py
	uv run python scripts/generate_rule_pack_docs.py
	uv run python scripts/generate_mcp_manifest.py
	uv run python scripts/changelog_to_json.py
	uv run python scripts/generate_llms_txt.py
	uv run python scripts/generate_python_sdk_docs.py

# Generators that require foreign toolchains (Go, Node, protoc). Run in CI
# unconditionally; locally they skip cleanly if the toolchain is missing.
docs-gen-foreign:
	uv run python scripts/generate_postman_collection.py || echo "skip: postman (npx missing)"
	uv run python scripts/generate_grpc_docs.py || echo "skip: grpc (protoc missing)"
	uv run python scripts/generate_go_sdk_docs.py || echo "skip: go-sdk (go missing)"
	uv run python scripts/generate_ts_sdk_docs.py || echo "skip: ts-sdk (pnpm/npm missing)"
```

- [ ] **Step 2: Verify `docs-gen` locally**

Run:
```bash
make docs-gen
git diff --stat -- docs/
```

Expected: Python SDK tree, rule-pack pages, MCP pages, CLI pages all updated; all other generators idempotent.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "build(docs): wire Wave 1 generators into Makefile"
```

---

## Task 14: mkdocs.yml nav flip + redirects

**Files:**
- Modify: `mkdocs.yml`

- [ ] **Step 1: Replace the API Reference / Integrations / Rule Packs nav sections**

In `mkdocs.yml`, replace the three nav blocks (`- Integrations:`, `- Rule Packs:`, `- API Reference:`) with one consolidated `- Reference:` block:

```yaml
  - Reference:
      - Overview: reference/index.md
      - Python SDK: reference/python-sdk/fathom.md
      - Go SDK: reference/go-sdk/index.md
      - TypeScript SDK: reference/typescript-sdk/index.md
      - REST API:
          - Overview: reference/rest/index.md
          - Try It: reference/rest/try.md
      - gRPC API: reference/grpc/index.md
      - MCP Tools: reference/mcp/index.md
      - YAML Schemas: reference/yaml/index.md
      - CLI: reference/cli/index.md
      - VSCode Tooling: reference/tooling/vscode/index.md
      - Rule Packs:
          - OWASP Agentic: reference/rule-packs/owasp-agentic.md
          - NIST 800-53: reference/rule-packs/nist-800-53.md
          - HIPAA: reference/rule-packs/hipaa.md
          - CMMC: reference/rule-packs/cmmc.md
```

- [ ] **Step 2: Populate `redirect_maps`**

Replace the empty `redirect_maps: {}` under the `redirects` plugin with:

```yaml
  - redirects:
      redirect_maps:
        api/engine.md: reference/python-sdk/fathom.md
        api/compiler.md: reference/python-sdk/fathom.md
        api/evaluator.md: reference/python-sdk/fathom.md
        api/facts.md: reference/python-sdk/fathom.md
        api/audit.md: reference/python-sdk/fathom.md
        api/attestation.md: reference/python-sdk/fathom.md
        integrations/cli.md: reference/cli/index.md
        integrations/go-sdk.md: reference/go-sdk/index.md
        integrations/typescript-sdk.md: reference/typescript-sdk/index.md
        integrations/mcp.md: reference/mcp/index.md
        rule-packs/owasp-agentic.md: reference/rule-packs/owasp-agentic.md
        rule-packs/nist-ai-rmf.md: reference/rule-packs/nist-800-53.md
        rule-packs/hipaa.md: reference/rule-packs/hipaa.md
        rule-packs/cmmc.md: reference/rule-packs/cmmc.md
```

- [ ] **Step 3: Create the Reference overview landing**

Create `docs/reference/index.md` — overwrite the existing placeholder:

```markdown
---
title: Reference
summary: Generated reference for every Fathom SDK, API, and tooling surface.
audience: [app-developers, rule-authors, contributors]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# Reference

Every public surface of Fathom is documented here. All pages under this tab
are generated from source — hand edits will be overwritten on next build.

## SDKs

- [Python SDK](python-sdk/fathom.md)
- [Go SDK](go-sdk/index.md)
- [TypeScript SDK](typescript-sdk/index.md)

## APIs

- [REST](rest/index.md) · [Try It](rest/try.md)
- [gRPC](grpc/index.md)
- [MCP Tools](mcp/index.md)

## YAML

- [Schemas](yaml/index.md)

## Tooling

- [CLI](cli/index.md)
- [VSCode snippets + schemas](tooling/vscode/index.md)

## Rule Packs

- [OWASP Agentic](rule-packs/owasp-agentic.md)
- [NIST 800-53](rule-packs/nist-800-53.md)
- [HIPAA](rule-packs/hipaa.md)
- [CMMC](rule-packs/cmmc.md)
```

- [ ] **Step 4: Run strict build**

Run:
```bash
make docs-gen
uv run mkdocs build --strict
```

Expected: zero warnings. If a redirect source points at a page still in nav, MkDocs warns — fix by removing the nav entry. If a target page doesn't exist yet, the generator for it hasn't run — re-run `make docs-gen`.

- [ ] **Step 5: Commit**

```bash
git add mkdocs.yml docs/reference/index.md
git commit -m "docs(nav): consolidate Wave 1 reference pages with redirects"
```

---

## Task 15: CI — install foreign toolchains and extend drift gate

**Files:**
- Modify: `.github/workflows/docs.yml`

- [ ] **Step 1: Add toolchain setup steps**

In `.github/workflows/docs.yml`, after the existing `Install uv` step, insert:

```yaml
      - name: Install Go
        uses: actions/setup-go@v5
        with:
          go-version: "1.22"

      - name: Install Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install pnpm
        uses: pnpm/action-setup@v4
        with:
          version: 9

      - name: Install protoc
        run: |
          sudo apt-get update
          sudo apt-get install -y protobuf-compiler
          go install github.com/pseudomuto/protoc-gen-doc/cmd/protoc-gen-doc@latest
          echo "$(go env GOPATH)/bin" >> "$GITHUB_PATH"
```

- [ ] **Step 2: Add a foreign-docs step**

After the existing `Generate docs artifacts` step, add:

```yaml
      - name: Generate foreign-toolchain docs
        run: make docs-gen-foreign
```

- [ ] **Step 3: Extend the drift gate paths**

Replace the `Drift gate` step body with:

```yaml
      - name: Drift gate
        run: |
          if ! git diff --exit-code \
              docs/reference \
              docs/llms.txt \
              docs/llms-full.txt \
              docs/changelog.json; then
            echo "::error::Generated docs artifacts are stale. Run 'make docs-gen && make docs-gen-foreign' and commit."
            exit 1
          fi
```

(The path list is unchanged in content — `docs/reference` covers all subtrees. This step just clarifies the hint.)

- [ ] **Step 4: Add coverage gate step**

After `Docstring coverage`, add:

```yaml
      - name: SDK coverage
        run: uv run python scripts/check_sdk_coverage.py
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "ci(docs): install Go/Node/protoc and run foreign-docs generators"
```

---

## Task 16: docs-deploy.yml via mike

**Files:**
- Create: `.github/workflows/docs-deploy.yml`

- [ ] **Step 1: Create the deploy workflow**

Create `.github/workflows/docs-deploy.yml`:

```yaml
name: docs-deploy

on:
  push:
    tags:
      - "v*.*.*"
  workflow_dispatch:
    inputs:
      version:
        description: "mike version alias (e.g. 0.3 or latest)"
        required: true
        default: "latest"

permissions:
  contents: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install uv
        uses: astral-sh/setup-uv@v3

      - name: Install Go
        uses: actions/setup-go@v5
        with:
          go-version: "1.22"

      - name: Install Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install pnpm
        uses: pnpm/action-setup@v4
        with:
          version: 9

      - name: Install protoc
        run: |
          sudo apt-get update
          sudo apt-get install -y protobuf-compiler
          go install github.com/pseudomuto/protoc-gen-doc/cmd/protoc-gen-doc@latest
          echo "$(go env GOPATH)/bin" >> "$GITHUB_PATH"

      - name: Install Python deps
        run: uv sync --extra docs --extra server --extra mcp

      - name: Generate everything
        run: |
          make docs-gen
          make docs-gen-foreign

      - name: Configure git for mike
        run: |
          git config user.name "docs-bot"
          git config user.email "docs-bot@users.noreply.github.com"

      - name: Resolve version label
        id: label
        run: |
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            echo "version=${{ inputs.version }}" >> "$GITHUB_OUTPUT"
            echo "alias=" >> "$GITHUB_OUTPUT"
          else
            TAG="${GITHUB_REF##refs/tags/}"
            VER="${TAG#v}"
            MM="$(echo "$VER" | awk -F. '{print $1"."$2}')"
            echo "version=${MM}" >> "$GITHUB_OUTPUT"
            echo "alias=latest" >> "$GITHUB_OUTPUT"
          fi

      - name: Deploy via mike
        run: |
          if [ -n "${{ steps.label.outputs.alias }}" ]; then
            uv run mike deploy --push --update-aliases \
              "${{ steps.label.outputs.version }}" "${{ steps.label.outputs.alias }}"
            uv run mike set-default --push "${{ steps.label.outputs.alias }}"
          else
            uv run mike deploy --push "${{ steps.label.outputs.version }}"
          fi
```

- [ ] **Step 2: Note required repo settings (do NOT automate)**

Add to the Wave 1 completion record (Task 17) that the user must:
- Enable GitHub Pages in repo settings, source = `gh-pages` branch root.
- Confirm branch protection allows `docs-bot` pushes (or adjust the workflow to use `gh pages` API / use `GITHUB_TOKEN` with writes).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/docs-deploy.yml
git commit -m "ci(docs): add tag-triggered mike deploy workflow"
```

---

## Task 17: Wave 1 completion record

**Files:**
- Create: `docs/superpowers/plans/2026-04-15-dev-docs-wave-1-reference-completion.md`

- [ ] **Step 1: Write the completion record**

Create `docs/superpowers/plans/2026-04-15-dev-docs-wave-1-reference-completion.md`:

```markdown
# Dev Docs — Wave 1 Completion

## Landed

- Python SDK reference via `pdoc` + `scripts/generate_python_sdk_docs.py`.
- `scripts/check_sdk_coverage.py` gate over `fathom.__all__`.
- Real `scripts/generate_rule_pack_docs.py` emitting per-pack pages + `rule-packs.json`.
- Real `scripts/generate_mcp_manifest.py` emitting `manifest.json` + per-tool pages.
- Real `scripts/generate_cli_docs.py` emitting per-Typer-command pages.
- REST landing + Swagger UI try-it (`mkdocs-swagger-ui-tag`).
- Postman collection export via `npx openapi-to-postmanv2`.
- gRPC reference via `protoc-gen-doc`.
- Go SDK reference via `gomarkdoc`.
- TypeScript SDK reference via `typedoc` + `typedoc-plugin-markdown`.
- VSCode snippets + YAML Schema landing page.
- `Makefile` split: `docs-gen` (Python-native) vs `docs-gen-foreign`.
- `mkdocs.yml`: consolidated Reference nav section; redirect_maps for old `api/*`, `integrations/*`, `rule-packs/*` URLs.
- `docs.yml` CI: installs Go, Node, pnpm, protoc; runs foreign-docs generators; SDK coverage gate.
- `docs-deploy.yml`: tag-triggered versioned deploy via `mike`.

## Deferred to Wave 2

- Rewrite of `docs/core/*`, `docs/integrations/*`, `docs/yaml/*` content into Diátaxis Explanation / How-to / Reference pages.
- Retirement of legacy page files from disk (Wave 1 only removes them from nav).
- Removal of the `docs/_prompts/**`, `docs/advanced/**`, `docs/core/**`, `docs/integration.md`, `docs/integrations/**`, `docs/yaml/**` exclusions from the markdownlint config.

## Open follow-ups

- **GitHub Pages setup** — repo owner must enable Pages (source = `gh-pages` branch) before `docs-deploy.yml` is useful.
- **`mkdocs-swagger-ui-tag` vs `mkdocs-material` native** — if Material releases first-party Swagger embed we can drop the plugin.
- **`CHANGELOG.md` format** — parser still expects bracketed form; migration is a Wave 2 content task.
- **m3** (silent slot-drop in `ConditionEntry`) — still pending its own issue.

## Verification

- `make docs-gen && make docs-gen-foreign` — generators all emit or skip cleanly.
- `uv run mkdocs build --strict` — zero warnings.
- `uv run pytest tests/test_scripts/` — all script tests pass.
- `uv run pytest` — full suite green.
- CI `docs` workflow — green on the push.
- `curl <deploy URL>/llms.txt` (after first tagged release triggers `docs-deploy.yml`) — returns llms.txt.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-15-dev-docs-wave-1-reference-completion.md
git commit -m "docs(plans): record Wave 1 completion and hand-offs to Wave 2"
```

- [ ] **Step 3: Final local verification**

Run:
```bash
make docs-gen
make docs-gen-foreign
uv run mkdocs build --strict
uv run pytest -q
git status
```

Expected:
- All generators emit (or cleanly skip foreign ones if local toolchains missing).
- Strict build passes.
- Full suite green.
- Working tree clean apart from the user's pre-existing uncommitted files.

- [ ] **Step 4: Push (after user confirms)**

Confirm with the user that CI is the right place for the first end-to-end run. Then:

```bash
git push origin HEAD
```

Expect the first CI run to surface whatever drifts between local and CI (same as Wave 0 did). Fix forward.

---

## Self-Review

**Spec coverage (design.md §3 + Wave 1 roadmap):**

- [x] Python SDK via pdoc — Task 2.
- [x] Coverage gate over `fathom.__all__` — Task 3.
- [x] Go SDK via gomarkdoc — Task 10.
- [x] TS SDK via typedoc — Task 11.
- [x] REST OpenAPI — already exported in Wave 0; Swagger UI landing — Task 7; Postman — Task 8.
- [x] gRPC via protoc-gen-doc — Task 9.
- [x] MCP manifest + per-tool pages — Task 5.
- [x] CLI via Typer introspection — Task 6.
- [x] Rule-pack catalog — Task 4.
- [x] JSON Schemas landing — Task 12 (schemas themselves already exported in Wave 0).
- [x] VSCode snippets — Task 12.
- [x] Redirects for `api/*`, `yaml/*`, `rule-packs/*`, `integrations/*` — Task 14.
- [x] FastAPI version binding — already landed in Wave 0 (confirmed via explorer agent).
- [x] Versioned deploy via mike — Task 16.

**Placeholder scan:** no "TBD", "implement later", "add validation". Each script step contains full implementation code. The two toolchain-dependent generators (Go, TS) fall back to SKIP in tests, matching Wave 0's npx-absent pattern.

**Type consistency:**
- `FathomMCPServer` attribute tree (`_mcp._tool_manager.list_tools()`) is version-dependent; Task 5 Step 4 explicitly flags this as the highest-risk BLOCKED path and asks the subagent to report actual attributes before the controller updates the path.
- `PACK_ID` mapping `nist_800_53 → nist-800-53` matches the catalog id used in `rule-packs.json` and in the mkdocs nav redirect (`rule-packs/nist-ai-rmf.md: reference/rule-packs/nist-800-53.md`).
- All scripts share the same pattern: positional `sys.argv[1]` = out path, default from module constant.
- `check_sdk_coverage.py` uses `FATHOM_SDK_DOCS_DIR` env override — same pattern as Wave 0's `check_docstrings.py` (if it had one); otherwise self-consistent.

**Scope check:** Wave 1 is intentionally large (17 tasks). The user explicitly chose single-plan over 1a/1b split. Tasks 2–12 are independent; Task 13–16 are sequential integration; Task 17 closes. Each task is TDD-shaped (test → fail → implement → pass → commit) and each produces a working, committable unit.

**Scaffolding reminders for the implementing subagents:**
- Each task has a `Real-repo run` step — run the generator against the real repo and eyeball one output file per generator. This is what caught the drift in Wave 0 CI run #1.
- After any task that writes to `docs/reference/**`, the drift gate will flag unrelated-looking differences in Wave 1 CI run #1 — same root cause as Wave 0: user's uncommitted `rest.py` changes. Handle by stashing, regenerating, committing, then unstashing (Wave 0's pattern).
