# Dev Docs — Wave 0 Completion

## Landed

- Version-sync gate: `scripts/check_version_sync.py` + CI job.
- Proto / go.mod mismatch fixed (REVIEW.md M2). Suffix kept as `fathomv1` (matches proto package `fathom.v1` and committed docs); plan's suggested `fathompb` was not adopted.
- FastAPI `app` version bound to `fathom.__version__` (REVIEW.md M1).
- `mkdocs-redirects` and `mike` added to `[project.optional-dependencies].docs`; `extra.version.provider: mike` wired in `mkdocs.yml`; `repo_name` corrected to `KrakenNet/fathom` (REVIEW.md m5).
- `Makefile` with `docs-gen`, `docs-build`, `docs-serve`, `docs-lint`, `docs-check`, `docs-clean`.
- `docs/reference/` skeleton with subtree per SDK/API/tool (`.gitkeep` + `index.md` placeholders).
- Generators:
  - `export_openapi.py` (full)
  - `export_json_schemas.py` (full — exports `TemplateDefinition`, `RulesetDefinition`, `ModuleDefinition`, `FunctionDefinition`, `HierarchyDefinition`)
  - `changelog_to_json.py` (full — regex matches the bracketed `## [x.y.z] - YYYY-MM-DD` form; current `CHANGELOG.md` uses em-dash form, so current output is `[]`; see open follow-ups)
  - `generate_llms_txt.py` (full — v1 coverage of current docs; emits 40-line `llms.txt` + 4225-line `llms-full.txt`)
  - `generate_cli_docs.py` (stub for Wave 1)
  - `generate_rule_pack_docs.py` (stub for Wave 1)
  - `generate_mcp_manifest.py` (stub for Wave 1)
- Validators:
  - `check_docstrings.py` (live in CI — current public surface: 8/8 documented)
  - `check_frontmatter.py` (dormant until Wave 2)
- Linter configs: `.markdownlint.jsonc`, `.codespellignore`, `.lycheeignore`.
- CI workflow `.github/workflows/docs.yml` with 8 steps (version sync, docs-gen, drift gate, strict mkdocs build, docstring check, markdownlint, codespell, lychee). Uses `--extra docs --extra server` (the plan's `docs-dev` extra does not exist in `pyproject.toml`; kept the existing grouping).
- Wave 0 side-fix: three broken `Next Steps` links in `docs/getting-started.md` (top-level slugs pointing under `core/` and `yaml/`) updated to their real paths so `mkdocs build --strict` passes.

## Deferred to Wave 1

- Real SDK reference generation (`pdoc`, `gomarkdoc`, `typedoc`).
- `protoc-gen-doc` for gRPC.
- Swagger UI embed + Postman collection.
- Real CLI, MCP, rule-pack docs (replacing stubs).
- VSCode snippets bundle.
- `docs-deploy.yml` workflow (GitHub Pages + `mike`) — deferred until Wave 1 has content worth deploying.

## Open follow-ups

- **m3 (silent slot-drop in `ConditionEntry`)** — not docs; belongs in its own issue.
- **`CHANGELOG.md` format divergence** — real file uses `## 0.3.0 — 2026-04-14` (em-dash, unbracketed). Parser matches the Keep-a-Changelog bracketed form per spec. Either normalize the changelog to bracketed form or extend the parser; decision belongs to Wave 1.
- **Pre-existing test failure in `tests/test_cli_repl.py`** — `INTERNALERROR` at collection time because `from fathom.cli import _repl_loop` triggers a Typer-dependent `SystemExit` during import when Typer is absent. This is in the user's uncommitted working tree, *not* introduced by Wave 0. Flagging so it does not get conflated with docs CI failures on first push.
- **Markdownlint warnings on existing `docs/core/*` and `docs/yaml/*` pages** — intentionally left failing; will be cleared by Wave 2's rewrite.

## Verification

All items below were verified locally before Wave 0 was marked complete:

- `make docs-gen` — all 7 scripts emit. Notable outputs: `docs/reference/rest/openapi.json` (6 paths), 5 JSON Schemas under `docs/reference/yaml/`, `docs/changelog.json` (0 versions — see follow-up), `docs/llms.txt` + `docs/llms-full.txt`, 3 stub manifests.
- `git diff --exit-code` on generated artifacts after re-running `docs-gen` — zero drift (idempotent generators, deterministic JSON via `sort_keys=True`).
- `uv run mkdocs build --strict` — PASS (`Documentation built in 1.84 seconds`) after the three broken-link fix in `getting-started.md`.
- `uv run pytest tests/test_scripts/ -q` — 11/11 pass (version sync × 2, openapi × 1, schemas × 1, changelog × 1, llms × 1, docstrings × 2, frontmatter × 3).
- Full `uv run pytest` — not fully green, but failure is isolated to the pre-existing `test_cli_repl.py` collection error noted in Open follow-ups above; Wave 0 changes do not touch that file or its imports.
