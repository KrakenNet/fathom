---
title: Hello-world policy
summary: Install Fathom, write a template and a rule in YAML, evaluate a fact, and inspect the evaluation result.
audience: [app-developers, rule-authors]
diataxis: tutorial
status: stable
last_verified: 2026-06-05
sources:
  - src/fathom/engine.py
  - src/fathom/compiler.py
  - src/fathom/models.py
---

# Hello-world policy

In this tutorial you'll install Fathom, define one template and one rule in YAML, load them into an engine, assert a fact, and read the evaluation result that comes back.

## 1. Install

```bash no-verify
pip install fathom-rules
```

## 2. Define a template

A template is the schema for a fact. Save this as `agent.yaml`:

```yaml
templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
      - name: clearance
        type: symbol
        required: true
        allowed_values: [public, confidential, secret]
```

## 3. Define a module


Rules in Fathom must belong to a named module so that the engine knows how to prioritize them.
`Compiler.compile_module` (in `src/fathom/compiler.py`) emits the CLIPS `defmodule` construct; modules are
loaded into the engine with `Engine.load_modules`.

Save as `modules.yaml`:
```yaml
modules:
  - name: governance
    description: Access-control governance layer
focus_order:
  - governance
```

## 4. Define a rule

Save this as `rules.yaml`:

```yaml
ruleset: demo
version: "1.0"
module: governance
rules:
  - name: allow-public
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: "equals(public)"
    then:
      action: allow
```

## 5. Load and evaluate

```python
from fathom.engine import Engine

engine = Engine()
engine.load_templates("agent.yaml")
engine.load_modules("modules.yaml")
engine.load_rules("rules.yaml")

engine.assert_fact("agent", {"id": "a-1", "clearance": "public"})
result = engine.evaluate()

print(result.decision)      # -> "allow"
print(result.rule_trace)    # -> [governance::"allow-public"]
```

The `no-verify` tag skips snippet execution because the install step and file paths aren't part of the test harness. The engine calls themselves are verified in [working memory](working-memory.md), which builds on this example with a real in-memory path.

## What just happened?

- Fathom compiled your YAML to CLIPS constructs via `fathom.compiler.Compiler` and loaded them into an embedded CLIPS environment.
- Your fact matched the condition `clearance == public`, the rule fired, and the rule's `then.action: allow` became the decision on the evaluation result.
- The `EvaluationResult` captures which rules fired (`rule_trace`), the final `decision`, and the evaluation duration — see [Audit & Attestation](../concepts/audit-attestation.md).

## Next

- [Modules & salience](modules-and-salience.md) — add a deny rule with lower salience so it fires last and wins.
