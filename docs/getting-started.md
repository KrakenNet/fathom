---
title: Getting Started
sources:
  - pyproject.toml
  - src/fathom/engine.py
  - src/fathom/evaluator.py
  - src/fathom/models.py
last_verified: 2026-04-27
---

# Fathom -- Getting Started

Fathom is a deterministic reasoning runtime built on CLIPS via clipspy. Define rules in YAML, evaluate in microseconds, get auditable results with zero hallucinations.

## Installation

Requires Python 3.14 or later.

```bash
uv add fathom-rules
```

The only core dependency is `clipspy`. No other external packages are required.

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

## Write Your First Rule

Rules define pattern-matching logic that fires when facts match conditions. Create `rules/access-control.yaml`:

```yaml
ruleset: access-control
version: 1.0
module: governance

rules:
  - name: deny-insufficient-clearance
    description: "Deny access when agent clearance is below data classification"
    salience: 10
    when:
      agent:
        clearance: below($data.classification)
      data_request:
        as: $data
    then:
      action: deny
      reason: "Agent clearance '{agent.clearance}' insufficient for '{$data.classification}' data"
      log: full
```

`salience` controls firing priority -- higher values fire first. The evaluator uses last-write-wins on `__fathom_decision` facts, so the rule firing LAST wins. Deny rules should have LOWER salience than allow rules so they fire last and override any prior allow, enforcing fail-closed behavior.

## Set Up Modules

Modules namespace rules into isolated groups with controlled execution order. Create `modules.yaml`:

```yaml
modules:
  - name: classification
    description: "Classification and clearance evaluation"
    priority: 1

  - name: governance
    description: "Action-level governance rules"
    priority: 2

focus_order: [classification, governance]
```

The `focus_order` list determines evaluation sequence. Rules in `classification` fire before rules in `governance`. Each rule file declares which module it belongs to via the `module` field.

## Run Your First Evaluation

```python
from fathom import Engine

engine = Engine()
engine.load_templates("templates/")
engine.load_modules("modules.yaml")
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
print(result.reason)       # "Agent clearance 'secret' insufficient for 'top-secret' data"
print(result.rule_trace)   # ["classification::resolve-levels", "governance::deny-insufficient-clearance"]
print(result.module_trace) # ["classification", "governance"]
print(result.duration_us)  # 47
```

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
