# Fathom — Deterministic Reasoning Runtime for the AI Era

> A modern Python-first expert system runtime built on CLIPS. Define rules in YAML. Evaluate in microseconds. Zero hallucinations.

**Status:** Design Draft
**License:** MIT
**Language:** Python (primary), with planned Go and TypeScript SDKs
**Package Manager:** uv
**Maintained by:** Kraken Networks

---

## Why Fathom Exists

Every AI agent framework gives agents tools and lets them decide what to do. The agent reasons probabilistically — it guesses. For most tasks, that's fine.

For some tasks, guessing is unacceptable:

- **Policy enforcement:** "Is this agent allowed to do this?" can't be a maybe.
- **Data routing:** "Which databases should this query hit?" can't hallucinate a source.
- **Compliance:** "Did this fleet operate within NIST 800-53 controls?" needs a provable answer.
- **Classification:** "What clearance level does this data require?" is not a prompt engineering problem.

These decisions need **deterministic, explainable, auditable reasoning** — not an LLM.

CLIPS is a 40-year-old expert system that does exactly this. It's also painful to work with, poorly documented, and invisible to the modern AI ecosystem. Fathom makes CLIPS accessible as a modern Python library with a YAML-first authoring experience.

---

## Core Primitives

Fathom exposes five primitives from CLIPS. These are the building blocks — everything else (rule packs, Nautilus routing, Bosun governance) composes from these.

### 1. Templates

Templates define the shape of facts. They're schemas — named slots with types. Without templates, facts are unstructured blobs. With them, Fathom validates facts at assertion time and the YAML compiler can catch errors before evaluation.

```yaml
# templates/agent.yaml
templates:
  - name: agent
    description: "An AI agent requesting access or action"
    slots:
      - name: id
        type: string
        required: true
      - name: clearance
        type: symbol
        required: true
        allowed_values: [unclassified, cui, confidential, secret, top-secret]
      - name: purpose
        type: symbol
        required: true
      - name: session_id
        type: string
        required: true

  - name: data_request
    description: "A request to access a data source"
    slots:
      - name: agent_id
        type: string
        required: true
      - name: target
        type: string
        required: true
      - name: classification
        type: symbol
        required: true
      - name: action
        type: symbol
        allowed_values: [read, write, delete]
        default: read

  - name: access_log
    description: "Record of a completed data access within a session"
    slots:
      - name: agent_id
        type: string
        required: true
      - name: source
        type: string
        required: true
      - name: data_type
        type: symbol
        required: true
      - name: timestamp
        type: float
```

```python
from fathom import Engine

engine = Engine()
engine.load_templates("templates/")

# Valid — matches template schema
engine.assert_fact("agent", {
    "id": "agent-alpha",
    "clearance": "secret",
    "purpose": "threat-analysis",
    "session_id": "sess-001"
})

# Raises ValidationError — "clearence" is not a valid slot
engine.assert_fact("agent", {"id": "agent-alpha", "clearence": "secret"})

# Raises ValidationError — "cosmic" is not in allowed_values
engine.assert_fact("agent", {"id": "agent-alpha", "clearance": "cosmic"})
```

Templates compile to CLIPS `deftemplate` constructs. Raw CLIPS `deftemplate` passthrough is also supported.

### 2. Facts

Facts are typed instances of templates asserted into working memory. They represent the current state of the world that rules reason about.

```python
engine.assert_fact("agent", {
    "id": "agent-alpha",
    "clearance": "secret",
    "purpose": "threat-analysis",
    "session_id": "sess-001"
})

engine.assert_fact("data_request", {
    "agent_id": "agent-alpha",
    "target": "hr_records",
    "classification": "cui",
    "action": "read"
})

# Bulk assertion
engine.assert_facts([
    ("access_log", {"agent_id": "agent-alpha", "source": "hr_db", "data_type": "PII", "timestamp": 1713020400.0}),
    ("access_log", {"agent_id": "agent-alpha", "source": "finance_db", "data_type": "PII", "timestamp": 1713020460.0}),
])
```

**Working memory queries** — inspect state without triggering evaluation:

```python
# Query working memory directly
agents = engine.query("agent", {"clearance": "secret"})
logs = engine.query("access_log", {"agent_id": "agent-alpha"})
pii_count = engine.count("access_log", {"agent_id": "agent-alpha", "data_type": "PII"})

# Retract facts
engine.retract("data_request", {"agent_id": "agent-alpha", "target": "hr_records"})
```

Working memory persists across evaluations within a session. This enables cumulative reasoning, temporal patterns, and cross-fact inference — Fathom's core differentiator over stateless engines like OPA and Edictum.

### 3. Rules

Rules define pattern-matching logic that fires when facts in working memory match conditions. Authored in YAML (compiled to CLIPS `defrule`) or in raw CLIPS for advanced cases.

```yaml
# rules/access-control.yaml
ruleset: access-control
version: 1.0
module: governance

rules:
  - name: deny-insufficient-clearance
    description: "Deny access when agent clearance is below data classification"
    salience: 100
    when:
      agent:
        clearance: below($data.classification)
      data_request:
        as: $data
    then:
      action: deny
      reason: "Agent clearance '{agent.clearance}' insufficient for '{$data.classification}' data"
      log: full

  - name: allow-matching-clearance
    salience: 50
    when:
      agent:
        clearance: meets_or_exceeds($data.classification)
        purpose: in([read, analyze])
      data_request:
        as: $data
    then:
      action: allow
      scope: "authorized-collections"
      log: full
```

**Salience** controls firing priority. When multiple rules match, higher salience fires first. The evaluator uses last-write-wins on `__fathom_decision` facts, so the rule that fires LAST wins. Deny rules should have LOWER salience than allow rules so they fire last and override any prior allow — this is the fail-closed default.

### 4. Modules

Modules namespace rules into isolated groups with controlled execution order via the focus stack. This is how rule packs compose without collision.

```yaml
# modules.yaml
modules:
  - name: classification
    description: "Classification and clearance evaluation"
    priority: 1

  - name: governance
    description: "Action-level governance rules"
    priority: 2

  - name: routing
    description: "Data source routing decisions"
    priority: 3

  - name: cumulative
    description: "Cross-session exposure analysis"
    priority: 4

focus_order: [classification, governance, routing, cumulative]
```

```python
engine.load_modules("modules.yaml")

# Rules loaded into their declared modules
engine.load_rules("rules/classification.yaml")   # module: classification
engine.load_rules("rules/access-control.yaml")   # module: governance
engine.load_rules("rules/routing.yaml")           # module: routing
engine.load_rules("rules/exposure.yaml")          # module: cumulative

# Evaluation follows focus order:
# 1. Classification rules fire first (determine data sensitivity levels)
# 2. Governance rules fire second (allow/deny based on classification output)
# 3. Routing rules fire third (select data sources)
# 4. Cumulative rules fire last (check session-wide patterns)
result = engine.evaluate()
```

Installing multiple rule packs is safe because each pack declares its module. NIST rules live in the `nist` module, HIPAA in `hipaa`, routing in `routing`. No rule name collisions, and focus order determines which module's decisions take precedence.

### 5. Functions

Custom functions provide reusable logic that rules reference in conditions and actions. The classification-aware operators (`below`, `meets_or_exceeds`) and temporal operators (`count_exceeds`, `rate_exceeds`) are implemented as functions.

```yaml
# functions/classification.yaml
functions:
  - name: below
    description: "Returns true if level_a ranks below level_b in the classification hierarchy"
    params: [level_a, level_b]
    hierarchy_ref: classification.yaml

  - name: meets_or_exceeds
    description: "Returns true if level_a ranks at or above level_b"
    params: [level_a, level_b]
    hierarchy_ref: classification.yaml

  - name: count_exceeds
    description: "Count facts matching a template+filter, return true if count > threshold"
    params: [template, filter, threshold]

  - name: rate_exceeds
    description: "Count matching facts within a time window, return true if rate > threshold"
    params: [template, filter, threshold, window_seconds]
```

For advanced use cases, raw CLIPS `deffunction` passthrough:

```python
engine.load_clips_function("""
(deffunction combined-risk (?clearance ?data-class ?access-count)
    (bind ?base-risk (- (classification-rank ?data-class) (classification-rank ?clearance)))
    (bind ?volume-risk (/ ?access-count 10))
    (+ ?base-risk ?volume-risk))
""")
```

Functions compile from YAML when possible. Raw CLIPS is available for anything the YAML abstraction can't express — complex math, string manipulation, or custom scoring logic.

---

## Evaluation

```python
engine.load_templates("templates/")
engine.load_modules("modules.yaml")
engine.load_functions("functions/")
engine.load_rules("rules/")

engine.assert_fact("agent", {
    "id": "agent-alpha",
    "clearance": "secret",
    "purpose": "threat-analysis",
    "session_id": "sess-001"
})

engine.assert_fact("data_request", {
    "agent_id": "agent-alpha",
    "target": "hr_records",
    "classification": "top-secret",
    "action": "read"
})

result = engine.evaluate()

print(result.decision)     # "deny"
print(result.reason)       # "Agent clearance 'secret' insufficient for 'top-secret' data"
print(result.rule_trace)   # ["classification::resolve-levels", "governance::deny-insufficient-clearance"]
print(result.module_trace) # ["classification", "governance"] (routing/cumulative never reached)
print(result.duration_us)  # 47
```

---

## Working Memory

Unlike stateless policy engines (OPA, Cedar, Edictum), Fathom maintains working memory across evaluations within a session. This enables:

- **Cumulative reasoning:** "This agent has accessed PII from 3 sources this session — deny the 4th."
- **Temporal patterns:** "This agent's denial rate spiked 400% in the last 10 minutes — escalate."
- **Cross-fact inference:** "Agent A passed data to Agent B. Agent B is requesting external network access. The combination violates information flow policy."

```python
# Working memory persists across evaluations within a session
engine.assert_fact("access_log", {"agent_id": "agent-alpha", "source": "hr_db", "data_type": "PII", "timestamp": 1713020400.0})
engine.assert_fact("access_log", {"agent_id": "agent-alpha", "source": "finance_db", "data_type": "PII", "timestamp": 1713020460.0})
engine.assert_fact("access_log", {"agent_id": "agent-alpha", "source": "medical_db", "data_type": "PHI", "timestamp": 1713020520.0})

# Rule using count_exceeds function: "3 PII accesses in one session exceeds threshold"
result = engine.evaluate()  # -> escalate

# Query working memory without triggering rules
logs = engine.query("access_log", {"agent_id": "agent-alpha"})
print(len(logs))  # 3
```

This is Fathom's core differentiator. OPA evaluates a request against policy. Fathom reasons about a *situation* across multiple facts over time.

### Explicitly Not in v1

- **COOL (CLIPS Object System)** — Full OOP layer. Powerful but adds massive surface area. Templates + functions cover the use cases.
- **Backward chaining** — Goal-driven reasoning. Forward chaining covers governance and routing. Backward chaining is a v2 consideration.
- **Generic functions / message handlers** — Over-engineering for the current problem space.

---

## Architecture

```
┌──────────────────────────────────────────┐
│              Fathom Engine                │
│                                          │
│  ┌──────────┐  ┌──────────────────────┐  │
│  │   YAML   │  │   CLIPS Runtime      │  │
│  │ Compiler │──│                      │  │
│  └──────────┘  │  - Templates         │  │
│                │  - Working Memory     │  │
│  ┌──────────┐  │  - Forward Chaining  │  │
│  │   Fact   │──│  - Modules + Focus   │  │
│  │ Asserter │  │  - Functions         │  │
│  └──────────┘  └──────────────────────┘  │
│                                          │
│  ┌──────────┐  ┌──────────────────────┐  │
│  │  Audit   │  │   Attestation        │  │
│  │   Log    │  │   Service            │  │
│  └──────────┘  └──────────────────────┘  │
└──────────────────────────────────────────┘
         │                    │
    ┌────▼─────┐       ┌─────▼──────┐
    │ REST API │       │ Python SDK │
    └──────────┘       └────────────┘
```

### Components

**YAML Compiler:** Translates YAML templates, rules, modules, and functions into CLIPS constructs (`deftemplate`, `defrule`, `defmodule`, `deffunction`). Handles type checking, variable binding, slot validation, and module assignment at compile time. Raw CLIPS passthrough supported for all construct types.

**CLIPS Runtime:** Embedded CLIPS engine (via `clipspy`). Manages working memory, template registry, module focus stack, rule activation, and forward-chaining inference. Stateful within a session, stateless across sessions.

**Fact Asserter:** Typed fact insertion validated against loaded templates. Supports bulk assertion, working memory queries, and fact retraction.

**Audit Log:** Every evaluation produces an immutable record: input facts, modules traversed, rules fired, decision, reasoning trace, duration. Structured JSON, append-only.

**Attestation Service:** Signs evaluation results with Ed25519 keys. Produces JWT tokens that third parties can verify. Optional — disabled by default, enabled for governance use cases.

**REST API:** FastAPI-based server for language-agnostic access. Accepts facts and rule references, returns decisions with traces.

**Python SDK:** Native Python interface. `uv add fathom-rules`. Zero external dependencies beyond `clipspy`.

---

## YAML Rule Language

### Supported Conditions

```yaml
# Comparison operators
field: equals(value)
field: not_equals(value)
field: greater_than(value)
field: less_than(value)
field: in([value1, value2])
field: not_in([value1, value2])
field: contains(substring)
field: matches(regex_pattern)

# Classification-aware operators (for Bosun/Nautilus use cases)
field: below(classification_level)
field: meets_or_exceeds(classification_level)
field: within_scope(scope_definition)

# Temporal operators (requires working memory)
field: changed_within(duration)
field: count_exceeds(threshold, window)
field: rate_exceeds(threshold, window)

# Cross-fact references
field: $other_fact.field
```

### Supported Actions

```yaml
then:
  action: allow | deny | escalate | scope | route
  reason: "Human-readable explanation with {variable} interpolation"
  log: none | summary | full
  notify: [channel_list]
  attestation: true | false
  metadata:
    key: value
```

### Rule Packs

Pre-built rule collections for common use cases:

- `fathom-nist-800-53` — Access control, audit, information flow
- `fathom-hipaa` — PHI handling, minimum necessary, breach triggers
- `fathom-cmmc` — CMMC Level 2+ controls for agent operations
- `fathom-owasp-agentic` — OWASP Agentic Top 10 risk mitigations

Rule packs are versioned and composable. Install via `uv add fathom-nist-800-53`.

---

## Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| Single rule evaluation | < 100µs | Comparable to OPA/Cedar |
| 100-rule evaluation | < 500µs | CLIPS rete algorithm scales well |
| Fact assertion | < 10µs | Direct working memory insertion |
| YAML compilation | < 50ms | One-time at load |
| Working memory (1000 facts) | < 5MB | Bounded per session |

---

## Integration Points

### As a library

```python
from fathom import Engine

engine = Engine.from_rules("rules/")
engine.assert_fact("agent", {...})
result = engine.evaluate()
```

### As a sidecar

```bash
docker run -p 8080:8080 -v ./rules:/rules kraken/fathom:latest
```

```bash
curl -X POST localhost:8080/v1/evaluate \
  -d '{"facts": [...], "ruleset": "access-control"}'
```

### As an MCP tool

```python
from fathom.integrations.mcp_server import FathomMCPServer

server = FathomMCPServer(rules_path="./rules")
server.run(transport="stdio")
# Any MCP-compatible agent can now call fathom.evaluate as a tool
```

### Framework adapters

- LangChain callback handler — shipped (`src/fathom/integrations/langchain.py`)
- CrewAI before-tool-call hook — shipped (`src/fathom/integrations/crewai.py`)
- OpenAI Agents SDK tool guardrail — shipped (`src/fathom/integrations/openai_agents.py`)
- Google ADK before-tool callback — shipped (`src/fathom/integrations/google_adk.py`)

---

## Relationship to Bosun and Nautilus

Fathom is the core runtime. Bosun and Nautilus are applications built on Fathom.

```
┌─────────────────────────────────────────┐
│  Bosun (Agent Governance)               │
│  - Fleet behavioral analysis            │
│  - Trajectory violation detection       │
│  - Compliance attestation               │
├─────────────────────────────────────────┤
│  Nautilus (Intelligent Data Broker)     │
│  - Multi-source data routing            │
│  - Classification-aware scoping         │
│  - Purpose-bound access control         │
├─────────────────────────────────────────┤
│  Fathom (Expert System Runtime)         │
│  - Five primitives: Templates, Facts,   │
│    Rules, Modules, Functions            │
│  - CLIPS-based forward-chain evaluation │
│  - Working memory + inference           │
│  - Audit logging + attestation          │
└─────────────────────────────────────────┘
```

Fathom can be used standalone for any deterministic reasoning need. Bosun and Nautilus add domain-specific rule packs, integrations, and UIs on top of the same engine.

---

## Development Roadmap

Status legend: ✅ shipped · 🚧 partial · ⏳ planned · 🔁 in-progress

### Phase 1 — Core Runtime — **Status: ✅ Complete**
- [x] ✅ Project scaffolding with uv (`pyproject.toml`, `fathom-rules` v0.3.0)
- [x] ✅ CLIPS embedding via `clipspy` with session management (`src/fathom/engine.py`)
- [x] ✅ YAML template compiler → `deftemplate` (`src/fathom/compiler.py`)
- [x] ✅ YAML rule compiler → `defrule` (core operators + salience)
- [x] ✅ YAML module compiler → `defmodule` with focus stack control
- [x] ✅ YAML function compiler → `deffunction` (classification + temporal)
- [x] ✅ Fact assertion with template validation, bulk assert, query, retract (`src/fathom/facts.py`)
- [x] ✅ Working memory query API (inspect without triggering evaluation)
- [x] ✅ Evaluation with rule trace + module trace output (`src/fathom/evaluator.py`)
- [x] ✅ Audit log — structured JSON, append-only (`src/fathom/audit.py`)
- [x] ✅ Python SDK with clean public API (`fathom.Engine`, `AssertSpec`, `EvaluationResult`, etc.)
- [x] ✅ Test suite — **1361 tests passing** (target was 500+)
- [x] ✅ PyPI package via uv: `fathom-rules` (v0.3.0)

### Phase 2 — API and Integrations — **Status: ✅ Complete**
- [x] ✅ FastAPI REST server (`src/fathom/integrations/rest.py`)
- [x] ✅ Docker container image (`Dockerfile`, Debian slim + uv)
- [x] ✅ MCP tool server (`src/fathom/integrations/mcp_server.py`)
- [x] ✅ Attestation service — Ed25519 JWT signing (`src/fathom/attestation.py`)
- [x] ✅ First rule pack: `fathom-owasp-agentic` (`src/fathom/rule_packs/owasp_agentic/`)

**Phase 2 also shipped (not originally scoped):**
- [x] ✅ gRPC server with bearer-token auth (`src/fathom/integrations/grpc_server.py`)
- [x] ✅ REST auth middleware + path jailing (`src/fathom/integrations/auth.py`, `paths.py`)
- [x] ✅ Rule-assertion actions: `then.assert` + `bind` + `Engine.register_function()` (rule-assertions spec, merged PR #2)

### Phase 3 — Ecosystem — **Status: 🚧 Mostly complete, docs in progress**
- [x] ✅ LangChain adapter (`src/fathom/integrations/langchain.py`)
- [x] ✅ CrewAI adapter (`src/fathom/integrations/crewai.py`)
- [x] ✅ OpenAI Agents SDK adapter (`src/fathom/integrations/openai_agents.py`)
- [x] ✅ Google ADK adapter (`src/fathom/integrations/google_adk.py`)
- [x] ✅ Additional rule packs — NIST 800-53, HIPAA, CMMC (`src/fathom/rule_packs/`)
- [x] ✅ Classification-aware operators (`below`, `meets_or_exceeds`, `dominates`, compartments)
- [x] ✅ Temporal operators (`count_exceeds`, `rate_exceeds`, `changed_within`, `last_n`, `distinct_count`, `sequence_detected`)
- [x] ✅ CLI tooling: `validate`, `test`, `bench`, `info`, `repl` (`src/fathom/cli.py`)
- [ ] 🔁 Documentation site — scaffold at `docs/` with MkDocs Material; full developer-docs refresh tracked in `docs/superpowers/specs/2026-04-15-developer-docs-design.md`

### Phase 4 — Advanced — **Status: 🚧 Partial**
- [x] ✅ Cross-session fleet reasoning — shared working memory with Redis + Postgres backends (`src/fathom/fleet.py`, `fleet_redis.py`, `fleet_pg.py`)
- [x] ✅ Prometheus metrics export (`src/fathom/metrics.py`; `/metrics` endpoint on REST server)
- [x] ✅ Go SDK — `packages/fathom-go/` REST client (`client.go`) + 33 unit tests (`client_test.go`); proto aligned, Makefile fixed; not yet published to Go proxy
- [x] ✅ TypeScript SDK — `packages/fathom-ts/` `@fathom-rules/sdk` v0.1.0 with `FathomClient` + error hierarchy + OpenAPI-generated types; 34 vitest tests passing; `dist/` builds clean; not yet published to npm
- [ ] 🚧 Visual rule editor — `packages/fathom-editor/` stub (React 19 + Vite 7 + pnpm); components exist (`RuleTree`, `ConditionBuilder`, `TestRunner`) but not production-ready

### Roadmap deltas since design was written

- **gRPC server** added to Phase 2 (not in original design; companion to REST).
- **Auth + path-jailing** added to Phase 2 (production-hardening not originally scoped).
- **Rule-assertion actions** (`then.assert` + `bind` + `register_function`) added via separate `rule-assertions` spec.
- **Fleet reasoning** moved from Phase 4 to Phase 3 (shipped earlier than planned).
- **Documentation site** deferred within Phase 3 and expanded into a dedicated full-refresh project (dev-docs spec, 2026-04-15).

### Known issues from latest code review (see `REVIEW.md`)

- **M1** — version skew between `pyproject.toml` and `__init__.py` (resolved by 0.3.0 bump; gate to prevent recurrence is Wave 0 of dev-docs plan).
- **M2** — ~~`protos/fathom.proto` `go_package` ≠ `packages/fathom-go/go.mod` module path~~ Resolved: proto `go_package` aligned; Makefile output path fixed to `./proto`.
- **m3** — ~~silent slot-drop in `ConditionEntry(slot=..., test=...)`~~ Resolved: model validator at `models.py:165-170` rejects at load time.
- **m6** — ~~missing E2E coverage for `ConditionEntry.test`~~ Resolved: `TestConditionEntryTestField` in `test_integration.py` exercises YAML-loaded test CE through evaluate.

---

## Open Source Strategy

- **License:** MIT
- **Core principle:** Fathom itself is fully open source with no feature gating. Commercial value comes from Bosun and Nautilus (which may have open-core or commercial licensing) and from Kraken's professional services.
- **Community:** GitHub Discussions for support, Issues for bugs, PRs welcome with CLA.
- **Blog cadence:** Technical post every 2 weeks during Phase 1-2 covering design decisions, benchmarks, and CLIPS internals.