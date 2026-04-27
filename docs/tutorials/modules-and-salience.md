---
title: Modules & salience
summary: Use modules and salience to build a fail-closed policy where deny always overrides allow.
audience: [app-developers, rule-authors]
diataxis: tutorial
status: stable
last_verified: 2026-04-27
sources:
  - src/fathom/models.py
  - src/fathom/compiler.py
  - src/fathom/engine.py
---

# Modules & salience

This tutorial builds on [Hello-world policy](hello-world.md). You will add a
deny rule alongside an allow rule, tune their salience so the deny always wins,
and confirm the fail-closed outcome.

## How salience and last-write-wins interact

Fathom compiles your YAML to CLIPS via `fathom.compiler.Compiler`. CLIPS fires
eligible rules in salience order — the **highest** salience rule fires **first**.
The `Evaluator` uses a **last-write-wins** strategy: the final
`__fathom_decision` fact asserted into working memory becomes the result that
`Engine.evaluate` returns as `EvaluationResult.decision`.

Put those two facts together and the fail-closed design becomes clear:

- Give the **allow** rule a **high** salience (e.g. 100) so it fires first.
- Give the **deny** rule a **low** salience (e.g. 10) so it fires after.
- Because the deny fact is written last, it overwrites the allow fact and wins.

`RuleDefinition.salience` (in `src/fathom/models.py`) is an `int` that defaults
to `0`. Any positive integer is valid.

## 1. Install

```bash no-verify
pip install fathom-rules
```

## 2. Define a template

Save as `agent.yaml`:

```yaml no-verify
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

Rules in Fathom must belong to a named module. `Compiler.compile_module`
(in `src/fathom/compiler.py`) emits the CLIPS `defmodule` construct; modules are
loaded into the engine with `Engine.load_modules`.

Save as `modules.yaml`:

```yaml no-verify
modules:
  - name: governance
    description: Access-control governance layer
focus_order:
  - governance
```

The optional `focus_order` list tells the engine which modules to activate and
in what order. Internally, `Compiler.compile_focus_stack` reverses this list
before building the CLIPS `(focus ...)` command because CLIPS uses push
semantics — the last module pushed ends up on top of the execution stack and
therefore runs first.

## 4. Define two rules with different salience

Both rules match an agent whose `clearance` slot equals `public`. The allow
rule fires first (`salience: 100`); the deny rule fires second (`salience: 10`)
and overwrites the allow decision via last-write-wins.

Save as `rules.yaml`:

```yaml no-verify
module: governance
rules:
  - name: allow-public
    salience: 100
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: "equals(public)"
    then:
      action: allow

  - name: deny-public
    salience: 10
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: "equals(public)"
    then:
      action: deny
      reason: "Public clearance is not sufficient"
```

## 5. Load, assert, and evaluate

The Python block below writes the three YAML definitions to a temporary
directory, loads them in the required order (templates → modules → rules),
asserts a fact, and verifies the deny outcome.

```python
import pathlib, tempfile
from fathom.engine import Engine

TEMPLATES_YAML = """
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
"""

MODULES_YAML = """
modules:
  - name: governance
    description: Access-control governance layer
focus_order:
  - governance
"""

RULES_YAML = """
module: governance
rules:
  - name: allow-public
    salience: 100
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: "equals(public)"
    then:
      action: allow

  - name: deny-public
    salience: 10
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: "equals(public)"
    then:
      action: deny
      reason: "Public clearance is not sufficient"
"""

with tempfile.TemporaryDirectory() as tmp:
    d = pathlib.Path(tmp)
    (d / "agent.yaml").write_text(TEMPLATES_YAML)
    (d / "modules.yaml").write_text(MODULES_YAML)
    (d / "rules.yaml").write_text(RULES_YAML)

    engine = Engine()
    engine.load_templates(str(d / "agent.yaml"))
    engine.load_modules(str(d / "modules.yaml"))
    engine.load_rules(str(d / "rules.yaml"))

    engine.assert_fact("agent", {"id": "a-1", "clearance": "public"})
    result = engine.evaluate()

    assert result.decision == "deny", f"expected deny, got {result.decision!r}"
    assert "governance::deny-public" in result.rule_trace, (
        f"rule_trace was {result.rule_trace}"
    )
```

Both rules match. `allow-public` fires first (salience 100) and writes an allow
fact. `deny-public` fires second (salience 10) and writes a deny fact. Because
the evaluator uses last-write-wins, the deny fact is the winner.

`result.decision` is `"deny"` and `result.rule_trace` includes
`"governance::deny-public"` (rules are recorded as `module::rule_name`).

## What just happened?

- **Modules** give rules a namespace. `Compiler.compile_module` emits
  `(defmodule governance (import MAIN ?ALL))` so governance rules can reference
  the internal decision template defined in `MAIN`.
- **Focus stack** — `Compiler.compile_focus_stack(["governance"])` produces
  `(focus governance)`. The evaluator pushes that onto the CLIPS agenda before
  running the forward-chain cycle.
- **Salience** controls firing order. Lower-salience rules fire later. The last
  decision fact written wins, so the deny rule at salience 10 overrides the
  allow rule at salience 100. This is the fail-closed design: allow rules can
  only succeed when no deny rule fires after them.
- `EvaluationResult.decision` and `EvaluationResult.rule_trace` (defined in
  `src/fathom/models.py`) capture the outcome.

## Next

- Explore [Working memory](working-memory.md) to see how facts persist across
  multiple evaluations within a session.
