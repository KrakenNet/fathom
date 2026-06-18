---
title: Getting Started
sources:
  - pyproject.toml
  - src/fathom/engine.py
  - src/fathom/evaluator.py
  - src/fathom/models.py
last_verified: 2026-06-24
---

# Fathom -- Getting Started

Fathom is a deterministic reasoning runtime built on CLIPS via clipspy. Define rules in YAML, evaluate in microseconds, get auditable results with zero hallucinations.

## Installation

Requires Python 3.12 or later.

```bash
uv add fathom-rules
```

The core dependencies are `clipspy`, `pyyaml`, and `pydantic` -- they install automatically with the package. No other external packages are required.

## Create Your First Template

Templates define the shape of facts. Create a file `templates/agent.yaml`:

```yaml
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
```

Each slot has a `type` (`string`, `symbol`, `float`) and optional constraints (`required`, `allowed_values`, `default`). Fathom validates facts against these schemas at assertion time.

## Register a Classification Hierarchy

To compare clearance against data classification we need an ordered set of levels. Declare it in `hierarchies/clearance.yaml`:

```yaml
name: clearance
levels:
  - unclassified
  - cui
  - confidential
  - secret
  - top-secret
```

Then tie the hierarchy to the rule operators with a classification function in `functions/clearance.yaml`:

```yaml
functions:
  - name: clearance
    type: classification
    params: [a, b]
    hierarchy_ref: clearance.yaml
```

Loading this function registers the `below(...)`, `meets_or_exceeds(...)`, and `within_scope(...)` operators so rules can compare levels.

## Write Your First Rule

Rules define pattern-matching logic that fires when facts match conditions. Create `rules/access-control.yaml`:

```yaml
ruleset: access-control
version: "1.0"
module: governance

rules:
  - name: deny-insufficient-clearance
    description: "Deny access when agent clearance is below data classification"
    salience: 10
    when:
      - template: data_request
        alias: $data
        conditions:
          - slot: classification
            expression: "meets_or_exceeds(unclassified)"
      - template: agent
        conditions:
          - slot: id
            expression: "equals($data.agent_id)"
          - slot: clearance
            expression: "below($data.classification)"
    then:
      action: deny
      reason: "Agent clearance is below the data classification (no read up)"
      log: full
```

`when` is a **list** of fact patterns. Each pattern names a `template`, an optional `alias` (used for cross-fact references like `$data.classification`), and a list of `conditions`. Each condition pairs a `slot` with an `expression` -- a literal operator like `equals(...)` / `in([...])`, or a classification operator like `below(...)` / `meets_or_exceeds(...)`. **Pattern ordering matters**: the pattern that binds an alias must appear before any pattern that references it, so `data_request` (alias `$data`) is listed before the `agent` pattern that uses `$data.classification`.

`salience` controls firing priority -- higher values fire first. The evaluator uses last-write-wins on `__fathom_decision` facts, so the rule firing LAST wins. Deny rules should have LOWER salience than allow rules so they fire last and override any prior allow, enforcing fail-closed behavior.

## Set Up Modules

Modules namespace rules into isolated groups with controlled execution order. Create `modules/modules.yaml`:

```yaml
modules:
  - name: governance
    description: "Action-level governance rules"

focus_order: [governance]
```

The `focus_order` list determines evaluation sequence -- when you add more modules, rules in earlier modules fire before rules in later ones. Each rule file declares which module it belongs to via the `module` field.

## Run Your First Evaluation

```python
from fathom import Engine

engine = Engine()
engine.load_templates("templates/")
engine.load_modules("modules/")
engine.load_functions("functions/")
engine.load_rules("rules/access-control.yaml")

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
print(result.reason)       # "Agent clearance is below the data classification (no read up)"
print(result.rule_trace)   # ["governance::deny-insufficient-clearance"]
print(result.module_trace) # ["governance"]
print(result.duration_us)  # ~90 (microseconds; varies by machine)
```

`load_functions` must run before `load_rules`, because the rules reference the `below(...)` operator the classification function registers. The full project layout is:

```
templates/agent.yaml          agent + data_request schemas
hierarchies/clearance.yaml     ordered classification levels
functions/clearance.yaml       registers below(...) / meets_or_exceeds(...)
modules/modules.yaml           single 'governance' module
rules/access-control.yaml      the deny rule
```

The agent's `secret` clearance is below the request's `top-secret` classification, so the deny rule fires. If the agent's clearance instead met or exceeded the classification, no deny rule would match and the engine would fall through to its fail-closed default (`decision = "deny"`, `reason = "default decision (no rules fired)"`). To grant access you would add an explicit allow rule with higher salience -- see [example 03](https://github.com/KrakenNet/fathom/tree/main/examples/03-classification-blp) for the full read/write Bell-LaPadula pattern.

The result object contains five fields:

- `decision` -- the action taken (`allow`, `deny`, `escalate`, etc.)
- `reason` -- human-readable explanation with interpolated variables
- `rule_trace` -- ordered list of rules that fired, prefixed by module name
- `module_trace` -- ordered list of modules that were evaluated
- `duration_us` -- evaluation time in microseconds

Working memory persists across evaluations within a session. This enables cumulative reasoning ("agent accessed PII from 3 sources -- deny the 4th") and temporal patterns that stateless engines cannot express.

## Next Steps

- [Tutorial 1 -- Hello-world policy](tutorials/hello-world.md) -- the guided version of this same material
- [Five Primitives](concepts/five-primitives.md) -- templates, facts, rules, modules, and functions in depth
- [YAML Rule reference](reference/yaml/rule.md) -- operators, conditions, actions, and rule packs
- [Runtime and Working Memory](concepts/runtime-and-working-memory.md) -- session state, queries, cumulative reasoning
- [Planned Integrations](reference/planned-integrations.md) -- library, sidecar, MCP tool, and framework adapters

## Do Not

- Do not skip template definitions and assert untyped facts -- Fathom validates at assertion time.
- Do not set deny rules to higher salience than allow rules -- deny must have lower salience so it fires last and wins under last-write-wins (fail-closed).
- Do not assume working memory resets between `evaluate()` calls within the same session -- it persists.
- Do not use raw CLIPS constructs when YAML equivalents exist -- YAML is the primary authoring interface.
