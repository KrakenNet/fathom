---
title: Dev Docs Wave 2 — Content Rewrite
summary: Full code-first rewrite of Fathom narrative docs into Diátaxis-aligned structure, with frontmatter drift gate and tutorial snippet verification.
audience: [fathom-contributors]
diataxis: explanation
status: stable
last_verified: 2026-04-15
---

# Dev Docs Wave 2 — Content Rewrite

## Context

Wave 1 scaffolded the Reference quadrant: SDK reference, REST/gRPC/MCP/CLI landing pages, YAML schema downloads, and drift gates for generated artifacts. The narrative corpus — `docs/core/*`, `docs/integrations/*`, `docs/yaml/*`, `docs/integration.md` (~3,700 lines across 28 files) — remained untouched. These files date to the initial scaffolding commit; they were written before the engine existed and have never been verified against shipped code.

Wave 2 rewrites the narrative corpus from scratch against current source, restructures the site into Diátaxis-inspired quadrants, adds a frontmatter drift gate to prevent future content rot, and retires the legacy files from disk.

## Goals

1. Every narrative page cites the source files it documents. Drift is caught by CI, not by users.
2. The site is navigable by learning intent (Tutorials / How-to / Reference / Concepts) rather than by internal taxonomy.
3. Tutorials are executable — every fenced YAML/Python block in a tutorial runs in CI.
4. Legacy files are deleted; markdownlint/codespell exclusions for those paths are removed.
5. No silent drift: a page whose source file changes after `last_verified` fails the build until re-verified.

## Non-goals

- AI-framework adapter implementations (LangChain, CrewAI, OpenAI Agent SDK, Google ADK). Wave 2 ships a single "Planned integrations" status page, not adapter code.
- Symbol-level drift detection. File-level is the granularity.
- Notebook-backed tutorials. Markdown + snippet runner only.
- Re-architecting the Reference quadrant shipped in Wave 1.

## Architecture

### Site structure

Top-level navigation after Wave 2:

```
Home
Getting Started
Tutorials
  - Hello-world policy
  - Modules & salience
  - Working memory across evaluations
How-to Guides
  - Writing rules
  - Integrating with FastAPI
  - Using the CLI
  - Registering a Python function
  - Loading a rule pack
  - Embedding via SDK (Python / Go / TS)
Concepts
  - Five Primitives
  - Runtime & Working Memory
  - YAML Compilation
  - Audit & Attestation
  - CLIPS Features Not In v1
Reference
  - Python SDK / Go SDK / TypeScript SDK   (Wave 1)
  - REST API / gRPC / MCP / CLI / VSCode   (Wave 1)
  - YAML
      - Schemas (Wave 1 landing)
      - Template / Rule / Module / Function / Fact   (Wave 2 per-construct narrative+schema pages)
  - Rule Packs                             (Wave 1)
  - Planned integrations                   (Wave 2)
Changelog
```

The "Architecture" and "YAML Reference" top-level tabs from the pre-Wave-2 nav are removed. Legacy pages under `docs/core/`, `docs/integrations/`, `docs/yaml/`, and `docs/integration.md` are deleted from disk.

### Page-count summary

| Quadrant        | Pages | Notes                                                 |
|-----------------|-------|-------------------------------------------------------|
| Home            |   1   | existing                                              |
| Getting Started |   1   | rewritten against current install/install flow        |
| Tutorials       |   3   | progressive: hello-world → modules → working-memory   |
| How-to Guides   |   6   | writing rules, FastAPI, CLI, register fn, rule pack, SDK embed |
| Concepts        |   5   | consolidated from legacy 12 under `docs/core/`        |
| YAML Reference  |   6   | schemas index (Wave 1) + 5 per-construct pages        |
| Planned integrations | 1 | langchain / crew-ai / openai-sdk / google-adk status  |
| Changelog       |   1   | existing                                              |

Total new pages authored in Wave 2: **20** (3 tutorials + 6 how-tos + 5 concepts + 5 YAML construct pages + 1 planned-integrations page). In addition, Home, Getting Started, and the Wave-1 `reference/yaml/index.md` schema-landing page are rewritten with `sources:` frontmatter. `docs/writing-rules.md` is relocated to `docs/how-to/writing-rules.md` and rewritten in place.

### Frontmatter contract

Every Tutorials, How-to, Concepts page and every Reference page that carries narrative prose declares:

```yaml
---
title: Five Primitives
summary: One-line blurb used in search indexes and llms.txt.
audience: [rule-authors, integrators, operators]   # ≥1
diataxis: concepts   # tutorial | how-to | concepts | reference
status: stable       # stable | draft
last_verified: 2026-04-15
sources:
  - src/fathom/models.py
  - src/fathom/engine.py
---
```

**Field semantics:**
- `sources`: file-level paths (relative to repo root) to every source file whose behavior the page describes. Purely generated landing pages (REST Swagger, SDK-reference index, YAML schema index) declare `generated: true` instead of `sources:` and are exempt.
- `last_verified`: the date the page author last read the cited sources and confirmed the prose matches. Bumped manually at commit time; never auto-set.
- `status`: `stable` is the default for Wave 2 shipped pages. `draft` flags work-in-progress pages and is permitted only behind a pre-release tag.

### Drift gate (`scripts/check_doc_sources.py`)

New CI script. Reads every Markdown page with a `sources:` list. For each listed source:

1. Runs `git log -1 --format=%cI -- <source>` to obtain the last-commit timestamp.
2. Compares against the page's `last_verified` date.
3. Fails if any source's last-commit is **after** the page's `last_verified`.
4. Also fails if a listed source file does not exist (catches renames and typos).

Exit codes:
- `0` — all pages green.
- `1` — one or more pages carry sources that have changed since last verification, or list missing files.
- `2` — script misconfiguration (malformed frontmatter, YAML parse error, `git` unavailable).

Output format: one line per stale/broken page, `page.md:source.py (last modified YYYY-MM-DD, verified YYYY-MM-DD)`.

The gate runs in `.github/workflows/docs.yml` as a step adjacent to the existing docstring-coverage gate.

### Frontmatter validator extension

`scripts/check_frontmatter.py` gains a rule: pages with `diataxis: tutorial|how-to|concepts` and narrative Reference pages (`diataxis: reference` without `generated: true`) **must** declare a non-empty `sources:` list. Missing-list failures exit `1` with a `page.md: missing sources` line.

### Tutorial snippet runner (`scripts/verify_tutorial_snippets.py`)

New CI script. Walks `docs/tutorials/*.md`, extracts fenced Python code blocks:

- ` ```python ` blocks → executed in a subprocess with the `fathom` package importable. Must exit 0.
- Blocks tagged ` ```python no-verify ` → skipped (escape hatch for install instructions, counter-examples, or snippets that depend on local filesystem state).
- Multiple `python` blocks within the same page are concatenated in document order into a single subprocess (earlier names remain in scope), unless a divider ` ```python reset ` opens a new subprocess.
- YAML blocks are not executed directly. YAML content is verified by being loaded inside a Python block that passes it through the Fathom loader (`Engine.load_template_yaml(...)`, `Engine.load_ruleset_yaml(...)`, or the equivalent in-memory entry point). If a tutorial's YAML is broken, the enclosing Python block fails.

Each subprocess runs in a fresh temp directory with no inherited state; temp dirs are removed on exit.

Exit codes: `0` clean; `1` snippet failure; `2` misconfiguration. Output includes page path, block line range, and exception trace.

Runs in CI after the drift gate, before `mkdocs build --strict`.

### Legacy retirement

Handled in the final plan task, after every replacement page has landed:

- `git rm docs/core/* docs/integrations/* docs/yaml/* docs/integration.md`.
- Remove markdownlint exclusions from `.github/workflows/docs.yml`:
  - `!docs/core/**`
  - `!docs/integrations/**`
  - `!docs/yaml/**`
  - `!docs/integration.md`
- Audit `docs/advanced/**`: default action is delete (pre-implementation drafts, same provenance as `docs/core/**`). Pages retained must be rewritten in-wave against code and given frontmatter; otherwise `git rm`.
- Extend `mkdocs.yml` `redirect_maps` with every retired URL → its new home.
- Remove the pre-Wave-2 Architecture and YAML Reference top-level nav sections.

## Content production process

Each page moves through four stages:

1. **Outline** — author reads cited source files, drafts section headings and key claims. Frontmatter `sources:` populated. No prose yet.
2. **Draft** — prose written against the outline. Every factual claim traces to a cited source. YAML/Python examples written by hand against current `fathom.models` and `fathom.engine` APIs — no copy-paste from legacy.
3. **Local verification** — author runs `mkdocs build --strict`, `python scripts/check_doc_sources.py`, `python scripts/check_frontmatter.py`, and (for tutorials) `python scripts/verify_tutorial_snippets.py`. All green.
4. **Commit** — `last_verified` set to today's date at commit time.

**Rewrite-from-legacy rule:** legacy files may be opened for context, but prose is not copy-pasted. The source of truth is the code. This prevents laundering stale claims into new pages.

### Subagent workflow mapping

Wave 2 executes under `superpowers:subagent-driven-development`:

- One plan task per page, or a small cluster of ≤3 closely related pages.
- Implementer subagent receives: page path, frontmatter template, full contents of cited source files (not just paths), outline constraints from this spec.
- Spec reviewer checks: frontmatter complete, sources match what code the page actually describes, no legacy prose recycled, Diátaxis mode honored.
- Code-quality reviewer checks: tutorial snippets run, links resolve, prose is scannable, examples compile.

## Error handling

Both new CI scripts follow the same contract:

- Deterministic exit codes (`0`/`1`/`2` as specified above).
- Errors printed with `page.md:line` or `source.py` prefixes so CI log annotators can link.
- Read-only: scripts do not modify any tracked file.
- Missing or unreadable input is a configuration error (exit `2`), distinct from a legitimate drift fail (exit `1`).

## Data flow

```
source files   ──┐
                 ├─► check_doc_sources.py ──► CI fail-fast
page frontmatter ┘

tutorial .md ──► verify_tutorial_snippets.py ──► compiler / engine ──► CI fail-fast

legacy files ──► (final plan task: git rm) ──► retired
```

## Testing

- Unit tests for `scripts/check_doc_sources.py`: fixture repo with pages + simulated source mtimes, assert correct fail/pass/typo detection.
- Unit tests for `scripts/verify_tutorial_snippets.py`: fixture tutorials with known-good, known-bad, and `no-verify`-tagged blocks; assert correct exit codes and error output.
- `mkdocs build --strict` serves as the site-health integration test.
- `lychee` link check serves as the cross-page integrity test.
- Manual smoke test at end of wave: local `mkdocs serve`, click every top-level tab and confirm no orphans.

## Definition of done

1. All 15 new pages present with populated frontmatter and passing all gates.
2. Getting Started and YAML reference pages rewritten with `sources:` frontmatter.
3. `scripts/check_doc_sources.py` and `scripts/verify_tutorial_snippets.py` present, tested, and wired into `docs.yml`.
4. `scripts/check_frontmatter.py` extended to require `sources:` on narrative pages.
5. Legacy files (`docs/core/**`, `docs/integrations/**`, `docs/yaml/**`, `docs/integration.md`, stale `docs/advanced/**`) removed from disk.
6. Markdownlint exclusions for those paths removed from `docs.yml`.
7. `mkdocs build --strict` clean; `lychee` reports no broken internal links; `codespell` clean on `docs/**` without legacy-path skips.
8. Wave 2 completion record committed under `docs/superpowers/plans/`.
