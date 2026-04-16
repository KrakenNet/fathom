---
title: Fathom
sources:
  - pyproject.toml
  - src/fathom/__init__.py
  - README.md
  - design.md
last_verified: 2026-04-15
---

# Fathom

Fathom is a deterministic reasoning runtime for AI agents, built on CLIPS via
clipspy. Rules are authored in YAML, compiled to CLIPS constructs, and
evaluated in microseconds with auditable traces.

Current release: `fathom-rules` 0.3.0 (requires Python 3.14+).

## Start here

- [Getting Started](getting-started.md) — install, first template, first rule,
  first evaluation.
- [Tutorial 1 — Hello-world policy](tutorials/hello-world.md) — the same
  material, guided step by step.

## Documentation by quadrant

The docs follow the [Diátaxis](https://diataxis.fr) framework. Pick the
quadrant that matches what you're doing.

### Learn — Tutorials

- [Hello-world policy](tutorials/hello-world.md)
- [Modules and salience](tutorials/modules-and-salience.md)
- [Working memory across evaluations](tutorials/working-memory.md)

### Solve a task — How-to Guides

- [Writing rules](how-to/writing-rules.md)
- [Integrating with FastAPI](how-to/fastapi.md)
- [Using the CLI](how-to/cli.md)
- [Registering a Python function](how-to/register-function.md)
- [Loading a rule pack](how-to/load-rule-pack.md)
- [Embedding via SDK](how-to/embed-sdk.md)

### Understand — Concepts

- [Five Primitives](concepts/five-primitives.md)
- [Runtime and Working Memory](concepts/runtime-and-working-memory.md)
- [YAML Compilation](concepts/yaml-compilation.md)
- [Audit and Attestation](concepts/audit-attestation.md)
- [CLIPS Features Not in v1](concepts/not-in-v1.md)

### Look up — Reference

- YAML: [Template](reference/yaml/template.md) ·
  [Rule](reference/yaml/rule.md) ·
  [Module](reference/yaml/module.md) ·
  [Function](reference/yaml/function.md) ·
  [Fact](reference/yaml/fact.md)
- APIs: [REST](reference/rest/index.md) ·
  [gRPC](reference/grpc/index.md) ·
  [MCP Tools](reference/mcp/index.md)
- [CLI](reference/cli/index.md)
- SDKs: [Python](reference/python-sdk/index.md) ·
  [Go](reference/go-sdk/index.md) ·
  [TypeScript](reference/typescript-sdk/index.md)
- [Rule Packs](reference/rule-packs/owasp-agentic.md)
- [Planned Integrations](reference/planned-integrations.md)

## What is not in v1

Fathom v1 is forward-chaining only and deliberately narrow. Backward chaining,
COOL (CLIPS object system), and message handlers are out of scope for this
release. See [CLIPS Features Not in v1](concepts/not-in-v1.md) for the full
list and the rationale.
