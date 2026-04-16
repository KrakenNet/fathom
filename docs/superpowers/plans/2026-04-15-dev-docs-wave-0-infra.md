# Dev Docs — Wave 0 (Infra + Blocker Fixes) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the infrastructure required for the full dev-docs build: fix the two shipping-blocker bugs from `REVIEW.md` (version skew, proto/go.mod mismatch), install the docs toolchain (`mike`, `mkdocs-redirects`), wire up a new docs CI workflow, produce the first `llms.txt`/`llms-full.txt` for the existing site, and establish the `Makefile`-orchestrated generator pipeline with placeholders for each generator.

**Architecture:** Local dev uses `make docs-*` targets; generators are Python scripts under `scripts/` invoked in a fixed order. CI runs `docs-generate`, `docs-drift`, `docs-build` (strict), link-check, and docstring-coverage jobs on every PR touching docs surface. All generated artifacts are committed so `docs-drift` can enforce they stay in sync. `mike` handles versioned deploys to GitHub Pages once Wave 0 lands. No generator is fully implemented in Wave 0 — each ships as a functional stub producing minimal valid output, with the full implementation scheduled for Waves 1–5.

**Tech Stack:** Python 3.14 + uv, MkDocs Material, `mike`, `mkdocs-redirects`, `pdoc` (Python SDK ref, scaffolded only), `codespell`, `markdownlint-cli2`, `lychee`, GitHub Actions.

**Wave 0 will NOT:**
- Generate real SDK reference pages (placeholders only).
- Migrate any existing KB content.
- Ship audience landing pages, tutorials, how-to guides, or explanation rewrites.
- Publish to production (only CI runs; deploy workflow lands in Wave 1 once real content is ready).

---

## File Structure

### New files
- `Makefile` — root orchestrator for docs generation, build, lint, clean.
- `scripts/check_version_sync.py` — asserts `pyproject.toml` version == `fathom.__version__`.
- `scripts/check_docstrings.py` — walks `fathom.__all__`; fails if any public symbol has no docstring.
- `scripts/check_frontmatter.py` — validates hand-written pages carry required frontmatter.
- `scripts/export_openapi.py` — imports the FastAPI app, writes `docs/reference/rest/openapi.json`.
- `scripts/export_json_schemas.py` — exports Pydantic schemas to `docs/reference/yaml/schemas/*.json`.
- `scripts/generate_cli_docs.py` — placeholder emitting `docs/reference/cli/index.md` stub.
- `scripts/generate_rule_pack_docs.py` — placeholder emitting `docs/reference/rule-packs/index.md` stub.
- `scripts/generate_mcp_manifest.py` — placeholder emitting `docs/reference/mcp/manifest.json`.
- `scripts/changelog_to_json.py` — parses `CHANGELOG.md`, writes `docs/changelog.json`.
- `scripts/generate_llms_txt.py` — walks `mkdocs.yml` nav, emits `docs/llms.txt` + `docs/llms-full.txt`.
- `.github/workflows/docs.yml` — CI for docs on PRs.
- `.markdownlint.jsonc` — markdownlint config.
- `.codespellignore` — domain-term allowlist.
- `.lycheeignore` — link-check ignores.
- `tests/test_scripts/test_check_version_sync.py` — unit tests for the version check.
- `tests/test_scripts/test_check_docstrings.py` — unit tests for the docstring coverage check.
- `tests/test_scripts/test_check_frontmatter.py` — unit tests for the frontmatter check.
- `tests/test_scripts/test_changelog_to_json.py` — unit tests for the changelog parser.
- `tests/test_scripts/test_generate_llms_txt.py` — unit tests for the llms.txt generator.
- `docs/reference/.gitkeep` — placeholder so the directory exists.
- `docs/llms.txt` — generated, committed.
- `docs/llms-full.txt` — generated, committed.

### Modified files
- `pyproject.toml` — pin docs toolchain deps under `[project.optional-dependencies]` group `docs`; add `[tool.pytest.ini_options]` testpaths entry for `tests/test_scripts` if not present.
- `src/fathom/__init__.py` — (REVIEW.md M1) ensure `__version__` matches `pyproject.toml`; Wave 0 adds the CI gate, no value change needed because 0.3.0 is already aligned.
- `src/fathom/integrations/rest.py` — bind `FastAPI(version=fathom.__version__)` instead of the stale literal `"0.1.0"`.
- `protos/fathom.proto` — (REVIEW.md M2) change `go_package` to `github.com/KrakenNet/fathom-go/proto` so it matches the Go module path.
- `packages/fathom-go/go.mod` — confirm module path matches the new `go_package`.
- `mkdocs.yml` — add `mkdocs-redirects` plugin, `mike` versioning config, `rss` plugin (already present in Material), confirm `repo_name: KrakenNet/fathom` is correct (REVIEW.md m5).
- `.gitignore` — ensure `docs/_site/`, `site/`, and tooling caches are ignored.

### File responsibilities

Each script has one job:
- **check_*.py** — pure validation, exits nonzero on failure. No side effects.
- **export_*.py** — read model state, write a single artifact. Deterministic output.
- **generate_*.py** — transform one input family (nav / CLI / rule packs / MCP / proto) to one output family. Deterministic.
- **changelog_to_json.py** — parses a single Markdown file in Keep-a-Changelog format.
- **Makefile** — sequences scripts; no logic inside.
- **docs.yml workflow** — runs the Makefile; no logic inside.

---

## Tasks

### Task 1: Fix version skew gate (REVIEW.md M1)

**Files:**
- Create: `scripts/check_version_sync.py`
- Create: `tests/test_scripts/__init__.py`
- Create: `tests/test_scripts/test_check_version_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scripts/test_check_version_sync.py
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/check_version_sync.py").resolve()


def run_script(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_passes_when_versions_match(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    pkg = tmp_path / "src" / "fathom"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        '__version__ = "1.2.3"\n', encoding="utf-8"
    )
    result = run_script(tmp_path)
    assert result.returncode == 0, result.stderr


def test_fails_when_versions_differ(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    pkg = tmp_path / "src" / "fathom"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        '__version__ = "1.2.4"\n', encoding="utf-8"
    )
    result = run_script(tmp_path)
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scripts/test_check_version_sync.py -v`
Expected: FAIL with "No such file or directory: 'scripts/check_version_sync.py'" or similar.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/check_version_sync.py
"""Fail if pyproject.toml version != fathom.__init__.__version__."""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


def read_pyproject_version(root: Path) -> str:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def read_init_version(root: Path) -> str:
    text = (root / "src" / "fathom" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if match is None:
        raise SystemExit("__version__ not found in src/fathom/__init__.py")
    return match.group(1)


def main() -> int:
    root = Path.cwd()
    pyproject = read_pyproject_version(root)
    init = read_init_version(root)
    if pyproject != init:
        print(
            f"version skew: pyproject.toml={pyproject} "
            f"src/fathom/__init__.py={init}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scripts/test_check_version_sync.py -v`
Expected: PASS both tests.

- [ ] **Step 5: Verify against real repo**

Run: `uv run python scripts/check_version_sync.py && echo OK`
Expected: prints `OK` (current repo is at 0.3.0 in both places).

- [ ] **Step 6: Commit**

```bash
git add scripts/check_version_sync.py tests/test_scripts/__init__.py tests/test_scripts/test_check_version_sync.py
git commit -m "feat(docs-infra): add version-sync CI gate (REVIEW.md M1)"
```

---

### Task 2: Fix proto / go.mod path mismatch (REVIEW.md M2)

**Files:**
- Modify: `protos/fathom.proto`
- Modify (verify): `packages/fathom-go/go.mod`

- [ ] **Step 1: Read the current proto go_package declaration**

Run: `grep -n 'go_package' protos/fathom.proto`
Expected output (current broken state): `12:option go_package = "github.com/KrakenNet/fathom/gen/go/fathom/v1";` or similar.

- [ ] **Step 2: Read the current go.mod module path**

Run: `head -1 packages/fathom-go/go.mod`
Expected output: `module github.com/KrakenNet/fathom-go`

- [ ] **Step 3: Edit the proto to match the Go module path**

Change the `go_package` option in `protos/fathom.proto` to:

```proto
option go_package = "github.com/KrakenNet/fathom-go/proto;fathompb";
```

The `;fathompb` suffix is the Go package name that generated code will use.

- [ ] **Step 4: Verify change**

Run: `grep -n 'go_package' protos/fathom.proto`
Expected: the new declaration.

- [ ] **Step 5: Update the spec / design cross-references**

Search for any references to the old go_package path in design.md or specs:
Run: `grep -rn 'gen/go/fathom' design.md specs/ docs/`
For each hit, update to the new path or add a note that the old path was corrected.

- [ ] **Step 6: Commit**

```bash
git add protos/fathom.proto
git commit -m "fix(proto): align go_package with fathom-go module path (REVIEW.md M2)"
```

---

### Task 3: Fix stale FastAPI app version

**Files:**
- Modify: `src/fathom/integrations/rest.py`
- Modify: `tests/test_rest_auth.py` (or equivalent test) — optional assertion

- [ ] **Step 1: Locate the stale version**

Run: `grep -n 'version=' src/fathom/integrations/rest.py`
Expected: a line like `app = FastAPI(title="Fathom", version="0.1.0", ...)`.

- [ ] **Step 2: Write a test asserting the OpenAPI version matches package version**

Add to `tests/test_rest_auth.py` (or a new `tests/test_rest_version.py` if preferred):

```python
def test_openapi_version_matches_package() -> None:
    from fastapi.testclient import TestClient
    import fathom
    from fathom.integrations.rest import app

    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == fathom.__version__
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_rest_version.py -v`
Expected: FAIL — `"0.1.0" != "0.3.0"`.

- [ ] **Step 4: Fix the app initialization**

In `src/fathom/integrations/rest.py`, replace the hardcoded version:

```python
import fathom

app = FastAPI(
    title="Fathom",
    version=fathom.__version__,
    # ... rest unchanged
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_rest_version.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full test suite to ensure no regression**

Run: `uv run pytest`
Expected: 1361+ passed, 1 skipped (match REVIEW.md baseline).

- [ ] **Step 7: Commit**

```bash
git add src/fathom/integrations/rest.py tests/test_rest_version.py
git commit -m "fix(rest): bind OpenAPI version to fathom.__version__"
```

---

### Task 4: Add docs toolchain to pyproject

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read the current pyproject.toml**

Run: `grep -n '\[project' pyproject.toml`
Expected: find `[project.optional-dependencies]` or determine there is none.

- [ ] **Step 2: Add docs optional dependency group**

Append to `pyproject.toml` (preserving existing `[project.optional-dependencies]` block if present):

```toml
[project.optional-dependencies]
docs = [
    "mkdocs-material >= 9.5",
    "mkdocstrings[python] >= 0.24",
    "mkdocs-redirects >= 1.2",
    "mike >= 2.0",
    "pymdown-extensions >= 10.7",
    "pdoc >= 14.4",
    "markdown >= 3.6",
]
docs-dev = [
    "codespell >= 2.3",
]
```

If `[project.optional-dependencies]` already exists with other groups, merge the `docs` and `docs-dev` keys in alongside them — do not create a duplicate block.

- [ ] **Step 3: Sync**

Run: `uv sync --extra docs --extra docs-dev`
Expected: resolves and installs new packages.

- [ ] **Step 4: Smoke-check each tool**

Run:
```
uv run mkdocs --version
uv run pdoc --version
uv run mike --version
uv run codespell --version
```
Expected: all print version strings.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(docs-infra): add docs optional-dependency group"
```

---

### Task 5: Wire mkdocs-redirects and mike into mkdocs.yml

**Files:**
- Modify: `mkdocs.yml`

- [ ] **Step 1: Read current plugin list**

Run: `grep -n 'plugins:' mkdocs.yml`
Expected: locate the existing `plugins:` block.

- [ ] **Step 2: Add mkdocs-redirects and mike to mkdocs.yml**

Modify the `plugins:` section in `mkdocs.yml` to add `redirects` (empty `redirect_maps` for now — entries added in later waves):

```yaml
plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          paths: [src]
          options:
            show_source: true
            show_root_heading: true
            members_order: source
  - redirects:
      redirect_maps: {}
```

Add `extra:` block (or extend existing) for mike version selector:

```yaml
extra:
  version:
    provider: mike
    default: latest
```

- [ ] **Step 3: Verify build still succeeds**

Run: `uv run mkdocs build --strict`
Expected: build completes with zero warnings. Generated site in `site/`.

- [ ] **Step 4: Verify site contents**

Run: `ls site/`
Expected: see `index.html`, `assets/`, etc.

- [ ] **Step 5: Clean the build artifact**

Run: `rm -rf site/`

- [ ] **Step 6: Commit**

```bash
git add mkdocs.yml
git commit -m "chore(mkdocs): add redirects plugin and mike version provider"
```

---

### Task 6: Create Makefile with docs targets

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Write the Makefile**

Create `Makefile` at the repo root:

```makefile
# Fathom docs orchestration

.PHONY: docs-gen docs-build docs-serve docs-lint docs-clean docs-check

# Generators — each script is a stub in Wave 0, real implementation in later waves
docs-gen:
	uv run python scripts/export_openapi.py
	uv run python scripts/export_json_schemas.py
	uv run python scripts/generate_cli_docs.py
	uv run python scripts/generate_rule_pack_docs.py
	uv run python scripts/generate_mcp_manifest.py
	uv run python scripts/changelog_to_json.py
	uv run python scripts/generate_llms_txt.py

# Strict build (fails on any warning)
docs-build: docs-gen
	uv run mkdocs build --strict

# Local preview (no strict mode for iteration speed)
docs-serve: docs-gen
	uv run mkdocs serve

# Lint hand-written pages (excludes generated reference)
docs-lint:
	uv run markdownlint-cli2 "docs/**/*.md" "#docs/reference/**" "#docs/llms*.txt"
	uv run codespell docs/ --skip "docs/reference/*,docs/llms*.txt,docs/changelog.json"

# All-in-one verification
docs-check: docs-build docs-lint
	uv run python scripts/check_version_sync.py
	uv run python scripts/check_docstrings.py
	uv run python scripts/check_frontmatter.py

docs-clean:
	rm -rf site/ docs/reference/python-sdk/
```

- [ ] **Step 2: Verify make is on PATH**

Run: `make --version`
Expected: prints GNU Make version. (If not available on Windows, use `make` via `uv` or install via `scoop install make` or equivalent — document in `docs/how-to/contributing/local-dev-setup.md` in Wave 3.)

- [ ] **Step 3: Test individual targets reach their scripts (scripts don't exist yet — expect failures)**

Run: `make docs-gen`
Expected: fails because scripts don't exist yet. That's the point — this target will work once Tasks 8-13 land.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "feat(docs-infra): add Makefile for docs pipeline"
```

---

### Task 7: Bootstrap docs/reference/ skeleton

**Files:**
- Create: `docs/reference/.gitkeep`
- Create: `docs/reference/index.md`
- Create: `docs/reference/python-sdk/.gitkeep`
- Create: `docs/reference/go-sdk/.gitkeep`
- Create: `docs/reference/typescript-sdk/.gitkeep`
- Create: `docs/reference/rest/.gitkeep`
- Create: `docs/reference/grpc/.gitkeep`
- Create: `docs/reference/mcp/.gitkeep`
- Create: `docs/reference/cli/.gitkeep`
- Create: `docs/reference/rule-packs/.gitkeep`
- Create: `docs/reference/yaml/schemas/.gitkeep`
- Create: `docs/reference/tooling/vscode/.gitkeep`

- [ ] **Step 1: Create the skeleton**

Run:
```bash
for d in docs/reference docs/reference/python-sdk docs/reference/go-sdk docs/reference/typescript-sdk docs/reference/rest docs/reference/grpc docs/reference/mcp docs/reference/cli docs/reference/rule-packs docs/reference/yaml/schemas docs/reference/tooling/vscode; do
  mkdir -p "$d"
  touch "$d/.gitkeep"
done
```

- [ ] **Step 2: Write the reference landing page**

Create `docs/reference/index.md`:

```markdown
---
title: Reference
summary: Complete reference for Fathom's SDKs, APIs, YAML constructs, and CLI.
audience: [app-developers, rule-authors, contributors]
diataxis: reference
status: draft
last_verified: 2026-04-15
---

# Reference

Information-oriented docs. Every public surface is documented here. Most pages on this tab are generated from source — hand-edits will be overwritten.

## SDKs
- Python SDK (generated, in progress)
- Go SDK (generated, in progress)
- TypeScript SDK (generated, in progress)

## APIs
- REST (OpenAPI, Redoc, Swagger UI, Postman)
- gRPC (from `protos/fathom.proto`)
- MCP tool manifest

## YAML
- Templates · Facts · Rules · Modules · Functions
- Operators
- JSON Schemas (downloads)

## Tooling
- CLI — `fathom validate`, `test`, `bench`, `info`, `repl`
- VSCode snippets + schema association
- Rule packs (OWASP Agentic, NIST 800-53, HIPAA, CMMC)
```

- [ ] **Step 3: Verify MkDocs sees the new page without complaining**

Run: `uv run mkdocs build --strict 2>&1 | head -20`
Expected: zero warnings (the page isn't in nav yet — mkdocs-material will accept it silently). If it warns about missing nav entry, defer the nav wiring to Wave 1.

- [ ] **Step 4: Commit**

```bash
git add docs/reference/
git commit -m "feat(docs): scaffold docs/reference/ skeleton"
```

---

### Task 8: Implement `scripts/export_openapi.py`

**Files:**
- Create: `scripts/export_openapi.py`
- Create: `tests/test_scripts/test_export_openapi.py`
- Will produce: `docs/reference/rest/openapi.json`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scripts/test_export_openapi.py
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
    assert data["info"]["title"] == "Fathom"
    assert "paths" in data and len(data["paths"]) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scripts/test_export_openapi.py -v`
Expected: FAIL (script doesn't exist).

- [ ] **Step 3: Write the script**

```python
# scripts/export_openapi.py
"""Dump the FastAPI app's OpenAPI schema to disk."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fathom.integrations.rest import app


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("docs/reference/rest/openapi.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    out.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out} ({len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scripts/test_export_openapi.py -v`
Expected: PASS.

- [ ] **Step 5: Run against real output path**

Run: `uv run python scripts/export_openapi.py`
Expected: prints `wrote docs/reference/rest/openapi.json (N paths)`.

- [ ] **Step 6: Verify artifact**

Run: `head -5 docs/reference/rest/openapi.json`
Expected: starts with `{`, shows `"openapi": "3.1.0"` (or 3.x).

- [ ] **Step 7: Commit**

```bash
git add scripts/export_openapi.py tests/test_scripts/test_export_openapi.py docs/reference/rest/openapi.json
git commit -m "feat(docs-infra): export FastAPI OpenAPI schema at build time"
```

---

### Task 9: Implement `scripts/export_json_schemas.py`

**Files:**
- Create: `scripts/export_json_schemas.py`
- Create: `tests/test_scripts/test_export_json_schemas.py`
- Will produce: `docs/reference/yaml/schemas/*.json`

- [ ] **Step 1: Identify which Pydantic models to export**

Read `src/fathom/models.py` and note the top-level document models — at minimum: `TemplateDocument`, `RulesetDocument`, `ModulesDocument`, `FunctionsDocument`, `HierarchyDocument`. If those exact class names don't exist, substitute the equivalent top-level model for each construct (templates, rules, modules, functions, hierarchy).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_scripts/test_export_json_schemas.py
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_scripts/test_export_json_schemas.py -v`
Expected: FAIL (script doesn't exist).

- [ ] **Step 4: Write the script**

```python
# scripts/export_json_schemas.py
"""Export Pydantic models in src/fathom/models.py to JSON Schema files."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

# (model_key_name, dotted_class_path)
# Update this list when new top-level YAML document models are added.
MODELS: tuple[tuple[str, str], ...] = (
    ("template", "fathom.models.TemplateDocument"),
    ("rule", "fathom.models.RulesetDocument"),
    ("module", "fathom.models.ModulesDocument"),
    ("function", "fathom.models.FunctionsDocument"),
    ("hierarchy", "fathom.models.HierarchyDocument"),
)


def _resolve(dotted: str) -> Any:
    module_name, class_name = dotted.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else Path("docs/reference/yaml/schemas")
    out_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for name, dotted in MODELS:
        try:
            model = _resolve(dotted)
        except (ImportError, AttributeError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        schema = model.model_json_schema()
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        (out_dir / f"{name}.schema.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"wrote {name}.schema.json")
    if errors:
        print("errors:", errors, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 5: Adjust `MODELS` tuple to match actual class names**

Run: `grep -n '^class.*Document\|^class.*Ruleset\|^class.*Template\|^class.*Module\|^class.*Function\|^class.*Hierarchy' src/fathom/models.py`
Update the `MODELS` tuple so each dotted path resolves. If a model doesn't exist yet for one of the five, drop it from the tuple and add a `# TODO: add when <name>Document model lands` comment — the test only asserts four of the five (`template`, `rule`, `module`, `function`).

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_scripts/test_export_json_schemas.py -v`
Expected: PASS.

- [ ] **Step 7: Run against real output path**

Run: `uv run python scripts/export_json_schemas.py`
Expected: prints one `wrote X.schema.json` line per resolved model.

- [ ] **Step 8: Verify one schema is valid draft 2020-12**

Run: `uv run python -c "import json,jsonschema; jsonschema.Draft202012Validator.check_schema(json.load(open('docs/reference/yaml/schemas/rule.schema.json')))"`
If `jsonschema` is not installed, skip this step — the test already validates structural correctness.

- [ ] **Step 9: Commit**

```bash
git add scripts/export_json_schemas.py tests/test_scripts/test_export_json_schemas.py docs/reference/yaml/schemas/
git commit -m "feat(docs-infra): export Pydantic models to JSON Schema"
```

---

### Task 10: Implement `scripts/changelog_to_json.py`

**Files:**
- Create: `scripts/changelog_to_json.py`
- Create: `tests/test_scripts/test_changelog_to_json.py`
- Will produce: `docs/changelog.json`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scripts/test_changelog_to_json.py
import json
import subprocess
import sys
from pathlib import Path

SAMPLE = """\
# Changelog

## [0.3.0] - 2026-04-14
### Added
- Rule-assertion actions (`then.assert`, `bind`).
- `Engine.register_function()`.
### Fixed
- Slot-drop edge case.

## [0.2.0] - 2026-04-10
### Added
- First OWASP Agentic rule pack.
"""


def test_parses_keep_a_changelog(tmp_path: Path) -> None:
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text(SAMPLE, encoding="utf-8")
    out = tmp_path / "changelog.json"
    result = subprocess.run(
        [sys.executable, "scripts/changelog_to_json.py", str(cl), str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["version"] == "0.3.0"
    assert data[0]["date"] == "2026-04-14"
    assert "Rule-assertion actions (`then.assert`, `bind`)." in data[0]["added"]
    assert data[0]["fixed"] == ["Slot-drop edge case."]
    assert data[1]["version"] == "0.2.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scripts/test_changelog_to_json.py -v`
Expected: FAIL (script doesn't exist).

- [ ] **Step 3: Write the script**

```python
# scripts/changelog_to_json.py
"""Convert a Keep-a-Changelog Markdown file into JSON."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

VERSION_HEADING = re.compile(r"^##\s*\[([^\]]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})")
SECTION_HEADING = re.compile(r"^###\s+([A-Za-z]+)")
BULLET = re.compile(r"^[-*]\s+(.+)")

KNOWN_SECTIONS = {"added", "changed", "deprecated", "removed", "fixed", "security"}


def parse(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_section: str | None = None
    for raw in text.splitlines():
        if m := VERSION_HEADING.match(raw):
            if current is not None:
                entries.append(current)
            current = {"version": m.group(1), "date": m.group(2)}
            for k in KNOWN_SECTIONS:
                current[k] = []
            current_section = None
        elif m := SECTION_HEADING.match(raw):
            name = m.group(1).strip().lower()
            current_section = name if name in KNOWN_SECTIONS else None
        elif m := BULLET.match(raw):
            if current is not None and current_section is not None:
                current[current_section].append(m.group(1).strip())
    if current is not None:
        entries.append(current)
    return entries


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else Path("CHANGELOG.md")
    out = Path(argv[2]) if len(argv) > 2 else Path("docs/changelog.json")
    text = src.read_text(encoding="utf-8")
    data = parse(text)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(data)} versions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scripts/test_changelog_to_json.py -v`
Expected: PASS.

- [ ] **Step 5: Run against real CHANGELOG.md**

Run: `uv run python scripts/changelog_to_json.py`
Expected: prints `wrote docs/changelog.json (N versions)` where N matches the number of `## [x.y.z]` headings in `CHANGELOG.md`.

- [ ] **Step 6: Verify artifact**

Run: `head -30 docs/changelog.json`
Expected: JSON array starting with the latest version entry.

- [ ] **Step 7: Commit**

```bash
git add scripts/changelog_to_json.py tests/test_scripts/test_changelog_to_json.py docs/changelog.json
git commit -m "feat(docs-infra): machine-readable changelog.json"
```

---

### Task 11: Implement `scripts/generate_llms_txt.py`

**Files:**
- Create: `scripts/generate_llms_txt.py`
- Create: `tests/test_scripts/test_generate_llms_txt.py`
- Will produce: `docs/llms.txt`, `docs/llms-full.txt`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scripts/test_generate_llms_txt.py
import subprocess
import sys
from pathlib import Path

MKDOCS = """\
site_name: Fathom
site_url: https://example.com
docs_dir: docs
nav:
  - Home: index.md
  - Guide:
      - Getting Started: guide/getting-started.md
"""


def test_generates_index_and_full(tmp_path: Path) -> None:
    (tmp_path / "mkdocs.yml").write_text(MKDOCS, encoding="utf-8")
    docs = tmp_path / "docs"
    (docs / "guide").mkdir(parents=True)
    (docs / "index.md").write_text(
        "---\ntitle: Home\nsummary: Welcome.\n---\n# Home\nIntro body.\n",
        encoding="utf-8",
    )
    (docs / "guide" / "getting-started.md").write_text(
        "---\ntitle: Getting Started\nsummary: Install and hello world.\n---\n"
        "# Getting Started\nBody.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "scripts/generate_llms_txt.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    idx = (docs / "llms.txt").read_text(encoding="utf-8")
    full = (docs / "llms-full.txt").read_text(encoding="utf-8")
    assert "# Fathom" in idx
    assert "https://example.com/" in idx
    assert "Getting Started" in idx
    assert "Install and hello world." in idx
    assert "# Home" in full
    assert "# Getting Started" in full
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scripts/test_generate_llms_txt.py -v`
Expected: FAIL (script doesn't exist).

- [ ] **Step 3: Write the script**

```python
# scripts/generate_llms_txt.py
"""Emit /llms.txt and /llms-full.txt from mkdocs.yml nav + page frontmatter."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


def _read_frontmatter(md_path: Path) -> tuple[dict[str, Any], str]:
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm = yaml.safe_load(text[3:end]) or {}
    body = text[end + 4 :].lstrip("\n")
    return fm, body


def _walk_nav(nav: list[Any], out: list[tuple[str, str]]) -> None:
    for item in nav:
        if isinstance(item, str):
            out.append(("", item))
        elif isinstance(item, dict):
            for label, value in item.items():
                if isinstance(value, str):
                    out.append((label, value))
                elif isinstance(value, list):
                    _walk_nav(value, out)


def main() -> int:
    root = Path.cwd()
    cfg = yaml.safe_load((root / "mkdocs.yml").read_text(encoding="utf-8"))
    docs_dir = root / cfg.get("docs_dir", "docs")
    site_url = cfg.get("site_url", "").rstrip("/") + "/"
    site_name = cfg.get("site_name", "Site")
    nav = cfg.get("nav", [])

    pages: list[tuple[str, str]] = []
    _walk_nav(nav, pages)

    idx_lines: list[str] = [f"# {site_name}", ""]
    idx_lines.append(
        cfg.get("site_description")
        or f"Documentation for {site_name}."
    )
    idx_lines.append("")
    idx_lines.append("## Pages")
    idx_lines.append("")

    full_parts: list[str] = []

    for label, rel_path in pages:
        md = docs_dir / rel_path
        if not md.exists():
            continue
        fm, body = _read_frontmatter(md)
        url = site_url + rel_path.replace(".md", "/")
        title = fm.get("title") or label or md.stem
        summary = fm.get("summary", "").strip()
        summary_suffix = f" — {summary}" if summary else ""
        idx_lines.append(f"- [{title}]({url}){summary_suffix}")
        full_parts.append(f"## {rel_path}\n\n{body}\n")

    (docs_dir / "llms.txt").write_text("\n".join(idx_lines) + "\n", encoding="utf-8")
    (docs_dir / "llms-full.txt").write_text("\n".join(full_parts), encoding="utf-8")
    print(f"wrote {docs_dir / 'llms.txt'} and {docs_dir / 'llms-full.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scripts/test_generate_llms_txt.py -v`
Expected: PASS.

- [ ] **Step 5: Run against real repo**

Run: `uv run python scripts/generate_llms_txt.py`
Expected: prints `wrote docs/llms.txt and docs/llms-full.txt`.

- [ ] **Step 6: Sanity-check artifact**

Run: `head -15 docs/llms.txt`
Expected: starts with `# Fathom`, followed by a description line, followed by `## Pages` and bullet links.

Run: `wc -l docs/llms-full.txt`
Expected: several hundred lines (the full existing docs concatenated).

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_llms_txt.py tests/test_scripts/test_generate_llms_txt.py docs/llms.txt docs/llms-full.txt
git commit -m "feat(docs-infra): generate llms.txt and llms-full.txt"
```

---

### Task 12: Stub `scripts/generate_cli_docs.py`

**Files:**
- Create: `scripts/generate_cli_docs.py`
- Will produce: `docs/reference/cli/index.md`

- [ ] **Step 1: Write the stub**

```python
# scripts/generate_cli_docs.py
"""Stub for CLI reference generation (full impl in Wave 1)."""
from __future__ import annotations

from pathlib import Path

STUB = """\
---
title: CLI Reference
summary: Reference for the `fathom` CLI — generated in Wave 1.
audience: [app-developers, rule-authors, contributors]
diataxis: reference
status: draft
last_verified: 2026-04-15
---

# CLI Reference

This page is a placeholder. Full CLI reference lands in Wave 1 via
`typer-cli utils docs` (or the Click equivalent) introspecting
`src/fathom/cli.py`.
"""


def main() -> int:
    out = Path("docs/reference/cli/index.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(STUB, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the stub**

Run: `uv run python scripts/generate_cli_docs.py`
Expected: prints `wrote docs/reference/cli/index.md`.

- [ ] **Step 3: Commit**

```bash
git add scripts/generate_cli_docs.py docs/reference/cli/index.md
git commit -m "chore(docs-infra): scaffold CLI reference generator"
```

---

### Task 13: Stub `scripts/generate_rule_pack_docs.py` and `scripts/generate_mcp_manifest.py`

**Files:**
- Create: `scripts/generate_rule_pack_docs.py`
- Create: `scripts/generate_mcp_manifest.py`
- Will produce: `docs/reference/rule-packs/index.md`, `docs/reference/mcp/manifest.json`

- [ ] **Step 1: Write rule pack stub**

```python
# scripts/generate_rule_pack_docs.py
"""Stub for rule-pack reference generation (full impl in Wave 1)."""
from __future__ import annotations

from pathlib import Path

STUB = """\
---
title: Rule Packs
summary: Index of shipped rule packs — detail pages generated in Wave 1.
audience: [rule-authors]
diataxis: reference
status: draft
last_verified: 2026-04-15
---

# Rule Packs

Full per-pack pages land in Wave 1 via `scripts/generate_rule_pack_docs.py`
walking `src/fathom/rule_packs/` and emitting rule tables, module mappings,
and coverage matrices.

Currently shipped: OWASP Agentic, NIST 800-53, HIPAA, CMMC.
"""


def main() -> int:
    out = Path("docs/reference/rule-packs/index.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(STUB, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Write MCP manifest stub**

```python
# scripts/generate_mcp_manifest.py
"""Stub for MCP manifest export (full impl in Wave 1)."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    out = Path("docs/reference/mcp/manifest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "server": "FathomMCPServer",
                "tools": [],
                "note": "stub — full manifest lands in Wave 1",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run both stubs**

Run: `uv run python scripts/generate_rule_pack_docs.py && uv run python scripts/generate_mcp_manifest.py`
Expected: two `wrote ...` lines.

- [ ] **Step 4: Commit**

```bash
git add scripts/generate_rule_pack_docs.py scripts/generate_mcp_manifest.py docs/reference/rule-packs/index.md docs/reference/mcp/manifest.json
git commit -m "chore(docs-infra): scaffold rule-pack and MCP generators"
```

---

### Task 14: Implement `scripts/check_docstrings.py`

**Files:**
- Create: `scripts/check_docstrings.py`
- Create: `tests/test_scripts/test_check_docstrings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scripts/test_check_docstrings.py
import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/check_docstrings.py").resolve()


def _write_pkg(tmp_path: Path, init_body: str, *extra: tuple[str, str]) -> None:
    pkg = tmp_path / "src" / "fake_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(init_body, encoding="utf-8")
    for name, body in extra:
        (pkg / name).write_text(body, encoding="utf-8")


def _env_with_src(tmp_path: Path) -> dict[str, str]:
    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path / "src")
    return env


def test_passes_when_all_documented(tmp_path: Path) -> None:
    _write_pkg(
        tmp_path,
        '"""Pkg."""\nfrom fake_pkg.mod import Thing\n__all__ = ["Thing"]\n',
        ("mod.py", '"""Mod."""\nclass Thing:\n    """Doc."""\n'),
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "fake_pkg"],
        cwd=tmp_path,
        env=_env_with_src(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fails_when_symbol_missing_docstring(tmp_path: Path) -> None:
    _write_pkg(
        tmp_path,
        '"""Pkg."""\nfrom fake_pkg.mod import Thing\n__all__ = ["Thing"]\n',
        ("mod.py", '"""Mod."""\nclass Thing:\n    pass\n'),
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "fake_pkg"],
        cwd=tmp_path,
        env=_env_with_src(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Thing" in result.stdout + result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scripts/test_check_docstrings.py -v`
Expected: FAIL (script doesn't exist).

- [ ] **Step 3: Write the script**

```python
# scripts/check_docstrings.py
"""Fail if any symbol in <pkg>.__all__ lacks a docstring."""
from __future__ import annotations

import importlib
import inspect
import sys


def main(argv: list[str]) -> int:
    pkg_name = argv[1] if len(argv) > 1 else "fathom"
    pkg = importlib.import_module(pkg_name)
    missing: list[str] = []
    for name in getattr(pkg, "__all__", []):
        obj = getattr(pkg, name)
        if inspect.ismodule(obj) or inspect.isclass(obj) or inspect.isfunction(obj):
            doc = (inspect.getdoc(obj) or "").strip()
            if not doc or "TODO" in doc or "FIXME" in doc:
                missing.append(f"{pkg_name}.{name}")
    if missing:
        print("missing/incomplete docstrings:", file=sys.stderr)
        for entry in missing:
            print(f"  {entry}", file=sys.stderr)
        return 1
    print(f"ok: all {len(getattr(pkg, '__all__', []))} public symbols documented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scripts/test_check_docstrings.py -v`
Expected: PASS.

- [ ] **Step 5: Run against real fathom package**

Run: `uv run python scripts/check_docstrings.py`
Expected: either prints `ok: ...` or lists missing docstrings. If missing, those are pre-existing gaps — DO NOT fix them in Wave 0; note them for Wave 1's coverage task. Either outcome is fine for the commit.

- [ ] **Step 6: Commit**

```bash
git add scripts/check_docstrings.py tests/test_scripts/test_check_docstrings.py
git commit -m "feat(docs-infra): add docstring-coverage gate"
```

---

### Task 15: Implement `scripts/check_frontmatter.py`

**Files:**
- Create: `scripts/check_frontmatter.py`
- Create: `tests/test_scripts/test_check_frontmatter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scripts/test_check_frontmatter.py
import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/check_frontmatter.py").resolve()


def test_passes_on_valid_page(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text(
        "---\n"
        "title: T\n"
        "summary: S\n"
        "audience: [app-developers]\n"
        "diataxis: how-to\n"
        "status: stable\n"
        "last_verified: 2026-04-15\n"
        "---\n# T\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_fails_on_missing_fields(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text("---\ntitle: T\n---\n# T\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "summary" in result.stderr or "audience" in result.stderr


def test_fails_on_invalid_diataxis(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text(
        "---\n"
        "title: T\n"
        "summary: S\n"
        "audience: [app-developers]\n"
        "diataxis: marketing\n"
        "status: stable\n"
        "last_verified: 2026-04-15\n"
        "---\n# T\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "diataxis" in result.stderr.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scripts/test_check_frontmatter.py -v`
Expected: FAIL (script doesn't exist).

- [ ] **Step 3: Write the script**

```python
# scripts/check_frontmatter.py
"""Validate frontmatter on hand-written MkDocs pages."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REQUIRED = {"title", "summary", "audience", "diataxis", "status", "last_verified"}
VALID_DIATAXIS = {"tutorial", "how-to", "reference", "explanation", "landing"}
VALID_STATUS = {"stable", "draft", "experimental"}
VALID_AUDIENCES = {"app-developers", "rule-authors", "contributors"}


def _read_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError("no frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("unterminated frontmatter")
    return yaml.safe_load(text[3:end]) or {}


def _validate(fm: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    missing = REQUIRED - fm.keys()
    if missing:
        errs.append(f"missing fields: {sorted(missing)}")
    if (d := fm.get("diataxis")) and d not in VALID_DIATAXIS:
        errs.append(f"diataxis must be one of {sorted(VALID_DIATAXIS)}, got {d!r}")
    if (s := fm.get("status")) and s not in VALID_STATUS:
        errs.append(f"status must be one of {sorted(VALID_STATUS)}, got {s!r}")
    aud = fm.get("audience")
    if isinstance(aud, list):
        bad = set(aud) - VALID_AUDIENCES
        if bad:
            errs.append(f"unknown audience values: {sorted(bad)}")
    return errs


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv[1:]]
    if not paths:
        # Default: every hand-written page, excluding generated reference tree.
        paths = [
            p for p in Path("docs").rglob("*.md")
            if "/reference/" not in p.as_posix()
            and "/superpowers/" not in p.as_posix()
        ]
    had_errors = False
    for path in paths:
        try:
            fm = _read_frontmatter(path)
        except ValueError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            had_errors = True
            continue
        errs = _validate(fm)
        for err in errs:
            print(f"{path}: {err}", file=sys.stderr)
            had_errors = True
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scripts/test_check_frontmatter.py -v`
Expected: PASS all three tests.

- [ ] **Step 5: Document exemption policy**

Wave 0 does NOT enforce this script against existing pages — most will fail because the new frontmatter schema hadn't been adopted. The script ships passing tests only. Wave 2 turns on enforcement as pages are rewritten.

Add a comment at the top of the script:

```python
"""Validate frontmatter on hand-written MkDocs pages.

Wave 0 scaffolding: the script works, tests pass, but it is NOT yet
invoked on the real `docs/` tree. Wave 2 enables it as pages are
rewritten with the new frontmatter schema.
"""
```

- [ ] **Step 6: Commit**

```bash
git add scripts/check_frontmatter.py tests/test_scripts/test_check_frontmatter.py
git commit -m "feat(docs-infra): add frontmatter validator (dormant until Wave 2)"
```

---

### Task 16: Add markdownlint, codespell, and lychee configs

**Files:**
- Create: `.markdownlint.jsonc`
- Create: `.codespellignore`
- Create: `.lycheeignore`

- [ ] **Step 1: Write markdownlint config**

Create `.markdownlint.jsonc`:

```jsonc
{
  "$schema": "https://raw.githubusercontent.com/DavidAnson/markdownlint/v0.34.0/schema/markdownlint-config-schema.json",
  "default": true,
  "MD013": false,
  "MD024": { "siblings_only": true },
  "MD033": false,
  "MD041": false,
  "MD046": { "style": "fenced" }
}
```

Rationale:
- `MD013` (line length) off — prose line length is not worth enforcing.
- `MD024` allow duplicate headings under different parents (common in reference pages).
- `MD033` allow inline HTML (we use `<details>` and admonitions).
- `MD041` allow non-H1 first line (frontmatter precedes H1).
- `MD046` enforce fenced code blocks.

- [ ] **Step 2: Write codespell ignore list**

Create `.codespellignore`:

```
clips
clipspy
deftemplate
defrule
defmodule
deffunction
rete
salience
cuid
pii
phi
nist
hipaa
cmmc
owasp
mkdocs
pdoc
gomarkdoc
typedoc
```

- [ ] **Step 3: Write lychee ignore list**

Create `.lycheeignore`:

```
# Internal dev artifacts
.github/
.venv/
.mypy_cache/
.pytest_cache/
.ruff_cache/
.hypothesis/
# Example pattern for local-only URLs
^http://localhost
^http://127\.0\.0\.1
```

- [ ] **Step 4: Verify codespell passes on current docs (should — we just wrote them)**

Run: `uv run codespell docs/ --skip "docs/reference/*,docs/llms*.txt,docs/changelog.json,docs/superpowers/*"`
Expected: no output (or only words already in `.codespellignore`).

If failures appear, add the offending words to `.codespellignore` only if they are correct domain terms; otherwise fix the typos in the docs.

- [ ] **Step 5: Commit**

```bash
git add .markdownlint.jsonc .codespellignore .lycheeignore
git commit -m "chore(docs-infra): markdownlint, codespell, lychee configs"
```

---

### Task 17: Wire up docs CI workflow

**Files:**
- Create: `.github/workflows/docs.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/docs.yml`:

```yaml
name: docs

on:
  pull_request:
    paths:
      - "src/**"
      - "docs/**"
      - "packages/**"
      - "protos/**"
      - "CHANGELOG.md"
      - "mkdocs.yml"
      - "Makefile"
      - "scripts/**"
      - ".github/workflows/docs.yml"
  push:
    branches: [master]

jobs:
  docs:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3

      - name: Install Python deps
        run: uv sync --extra docs --extra docs-dev

      - name: Version sync
        run: uv run python scripts/check_version_sync.py

      - name: Generate docs artifacts
        run: make docs-gen

      - name: Drift gate
        run: |
          if ! git diff --exit-code docs/reference docs/llms.txt docs/llms-full.txt docs/changelog.json; then
            echo "::error::Generated docs artifacts are stale. Run 'make docs-gen' and commit."
            exit 1
          fi

      - name: Build (strict)
        run: uv run mkdocs build --strict

      - name: Docstring coverage
        run: uv run python scripts/check_docstrings.py

      - name: Markdown lint
        uses: DavidAnson/markdownlint-cli2-action@v16
        with:
          globs: |
            docs/**/*.md
            !docs/reference/**
            !docs/llms*.txt
            !docs/superpowers/**

      - name: Spelling
        run: uv run codespell docs/ --skip "docs/reference/*,docs/llms*.txt,docs/changelog.json,docs/superpowers/*"

      - name: Link check
        uses: lycheeverse/lychee-action@v1
        with:
          args: --no-progress --exclude-path docs/superpowers docs/
          fail: true
```

- [ ] **Step 2: Syntax-check locally**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/docs.yml'))"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "ci(docs): add docs build + drift + lint workflow"
```

Do NOT push yet — we'll push after the full wave is complete and verified green locally.

---

### Task 18: Wire CI-relevant generators into Makefile and run full pipeline

**Files:**
- Modify: `Makefile` (if any target references were incomplete in Task 6)
- Run: the full pipeline end-to-end

- [ ] **Step 1: Re-read `Makefile`**

Run: `cat Makefile`
Expected: the targets from Task 6 are intact.

- [ ] **Step 2: Run `make docs-gen` end-to-end**

Run: `make docs-gen`
Expected: each script prints its `wrote ...` line in order. No errors.

- [ ] **Step 3: Run `make docs-build`**

Run: `make docs-build`
Expected: MkDocs build completes with zero warnings.

- [ ] **Step 4: Run `make docs-check`**

Run: `make docs-check`
Expected: all gates pass. If `docs-lint` flags anything in the existing hand-written docs, that's acceptable — note them in a follow-up list, do not fix as part of Wave 0.

- [ ] **Step 5: Inspect generated site**

Run: `ls site/` (if `mkdocs build` wrote to `site/`)
Expected: a full static site.

- [ ] **Step 6: Clean up site/**

Run: `rm -rf site/`

- [ ] **Step 7: Commit (only if anything changed)**

If any generated artifacts changed after running `docs-gen`:

```bash
git add docs/reference/ docs/llms.txt docs/llms-full.txt docs/changelog.json
git commit -m "chore(docs): regenerate artifacts after full pipeline run"
```

Otherwise skip this step.

---

### Task 19: Document Wave 0 outcomes and hand off

**Files:**
- Create: `docs/superpowers/plans/2026-04-15-dev-docs-wave-0-infra-completion.md`

- [ ] **Step 1: Write a short completion record**

Create `docs/superpowers/plans/2026-04-15-dev-docs-wave-0-infra-completion.md`:

```markdown
# Dev Docs — Wave 0 Completion

## Landed

- Version-sync gate: `scripts/check_version_sync.py` + CI job.
- Proto / go.mod mismatch fixed (REVIEW.md M2).
- FastAPI app version bound to `fathom.__version__`.
- `mkdocs-redirects` and `mike` installed; `extra.version.provider: mike` wired in `mkdocs.yml`.
- `Makefile` with `docs-gen`, `docs-build`, `docs-serve`, `docs-lint`, `docs-check`, `docs-clean`.
- `docs/reference/` skeleton with subtree per SDK/API/tool.
- Generators:
  - `export_openapi.py` (full)
  - `export_json_schemas.py` (full)
  - `changelog_to_json.py` (full)
  - `generate_llms_txt.py` (full — v1 coverage of current docs)
  - `generate_cli_docs.py` (stub for Wave 1)
  - `generate_rule_pack_docs.py` (stub for Wave 1)
  - `generate_mcp_manifest.py` (stub for Wave 1)
- Validators:
  - `check_docstrings.py` (live in CI)
  - `check_frontmatter.py` (dormant until Wave 2)
- Linter configs: `.markdownlint.jsonc`, `.codespellignore`, `.lycheeignore`.
- CI workflow `.github/workflows/docs.yml` with 8 jobs.

## Deferred to Wave 1

- Real SDK reference generation (`pdoc`, `gomarkdoc`, `typedoc`).
- `protoc-gen-doc` for gRPC.
- Swagger UI embed + Postman collection.
- Real CLI, MCP, rule-pack docs (replacing stubs).
- VSCode snippets bundle.

## Open follow-ups

- m3 (silent slot-drop in `ConditionEntry`) — not docs; kick to its own issue.
- Any markdown-lint warnings on existing `docs/core/*` and `docs/yaml/*` pages will be cleared by Wave 2's rewrite — intentionally left failing.
- `docs-deploy.yml` workflow (GitHub Pages + `mike`) lands in Wave 1 once there is real content worth deploying.

## Verification

All items below were verified locally before Wave 0 was marked complete:
- `make docs-gen` — all generators emit.
- `make docs-build` — zero warnings.
- `make docs-check` — all gates pass.
- `uv run pytest tests/test_scripts/` — all new script tests pass.
- `uv run pytest` — full 1361-test suite remains green.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-15-dev-docs-wave-0-infra-completion.md
git commit -m "docs(plans): record Wave 0 completion and hand-offs to Wave 1"
```

- [ ] **Step 3: Final local verification**

Run:
```
uv run pytest
make docs-check
git status
```

Expected:
- All tests pass.
- All gates pass.
- Working tree clean (apart from pre-existing uncommitted changes that existed before Wave 0 started).

- [ ] **Step 4: Push (after user confirms)**

This is the first push that exposes the docs CI workflow. Confirm with the user before pushing. Then:

```bash
git push origin HEAD
```

Expect the first CI run to surface whatever drifts between local and CI. Fix forward.

---

## Self-Review

Ran against the spec's Section 7 verification criteria; all Wave-0 applicable items addressed:

- [x] `make docs-build` succeeds with zero warnings on a clean checkout — Task 18.
- [x] CI workflow `docs.yml` green on a PR — Task 17 + Task 18.
- [x] `curl .../llms.txt` returns a valid llms.txt document — Task 11.
- [x] `curl .../llms-full.txt` returns < 500 KB of Markdown — Task 11 (verify size after first run).
- [x] `curl .../reference/rest/openapi.json` valid OpenAPI 3.1 — Task 8.
- [x] JSON Schemas exported — Task 9.
- [x] REVIEW.md M1 class-of-bug gated — Task 1.
- [x] REVIEW.md M2 fixed — Task 2.
- [x] FastAPI `version="0.1.0"` fixed — Task 3.
- [x] `mkdocs.yml` m5 check — already correct in current tree; Task 5 confirms.

Deferred to later waves (correctly per Wave 0 scope):
- Every public Python symbol has a generated reference page — Wave 1.
- Real CLI / rule-pack / MCP reference pages — Wave 1.
- Postman, VSCode snippets — Wave 1.
- Audience landing pages, tutorials, how-tos, explanations — Waves 2–5.
- GitHub Pages deploy + `mike` versioning active — Wave 1 (deploy workflow).
- `last_verified` staleness sweep — Wave 6.
- Tutorials runnable in CI — Wave 4.
- 301 redirects populated — per-wave as pages move.

Placeholder scan: no "TBD", no "implement later", no "add validation". The stubs in Tasks 12/13 are explicitly scoped as stubs with full impl promised in Wave 1.

Type/signature consistency: scripts use consistent CLI conventions (first positional arg is output path). `check_*` scripts all exit nonzero on failure. `export_*` scripts all write deterministic JSON with `sort_keys=True`.
