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

- **GitHub Pages setup** — repo owner must enable Pages (source = `gh-pages` branch) before `docs-deploy.yml` is useful. Confirm branch protection allows the workflow's `GITHUB_TOKEN` to push to `gh-pages`.
- **`mkdocs-swagger-ui-tag` vs `mkdocs-material` native** — if Material releases first-party Swagger embed we can drop the plugin.
- **`CHANGELOG.md` format** — parser still expects bracketed form; migration is a Wave 2 content task.
- **m3** (silent slot-drop in `ConditionEntry`) — still pending its own issue.
- **typedoc 0.27+ upgrade** — current pin (`typedoc ~0.26.11` + `typedoc-plugin-markdown ~4.2.10`) is the last compatible combo; bump when the TypeScript toolchain catches up.
- **TS SDK entry-link post-processing** — the generator rewrites typedoc's `../README.md` entry links to `../index.md` and drops the auto-generated README. If typedoc-plugin-markdown ever stops emitting those links, the post-processor becomes a no-op and can be removed.

## Verification

- `make docs-gen && make docs-gen-foreign` — generators all emit or skip cleanly.
- `uv run mkdocs build --strict` — zero warnings.
- `uv run pytest tests/test_scripts/` — all script tests pass.
- `uv run pytest` — full suite green.
- CI `docs` workflow — green on the push.
- `curl <deploy URL>/llms.txt` (after first tagged release triggers `docs-deploy.yml`) — returns llms.txt.
