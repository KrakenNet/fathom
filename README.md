# Fathom

> A modern Python-first expert system runtime built on CLIPS. Define rules in YAML. Evaluate in microseconds. Zero hallucinations.

[![PyPI](https://img.shields.io/pypi/v/fathom-rules.svg)](https://pypi.org/project/fathom-rules/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)

**Current version:** 0.3.1

**License:** MIT

**Language:** Python 3.14+ (primary), Go and TypeScript SDKs in progress

**Package Manager:** uv

**Maintained by:** [Kraken Networks](https://github.com/KrakenNet)

---

## Why Fathom?

Every AI agent framework lets agents decide what to do by guessing. For most tasks, that's fine.

For some tasks, guessing is unacceptable:

- **Policy enforcement** — "Is this agent allowed to do this?" can't be a maybe.
- **Data routing** — "Which databases should this query hit?" can't hallucinate a source.
- **Compliance** — "Did this fleet operate within NIST 800-53 controls?" needs a provable answer.
- **Classification** — "What clearance level does this data require?" is not a prompt engineering problem.

Fathom provides **deterministic, explainable, auditable reasoning** using CLIPS — a battle-tested expert system — wrapped in a modern Python library with YAML-first rule authoring.

## Install

```bash
uv add fathom-rules
```

## Quick Start

```python
from fathom import Engine

engine = Engine()
engine.load_templates("templates/")
engine.load_rules("rules/")

engine.assert_fact("agent", {
    "id": "agent-alpha",
    "clearance": "secret",
    "purpose": "threat-analysis",
    "session_id": "sess-001",
})

engine.assert_fact("data_request", {
    "agent_id": "agent-alpha",
    "target": "hr_records",
    "classification": "top-secret",
    "action": "read",
})

result = engine.evaluate()
print(result.decision)       # "deny"
print(result.reason)         # "Agent clearance 'secret' insufficient for 'top-secret' data"
print(result.duration_us)    # 47
```

See the [Getting Started guide](docs/getting-started.md) for a full walkthrough.

## What Ships Today

Phase 1–3 of the roadmap are complete; Phase 4 is in progress. See [design.md](design.md) for the full roadmap with status.

**Core runtime (Python)**
- YAML compiler for templates, rules, modules, and functions
- Forward-chaining evaluation with rule + module traces
- Working memory persistence across evaluations within a session
- Classification-aware operators (`below`, `meets_or_exceeds`, `dominates`, compartments)
- Temporal operators (`count_exceeds`, `rate_exceeds`, `changed_within`, `last_n`, `distinct_count`, `sequence_detected`)
- Rule-assertion actions (`then.assert` + `bind`) and user-defined Python functions (`Engine.register_function`)
- Structured JSON audit log with append-only sinks
- Ed25519 attestation service for signed evaluation results
- Fleet reasoning with Redis and Postgres backends for shared working memory

**Integrations**
- **FastAPI REST server** with bearer-token auth and rule-path jailing
- **gRPC server** with bearer-token auth (see `protos/fathom.proto`)
- **MCP tool server** (`FathomMCPServer`) for agent discovery
- **LangChain adapter** callback handler
- **CLI** — `fathom validate`, `fathom test`, `fathom bench`, `fathom info`, `fathom repl`
- **Docker sidecar** (Debian slim + uv)
- **Prometheus metrics** export (`/metrics` endpoint)

**Rule packs**
- `fathom-owasp-agentic` — OWASP Agentic Top 10 mitigations
- `fathom-nist-800-53` — Access control, audit, information flow
- `fathom-hipaa` — PHI handling, minimum necessary, breach triggers
- `fathom-cmmc` — CMMC Level 2+ controls

**SDKs (in progress)**
- `fathom-go` — hand-written REST client (`packages/fathom-go/`); gRPC regeneration blocked on a `go_package` path fix
- `fathom-ts` — `@fathom-rules/sdk` v0.1.0 (`packages/fathom-ts/`); OpenAPI-generated client pending
- `fathom-editor` — React visual rule editor (`packages/fathom-editor/`); stub

## Core Primitives

| Primitive | Purpose | CLIPS Construct |
|-----------|---------|-----------------|
| **Templates** | Define fact schemas with typed slots | `deftemplate` |
| **Facts** | Typed instances asserted into working memory | working memory |
| **Rules** | Pattern-matching logic with conditions and actions | `defrule` |
| **Modules** | Namespace rules with controlled execution order | `defmodule` |
| **Functions** | Reusable logic for conditions and actions | `deffunction` |

## Key Differentiator: Working Memory

Unlike stateless policy engines (OPA, Cedar), Fathom maintains working memory across evaluations within a session:

- **Cumulative reasoning** — "This agent accessed PII from 3 sources — deny the 4th."
- **Temporal patterns** — "Denial rate spiked 400% in 10 minutes — escalate."
- **Cross-fact inference** — "Agent A passed data to Agent B, who is requesting external access — violation."

## Integration Shapes

**As a library**
```python
from fathom import Engine
engine = Engine.from_rules("rules/")
result = engine.evaluate()
```

**As a REST sidecar**
```bash
docker run -p 8080:8080 -v ./rules:/rules kraken/fathom:latest
curl -H "Authorization: Bearer $TOKEN" -X POST localhost:8080/v1/evaluate \
  -d '{"facts": [...], "ruleset": "access-control"}'
```

**As a gRPC sidecar**
```bash
# protos/fathom.proto — regenerate Go/TS clients from the proto
grpcurl -H "authorization: Bearer $TOKEN" \
  -d '{"facts": [...]}' localhost:50051 fathom.v1.Fathom/Evaluate
```

**As an MCP tool**
```python
from fathom.integrations.mcp_server import FathomMCPServer
server = FathomMCPServer(engine)
server.serve()
```

## Documentation

Docs live under [`docs/`](docs/) and build with MkDocs Material (Diátaxis information architecture).

Entry points:
- [Getting Started](docs/getting-started.md)
- [Tutorials](docs/tutorials/index.md)
- [How-to Guides](docs/how-to/index.md)
- [Concepts](docs/concepts/index.md)
- [Reference](docs/reference/index.md)

## Performance Targets

| Operation | Target |
|-----------|--------|
| Single rule evaluation | < 100µs |
| 100-rule evaluation | < 500µs |
| Fact assertion | < 10µs |
| YAML compilation | < 50ms |

## Related Projects

- **Bosun** — Agent governance built on Fathom (fleet analysis, compliance attestation)
- **Nautilus** — Intelligent data broker built on Fathom (multi-source routing, classification-aware scoping)

## Development

```bash
git clone https://github.com/KrakenNet/fathom.git
cd fathom
uv sync
uv run pytest           # 1361 tests
uv run mkdocs serve     # docs preview
```

Run the live REST server locally:
```bash
uv run uvicorn fathom.integrations.rest:app --reload
```

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

MIT — see [LICENSE](LICENSE) for details.

---

Maintained by [Kraken Networks](https://github.com/KrakenNet) · [krakennetworks.com](https://krakennetworks.com) · [krakn.ai](https://krakn.ai)
