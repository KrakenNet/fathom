# Dev Docs — Wave 2 Completion

## Phase 1 — infrastructure (landed in earlier commits)

- `scripts/check_doc_sources.py` drift gate (frontmatter `sources:` vs `git log --format=%cI`).
- Frontmatter validator extension integrated with the docs CI workflow.
- `scripts/verify_tutorial_snippets.py` tutorial snippet runner.
- CI wiring (`.github/workflows/docs.yml`) — both gates run on every docs-touching PR.
- `mkdocs.yml` Diátaxis nav scaffold (Tutorials, How-to, Concepts, Reference).

## Phase 2 — content rewrite (this wave)

Tutorials, how-tos, concepts, and the per-construct YAML reference were rewritten
code-first with source-anchored frontmatter so the drift gate catches divergence:

### Tutorials
- `tutorials/hello-world.md` — install → first template → first rule → evaluate.
- `tutorials/modules-and-salience.md` — module focus stack, fail-closed salience.
- `tutorials/working-memory.md` — persistence across `evaluate()` calls.

### How-to Guides
- `how-to/writing-rules.md`, `fastapi.md`, `cli.md`, `register-function.md`,
  `load-rule-pack.md`, `embed-sdk.md`.

### Concepts
- `concepts/five-primitives.md` — templates, facts, rules, modules, functions.
- `concepts/runtime-and-working-memory.md` — evaluation loop, focus stack,
  fail-closed salience mechanics.
- `concepts/yaml-compilation.md` — pipeline, Pydantic safety, per-construct emission.
- `concepts/audit-attestation.md` — `AuditSink`, `FileSink`, `NullSink`,
  Ed25519 JWT attestation, threat model.
- `concepts/not-in-v1.md` — COOL, backward chaining, generics, defglobal/deffacts/logical/strategy/agenda.
- `concepts/index.md` — Diátaxis landing.

### YAML Reference (per-construct)
- `reference/yaml/template.md`, `rule.md`, `module.md`, `function.md`, `fact.md`.
- `reference/yaml/index.md` refreshed to link per-construct pages + existing JSON Schemas.

### Integration catalog
- `reference/planned-integrations.md` — honest status (Shipped / Partial / Planned)
  for fathom-go, fathom-ts, fathom-editor, and the four framework adapters
  named in `design.md:490-495`.

### Landing pages
- `_index.md` rewritten as a Diátaxis router (Learn / Solve a task / Understand / Look up).
- `getting-started.md` kept the existing install-and-first-evaluate flow,
  re-frontmattered under the drift gate, and its Next Steps links rewired
  to the new Tutorials / Concepts / Reference paths.

### Retirements (T28)
- Deleted 37 pre-Diátaxis files: `docs/core/**`, `docs/integrations/**`,
  `docs/yaml/**`, `docs/advanced/**`, `docs/rule-packs/**` (the old top-level
  set; `docs/reference/rule-packs/**` stays), `docs/writing-rules.md`,
  `docs/integration.md`.
- Wired 27 redirects in `mkdocs.yml` so retired URLs resolve to their
  closest Diátaxis replacement.
- Dropped the five retired-path exclusions from the markdownlint step in
  `.github/workflows/docs.yml` and the `docs-lint` Makefile target.
- Updated `README.md` entry points to the Diátaxis five-point list.

## Bugs flushed during the rewrite

- `docs/reference/yaml/template.md` — claimed `SlotDefinition.required` was
  "not enforced / reserved for future validation". Corrected in T27:
  `FactManager._check_required` (`src/fathom/facts.py:274-283`) enforces
  required slots on the SDK and REST paths (the flag is still not emitted
  to CLIPS and the rule-RHS `assert` path still bypasses it).
- `mkdocs.yml` nav pointed at `concepts/primitives.md` and
  `concepts/runtime.md`; actual Phase 2 files are `concepts/five-primitives.md`
  and `concepts/runtime-and-working-memory.md`. Corrected in T27.
- `design.md:492` lists the LangChain callback handler under
  "Framework adapters (planned)". The adapter already ships at
  `src/fathom/integrations/langchain.py`. Flagged in the Planned
  Integrations page; `design.md:560` already marks Phase 3 shipped, so
  the stale sentence at :492 should be reconciled on the next design.md pass.
- `packages/fathom-editor/` was stripped from the Architecture nav when
  legacy `docs/core/visual-editor.md` retired — the in-tree component stubs
  are documented in `reference/planned-integrations.md`.

## Verification

- `uv run python scripts/check_doc_sources.py` — exit 0.
- `uv run python scripts/verify_tutorial_snippets.py docs/tutorials` — exit 0.
- `uv run mkdocs build --strict` — exit 0; no broken links, no 404 warnings.
- `uv run pytest` — pre-existing test suite unaffected.
- Two-stage subagent review (spec compliance + code quality) run on each
  content task; every page shipped with REVIEW_PASS.

## Open follow-ups

- **`design.md:492`** — reconcile the stale "LangChain (planned)" line with
  the shipped adapter at `src/fathom/integrations/langchain.py`.
- **`mkdocs.yml` orphan pages** — `reference/rest/index.md` and
  `reference/grpc/index.md` generate sub-pages that are not in nav (pre-existing
  INFO-level mkdocs messages; not a failure but worth a Wave 3 pass).
- **CHANGELOG.md parser format** — still carried over from Wave 1.
- **Framework adapters beyond LangChain** — CrewAI, OpenAI Agents SDK,
  Google ADK remain "Planned" in `reference/planned-integrations.md`; real
  adapters would move them to "Shipped".
