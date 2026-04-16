---
title: Fathom Developer Documentation — Design
date: 2026-04-15
status: approved
audience: [contributors]
---

# Fathom Developer Documentation — Design Spec

## 1. Goals, Audiences, and Non-Goals

### Goals

- A single MkDocs Material site at `https://fathom-rules.dev` (repo path: `docs/`) serving all three audiences without forking content.
- SDK reference pages auto-generated from source (pdoc for Python, gomarkdoc for Go, typedoc-markdown for TypeScript) so references never drift from code.
- LLM-friendly surface: `llms.txt`, `llms-full.txt`, OpenAPI JSON, gRPC proto, MCP manifest, machine-readable changelog — so agents (including Bosun / Nautilus / Claude-powered tools) can consume Fathom docs as a tool.
- Every public API symbol, every YAML construct, every CLI flag, every REST/gRPC endpoint has a doc page reachable in ≤ 3 clicks from the home page.
- Docs build is part of CI; a broken link, missing docstring on a public symbol, or stale generated reference fails the build.

### Primary Audiences

One site, four Diátaxis quadrants shared across audiences, curated audience landing pages that route each reader through the shared content.

- **App developers** — embedding Fathom via Python SDK, REST, gRPC, MCP, Go/TS SDKs. Want quickstarts, SDK references, integration recipes.
- **Rule authors** — writing YAML templates/rules/modules/functions. Want YAML reference, pattern cookbook, rule-pack catalog.
- **Contributors** — hacking on the compiler/engine/CLIPS bridge. Want architecture explanation, internal module reference, testing/release runbooks.

### Non-Goals (v1)

- Custom theming beyond MkDocs Material defaults.
- A separate marketing/landing site — the home page lives in MkDocs.
- Interactive "try it in browser" REPL.
- Localization.
- Algolia DocSearch / typesense search integration — MkDocs Material's built-in search suffices for v1.
- Community examples gallery.
- Newsletter / RSS beyond MkDocs Material's built-in RSS plugin.

---

## 2. Site Information Architecture

Top-level tabs are the four **Diátaxis quadrants** plus an **Audiences** tab that curates paths through them. Existing pages are folded into the new IA, not discarded; old URLs get 301 redirects via `mkdocs-redirects`.

```
Home (/)
├── Audiences                         ← curated landing pages, no original content
│   ├── For App Developers
│   ├── For Rule Authors
│   └── For Contributors
│
├── Tutorials                         ← learning-oriented, numbered, linear
│   ├── 1. Your First Rule (10 min)
│   ├── 2. Working Memory & Cumulative Reasoning
│   ├── 3. Build a LangChain Guard
│   ├── 4. Ship a Rule Pack
│   └── 5. Run Fathom as a Sidecar (REST + gRPC)
│
├── How-To Guides                     ← task-oriented, standalone recipes
│   ├── Rule Authoring
│   │   ├── Write a deny rule
│   │   ├── Add a custom function
│   │   ├── Use classification operators
│   │   ├── Cross-fact references
│   │   ├── Temporal patterns
│   │   └── Use a rule pack
│   ├── Integration
│   │   ├── Python SDK · Go SDK · TypeScript SDK
│   │   ├── REST · gRPC · MCP tool server
│   │   ├── LangChain · Docker sidecar · CLI
│   ├── Operations
│   │   ├── Configure auth · Jail rule paths
│   │   ├── Export Prometheus metrics · Enable attestation
│   │   ├── Audit log sinks · Versioning & upgrades
│   └── Contributing
│       ├── Local dev setup · Run the test suite
│       ├── Write a compiler pass · Add a YAML construct
│       └── Release a new version
│
├── Reference                         ← information-oriented, mostly generated
│   ├── YAML
│   │   ├── Templates · Facts · Rules · Modules · Functions
│   │   ├── Operators
│   │   └── Schemas (JSON Schema downloads)
│   ├── Python SDK (generated, pdoc)
│   ├── Go SDK (generated, gomarkdoc)
│   ├── TypeScript SDK (generated, typedoc-markdown)
│   ├── REST API (generated, OpenAPI → Redoc + Swagger UI + Postman)
│   ├── gRPC API (generated from .proto)
│   ├── MCP Tools (generated from server manifest)
│   ├── CLI (generated from Click/Typer introspection)
│   ├── Rule Packs
│   │   └── OWASP Agentic · NIST 800-53 · HIPAA · CMMC
│   └── Tooling
│       └── VSCode snippets · JetBrains templates
│
├── Explanation                       ← understanding-oriented, prose
│   ├── Why Fathom (vs OPA / Cedar / LLM-as-policy)
│   ├── CLIPS in 15 Minutes
│   ├── The Five Primitives
│   ├── Working Memory & Forward Chaining
│   ├── Salience, Modules, and Focus Stack
│   ├── Audit Log & Attestation Model
│   ├── Architecture Overview
│   └── Security Model
│
└── Meta
    ├── Changelog (from CHANGELOG.md)
    ├── Roadmap (mirrors design.md roadmap)
    ├── FAQ
    └── llms.txt · llms-full.txt (linked, not rendered as nav)
```

### Existing-page fate (full-refresh pass)

| Current path | Destination | Action |
|---|---|---|
| `docs/core/*` | `docs/explanation/*` | Rewrite using Explanation template |
| `docs/yaml/*` | `docs/reference/yaml/*` | Rewrite; exhaustive operator tables |
| `docs/integrations/*` | Split: `docs/explanation/*` + `docs/how-to/integration/*` + `docs/reference/*` | Split by Diátaxis mode |
| `docs/api/*` | `docs/reference/python-sdk/*` | Replace wholesale by pdoc output |
| `docs/rule-packs/*` | `docs/reference/rule-packs/*` | Rewrite using Rule Pack template |
| `docs/writing-rules.md` | Tutorial 1 + Tutorial 2 | Split and rewrite |
| `docs/getting-started.md` | Home page "60-second example" + Tutorial 1 | Split |
| `docs/external/CLIPS` | `docs/explanation/clips-in-15-minutes.md` | Move, rewrite |
| `docs/_index.md` | New `docs/index.md` (home) | Rewrite |

Every pre-migration URL gets a 301 redirect entry in `mkdocs.yml`.

---

## 3. SDK Reference Generation

Every SDK reference is generated at build time and never hand-maintained. Generation failures fail CI.

### Python SDK — `pdoc`

- Tool: `pdoc` (zero-config, reads type hints + docstrings, emits HTML and Markdown). Already compatible with `py.typed` shipping.
- Docstring style: Google-style (prevalent in `src/fathom/*`). Enforced by `ruff` rule `D` group (`D212`, `D415`, plus a Google-style preset).
- Build step: `uv run pdoc --output-directory docs/reference/python-sdk src/fathom` → nested Markdown tree MkDocs can index.
- Also retain `mkdocstrings` (already in `mkdocs.yml`) for embedded API blocks inside hand-written pages (e.g. "Here's the full API for `Engine`: ::: fathom.Engine"). Two tools, two jobs.
- Coverage gate: `scripts/check_docstrings.py` walks `fathom.__all__` and every public submodule; fails if any public symbol lacks a docstring or contains `TODO` / `FIXME`.

### Go SDK — `gomarkdoc`

- Tool: `gomarkdoc` renders `godoc` as Markdown for MkDocs ingestion.
- Output: `docs/reference/go-sdk/`.
- **Prerequisite**: REVIEW.md **M2** (proto `go_package` vs `go.mod` path mismatch) must be resolved before generation succeeds. This spec raises M2 as a Wave-0 blocker task.
- Godoc comments required on every exported identifier; enforced by `revive` (`exported` rule) in CI.
- Cross-links to pkg.go.dev from the SDK landing page.

### TypeScript SDK — `typedoc` + `typedoc-plugin-markdown`

- Output: `docs/reference/typescript-sdk/`.
- TSDoc comments on all exported symbols; enforced by `eslint-plugin-tsdoc`.
- Invocation: `pnpm --filter fathom-ts run docs`.

### REST API — OpenAPI + Redoc + Swagger UI + Postman

- Source of truth: FastAPI emits OpenAPI at runtime. `scripts/export_openapi.py` imports the app and dumps schema to `docs/reference/rest/openapi.json` (no server needed).
- Rendering: **Redoc** for reference reading, **Swagger UI** at `/reference/rest/try/` for interactive try-it.
- **Postman collection**: `openapi-to-postmanv2` converts `openapi.json` to `docs/reference/rest/fathom.postman_collection.json`. "Run in Postman" button on the landing page. Insomnia imports OpenAPI directly — link documented.
- **Fix M5-adjacent bug**: FastAPI app currently declares `version="0.1.0"`. Bind it to `fathom.__version__` at startup as part of this spec's Wave 1.

### gRPC API — `protoc-gen-doc`

- Output: `docs/reference/grpc/fathom.md` plus raw `.proto` served at `docs/reference/grpc/fathom.proto`.
- Canonical source: `protos/fathom.proto`.
- Blocked by M2 in the same way as the Go SDK ref.

### MCP Tools — manifest-driven

- `scripts/generate_mcp_manifest.py` introspects `FathomMCPServer` and emits `docs/reference/mcp/manifest.json` (tool name, description, input schema, output schema).
- A Jinja template renders one Markdown page per tool under `docs/reference/mcp/`.

### CLI — Click/Typer introspection

- Emit `--help` trees via `typer-cli utils docs` (or Click equivalent) → `docs/reference/cli/*.md`.
- Every command and flag documented, examples pulled from docstrings.

### Rule Packs — YAML introspection

- `scripts/generate_rule_pack_docs.py` walks `src/fathom/rule_packs/{owasp_agentic,nist_800_53,hipaa,cmmc}` and emits one page per pack: rule count, module mapping, rule table (name / salience / summary / source file / controls covered), example assert/deny scenarios.
- Also emits `docs/reference/rule-packs/rule-packs.json` for agent consumption.

---

## 4. LLM-Consumable Artifacts

All artifacts live under `docs/` and are served at predictable URLs so an agent can fetch a single URL tree and have everything needed to use Fathom.

### `/llms.txt` — index (llmstxt.org spec)

- Served at site root. Plain-text, llmstxt.org format: `# Fathom` header, one-paragraph summary, grouped link lists.
- Groups: Core docs · SDK references · How-to recipes (top ~15) · Rule packs · Machine-readable artifacts.
- Generated by `scripts/generate_llms_txt.py` walking `mkdocs.yml` nav + page frontmatter summaries.

### `/llms-full.txt` — full bundled Markdown

- Concatenation of every doc page in reading order, with `## <page path>` separators and source URL comments.
- Target size 200–400 KB. If > 500 KB, split into `llms-full-core.txt` and `llms-full-reference.txt`.
- Generated by the same script in one pass from post-rendered Markdown sources.

### OpenAPI JSON — `/reference/rest/openapi.json`

- Versioned in git. CI diff-gates committed copy against freshly exported schema to enforce no drift.

### gRPC proto — `/reference/grpc/fathom.proto`

- Served as static text.

### MCP manifest — `/reference/mcp/manifest.json`

- JSON manifest of all tools exposed by `FathomMCPServer`. Lets other MCP servers / agents discover Fathom without running it.

### Machine-readable changelog — `/changelog.json`

- Emitted from `CHANGELOG.md` via `scripts/changelog_to_json.py`. Keep-a-Changelog format → array of `{version, date, added, changed, deprecated, removed, fixed, security}`.

### Rule-pack catalog — `/reference/rule-packs/rule-packs.json`

- One record per pack: id, version, module, rules, control coverage, schema. Queryable by agents (e.g. "find rule pack covering HIPAA 164.312(a)").

### `robots.txt` + LLM crawl hints

- Permissive. Explicit `Allow: /` for `ClaudeBot`, `GPTBot`, `PerplexityBot`, `Google-Extended` — this is a library docs site; we want it retrievable.

### `sitemap.xml`

- Generated by MkDocs Material by default.

### Code-fenced example manifests — `/examples/manifest.json`

- For each directory under the repo's `examples/`: name, summary, files, entrypoint command, expected output. Lets an agent pick and run an example programmatically.

### `CITATION.cff` + `.well-known/security.txt`

- `CITATION.cff` at repo root for academic references.
- `security.txt` at `/.well-known/security.txt` for responsible disclosure.

### `AGENTS.md` at repo root

- Short file pointing LLMs at `CLAUDE.md`, `design.md`, `docs/llms.txt`. Complements `CLAUDE.md` for non-Claude agents.

### JSON Schema for YAML — `/reference/yaml/schemas/`

- One schema per construct: `template.schema.json`, `rule.schema.json`, `module.schema.json`, `function.schema.json`, `ruleset.schema.json`, `hierarchy.schema.json`. Plus a combined `fathom.schema.json` with top-level `oneOf` / `$defs`.
- Source of truth: Pydantic models in `src/fathom/models.py`. `scripts/export_json_schemas.py` exports via `Model.model_json_schema()`. CI diff-gates.
- Register with **SchemaStore.org** so VSCode / IntelliJ / Helix auto-associate `.yaml` files in `templates/`, `rules/`, `modules/`, `functions/` folders.
- Docs page shows VSCode `yaml.schemas` setup and `yaml-language-server` inline schema header:
  ```yaml
  # yaml-language-server: $schema=https://fathom-rules.dev/reference/yaml/schemas/rule.schema.json
  ```

### VSCode snippets + extension scaffold — `/reference/tooling/vscode/`

- **Snippets file**: `fathom.code-snippets` with snippets for:
  - New template / rule / module / function (YAML skeletons).
  - Common condition patterns (`below(...)`, `count_exceeds(...)`, `$fact.slot` cross-ref).
  - Common action patterns (deny with reason, allow with scope, assert + bind).
  - CLIPS raw-passthrough stubs (`deftemplate`, `defrule`, `deffunction`).
- **Delivery**: downloadable `.code-snippets` file with copy-paste instructions **and** a minimal VSCode extension scaffold at `packages/fathom-vscode/` that ships snippets + YAML schema association + syntax highlighting. Marketplace publication deferred.
- **JetBrains live templates**: mirror XML file, lower priority.

---

## 5. CI, Build, and Publishing

### Local dev

- `uv run mkdocs serve` — live preview of hand-written pages.
- A `Makefile` at repo root orchestrates generation + build. Targets: `docs-gen`, `docs-build`, `docs-serve`, `docs-lint`, `docs-clean`.
- `make docs-gen` order:
  1. `scripts/export_openapi.py` → `docs/reference/rest/openapi.json`
  2. `scripts/export_json_schemas.py` → `docs/reference/yaml/schemas/*.json`
  3. `scripts/generate_cli_docs.py` → `docs/reference/cli/*.md`
  4. `scripts/generate_rule_pack_docs.py` → `docs/reference/rule-packs/*.md` + `rule-packs.json`
  5. `scripts/generate_mcp_manifest.py` → `docs/reference/mcp/manifest.json`
  6. `scripts/changelog_to_json.py` → `docs/changelog.json`
  7. `pdoc` → `docs/reference/python-sdk/`
  8. `gomarkdoc` (via `cd packages/fathom-go && make docs`) → `docs/reference/go-sdk/`
  9. `typedoc` (via `pnpm --filter fathom-ts run docs`) → `docs/reference/typescript-sdk/`
  10. `protoc-gen-doc` → `docs/reference/grpc/fathom.md`
  11. `openapi-to-postmanv2` → `docs/reference/rest/fathom.postman_collection.json`
  12. `scripts/generate_llms_txt.py` → `docs/llms.txt` + `docs/llms-full.txt`

### CI — new `.github/workflows/docs.yml`

REVIEW.md notes no CI currently exists. This spec establishes CI for docs only; other CI concerns are out of scope.

Jobs:

1. **`docs-generate`** — runs `make docs-gen`; fails if any generator errors.
2. **`docs-drift`** — verifies committed generated artifacts match freshly generated output (`git diff --exit-code` on `docs/reference/**`, `docs/llms*.txt`, `docs/changelog.json`). Forces regeneration when code changes.
3. **`docs-build`** — `mkdocs build --strict` (fails on warnings: broken cross-refs, missing pages in nav, orphan files).
4. **`docs-lint`** — `markdownlint-cli2` on hand-written pages (exclude `docs/reference/**`).
5. **`docs-link-check`** — `lychee --no-progress docs/`. External links warn-only; internal failures block.
6. **`docs-spelling`** — `codespell` with `.codespellignore` for domain terms (CLIPS, Rete, salience, clipspy, etc.).
7. **`docs-docstring-coverage`** — `scripts/check_docstrings.py` + Go `revive` + TS `eslint-plugin-tsdoc`. Fails if any public symbol lacks docstring.
8. **`docs-schema-validation`** — round-trip: validate each example YAML under `examples/` against the generated JSON Schema.

Triggers: PRs touching `src/**`, `docs/**`, `packages/**`, `protos/**`, `CHANGELOG.md`, or the docs workflow itself.

### Publishing

- **Primary host**: GitHub Pages from `gh-pages` branch. `mkdocs gh-deploy` on merges to `master` (separate workflow `.github/workflows/docs-deploy.yml`).
- **Custom domain**: `fathom-rules.dev` via `docs/CNAME`. Matches `site_url` in `mkdocs.yml`.
- **Versioned docs**: `mike` publishes versioned docs (`latest`, `stable`, `0.3.x`, `0.2.x`). Version selector in header. Release workflow runs `mike deploy --push --update-aliases <version> latest`.
- **Preview deploys**: deferred for v1. Adopt Cloudflare Pages / Netlify previews if PR iteration becomes painful.
- **`llms.txt` and friends**: served alongside the site from `docs/`, so `https://fathom-rules.dev/llms.txt` works from GitHub Pages directly.

### Release-time docs tasks (added to release runbook)

- Bump version in `pyproject.toml` AND `src/fathom/__init__.py` (resolves the class of bug in REVIEW.md M1).
- `scripts/check_version_sync.py` runs in CI to prevent recurrence.
- Update `CHANGELOG.md` — `changelog.json` derives from it.
- `mike deploy --push --update-aliases <version> latest` on tag.
- Verify `/llms.txt`, `/openapi.json`, `/changelog.json` are current on deployed site.

---

## 6. Writing Style, Page Templates, and Quality Bar

### Voice and style

- **Diátaxis discipline**: each page serves one mode. Tutorials teach (imperative, "you"), how-tos instruct (imperative, goal-first), references describe (declarative, third-person), explanations narrate (expository).
- **Tone**: terse, confident, no marketing. Match `design.md` and `README.md` voice (short declarative sentences, concrete examples, no hedging).
- **No emoji** in docs body. Admonitions (`!!! note`, `!!! warning`) instead.
- **Second person singular** ("you") in tutorials and how-tos. **Never "I"** except in FAQ entries.
- **Present tense, active voice**.
- **Banned words**: "simply", "just", "easily", "obviously". Enforced by `vale` Write-Good lint.
- **Short sentences** — target ≤ 25 words.
- **Code before prose** where possible — show the snippet, then explain.

### Page templates (committed to `docs/_templates/`)

1. **Tutorial** — goal · prerequisites · numbered steps with concrete output · "what you learned" · next tutorial.
2. **How-to** — task statement · prerequisites · steps · verification · related how-tos.
3. **Reference (manual)** — one-line summary · signature/schema · parameters table · return/emits · examples · notes · see also.
4. **Reference (auto)** — frontmatter only; body generated.
5. **Explanation** — the question this page answers · context · the concept · trade-offs · implications · further reading.
6. **Integration recipe** — target system · prerequisites · install · minimal example · advanced config · troubleshooting.
7. **Rule pack** — pack id + version · coverage matrix · rule list table · module layout · install · example decisions · upgrade notes.

### Content rules

- **Every page has a one-line TL;DR** under the H1. Feeds `llms.txt` summaries.
- **Every code sample runs** where feasible. Python/YAML samples extracted and tested in CI by `pytest --doctest-glob='docs/**/*.md'`. Non-runnable snippets get `# not runnable — illustrative`.
- **No dead links**. Lychee (internal blocking, external warn-only). Every cross-ref uses relative MkDocs paths.
- **Every public symbol referenced by name** has an `mkdocstrings` block.
- **Diagrams** via Mermaid (fenced `mermaid` blocks). ASCII art from `design.md` promoted to Mermaid where sensible.
- **Consistent naming**: "Fathom", "CLIPS", "working memory", "rule pack", `deftemplate`/`defrule`/`defmodule`/`deffunction` in code font, lowercase.

### Frontmatter on every hand-written page

```yaml
---
title: Your First Rule
summary: Load a YAML rule, assert a fact, evaluate, and read the decision.
audience: [app-developers, rule-authors]
diataxis: tutorial
reading_time: 10
status: stable | draft | experimental
last_verified: 2026-04-15
---
```

`summary` + `audience` + `diataxis` feed audience landing pages and `llms.txt` grouping. `last_verified` is checked by a scheduled CI job that warns on pages > 180 days stale.

### Quality gates (on top of Section 5)

- All hand-written pages have required frontmatter (`scripts/check_frontmatter.py`).
- No page exceeds 1,500 words (forces how-to + explanation pairs).
- Every tutorial has numbered steps and a concrete "you'll know it worked when…" verification.
- References to unreleased features must have `status: experimental` frontmatter.

### Style linting

- `markdownlint-cli2` (config at `.markdownlint.jsonc`).
- `vale` with Write-Good + Microsoft-Writing-Style-Guide packages, configured as **warning** (not blocker).
- `codespell` blocks build.

### Contributor-facing doc-authoring guide

- New page `Contributing / Writing Docs` documents templates, banned-words list, frontmatter schema, `make docs-serve` workflow.

---

## 7. Migration, Phasing, and Verification

### Migration model

**Parallel-write, then cut-over.** Existing `docs/` tree stays in place; new pages are written under new paths; `mkdocs.yml` nav flips in one commit at the end of each wave. Redirects via `mkdocs-redirects` preserve all existing URLs.

### Waves

**Wave 0 — Infra (no user-visible content)**
- Add `mkdocs-redirects`, `mike`, generator scripts, Makefile targets, CI workflow.
- Fix prerequisites: REVIEW.md **M2** (proto ↔ go.mod path mismatch) blocks Wave 1 Go SDK reference. Flagged as explicit gating task.
- Ship `llms.txt` and `llms-full.txt` for existing content as a quick win.
- Fix `mkdocs.yml:5` `repo_name` to `KrakenNet/fathom` (REVIEW.md m5).

**Wave 1 — Reference (mostly generated, lowest risk)**
- Generate and publish Python/Go/TS SDK refs, REST OpenAPI + Swagger/Postman, gRPC, MCP, CLI, JSON Schemas, rule-pack catalog, VSCode snippets bundle.
- Bind FastAPI `version` to `fathom.__version__` (fixes REVIEW.md's stale `version="0.1.0"` note).
- Redirect `docs/api/*`, `docs/yaml/*`, `docs/rule-packs/*` → new `docs/reference/*` paths.

**Wave 2 — Explanation**
- Rewrite `docs/core/*` into `docs/explanation/*` using Explanation template.
- Move `docs/external/CLIPS` → `docs/explanation/clips-in-15-minutes.md`.
- Redirect old URLs.

**Wave 3 — How-to guides**
- Extract task-oriented content from `docs/integrations/*` into `docs/how-to/integration/*`.
- Write new how-tos for gaps identified in Section 2.
- Retire `docs/integrations/` after content is re-homed.

**Wave 4 — Tutorials**
- Five tutorials from scratch, each tied to a runnable example under `examples/`.
- `examples/manifest.json` emitted so each tutorial has a corresponding runnable folder.

**Wave 5 — Audience landing pages + home + meta**
- Three audience landing pages, new home page, FAQ, roadmap mirror, changelog page.
- Flip `mkdocs.yml` nav to final Section 2 layout.
- Redirect old top-level pages (`getting-started.md`, `writing-rules.md`, `integration.md`, `_index.md`).

**Wave 6 — Polish**
- Vale pass, Mermaid diagrams, cross-link audit, `last_verified` sweep.
- Tag docs v1.0 via `mike`.

### Handling of REVIEW.md bugs

Docs spec cannot cleanly ship without these being resolved. Each lands as an explicit task gate in the plan:

- **M1** (version skew `pyproject.toml` vs `__init__.py`) — Wave 0 pre-req task. Adds `scripts/check_version_sync.py` CI check.
- **M2** (proto ↔ go.mod mismatch) — Wave 0 pre-req task; blocks Wave 1 Go SDK generation.
- **m3** (silent slot-drop in `ConditionEntry`) — out of scope; kicked to its own issue.
- **m5** (`mkdocs.yml` `repo_name`) — Wave 0 fix while editing the file.
- **FastAPI `version="0.1.0"`** — Wave 1 fix during OpenAPI export task.

### Verification (success criteria)

Spec is complete when every item is mechanically verifiable:

- [ ] `make docs-build` succeeds with zero warnings on a clean checkout.
- [ ] CI workflow `docs.yml` green on a PR.
- [ ] Every public Python symbol in `fathom.__all__` has a generated reference page.
- [ ] `gh pages` deploy produces a live site at `https://fathom-rules.dev/` with working version selector.
- [ ] `curl https://fathom-rules.dev/llms.txt` returns a valid llms.txt document.
- [ ] `curl https://fathom-rules.dev/llms-full.txt` returns < 500 KB of Markdown.
- [ ] `curl .../reference/rest/openapi.json` returns valid OpenAPI 3.1 matching the running FastAPI app.
- [ ] `curl .../reference/yaml/schemas/rule.schema.json` validates `examples/01-hello-allow-deny` YAML.
- [ ] Every tutorial example runs end-to-end when executed from a clean environment (CI runs them).
- [ ] 301 redirects in place for every pre-migration URL (tested via `lychee` on a seed list).
- [ ] Audience landing pages list at least 5 curated links each.
- [ ] `scripts/check_docstrings.py` reports 100% coverage on public API.
- [ ] README links the docs site and the three audience landing pages.
- [ ] Postman collection imports cleanly.
- [ ] VSCode snippets bundle loads in a test workspace and expands at least one snippet per family.

### Out of scope (deferred, named so not forgotten)

- Algolia DocSearch / typesense.
- Interactive REPL / playground.
- Community examples gallery.
- i18n.
- Marketing microsite / design system beyond MkDocs Material defaults.
- Newsletter / RSS (beyond Material's built-in RSS plugin).
- Preview deploys per PR (adopt later if needed).
- JetBrains marketplace publication of snippets.
- VSCode marketplace publication of the extension (scaffold ships, publication deferred).

---

## Research notes (Section B — targeted sources)

Design informed by current patterns from the following projects and specs:

- **Diátaxis framework** (diataxis.fr) — four-quadrant doc taxonomy. Adopted wholesale for top-level IA.
- **Stripe Docs** — "Run in Postman" affordance, audience-curated landing pages, terse voice.
- **Supabase Docs** — SDK references per language alongside shared conceptual pages; MkDocs/Nextra hybrid approach informs the "one site, multiple generated refs" decision.
- **Prisma Docs** — "API Reference" as a generated surface with hand-written guides alongside; schema-as-source-of-truth.
- **FastAPI Docs** — MkDocs Material + mkdocstrings reference model; OpenAPI-as-source-of-truth for REST.
- **OPA Docs** — policy-engine parallel; Rego reference + integration recipes layout maps cleanly to Fathom's YAML reference + integration how-tos.
- **llmstxt.org spec** (Jeremy Howard, 2024) — `/llms.txt` and `/llms-full.txt` conventions for LLM-consumable docs.
- **SchemaStore.org** — registration process for YAML schema auto-association in editors.

---

## Appendix — Adjacent deliverables (Workstreams 1 and 2)

This spec covers Workstream 3 (dev docs). The other two workstreams execute directly as immediate work:

### Workstream 1 — Design-doc verification (approach A)

Audit `design.md` roadmap against shipped code. Check off completed items, add a Status column per phase, note deferred or changed items. In place. No separate artifact.

### Workstream 2 — KB + README full refresh (approach C)

Rewrite thin or outdated KB pages, normalize tone and style, add diagrams where helpful. README refreshed to reflect actual shipped state, including version, package name, integration surface, and links to the upcoming docs site.
