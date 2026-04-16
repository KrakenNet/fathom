---
title: Working memory across evaluations
summary: Assert facts incrementally across multiple evaluate() calls and learn how to clear working memory when a session ends.
audience: [app-developers, rule-authors]
diataxis: tutorial
status: stable
last_verified: 2026-04-15
sources:
  - src/fathom/engine.py
  - src/fathom/models.py
---

# Working memory across evaluations

This tutorial builds on [Modules & salience](modules-and-salience.md). You will
assert facts in two separate steps, call `Engine.evaluate` after each step, and
confirm that the second evaluation sees facts from both steps. You will also
learn how to clear working memory when a session is done.

## Why this matters

Systems like OPA and Cedar are stateless: every evaluation starts from a blank
slate. Fathom is different — **facts asserted into a `Engine` instance persist
across `evaluate()` calls** for the lifetime of that instance. This is the
core design choice that makes Fathom useful for session-level reasoning: rules
can accumulate evidence across many events before reaching a conclusion.

A concrete example: an access-control policy that counts API calls made in the
last minute. Each `assert_fact` adds a new event to working memory. A rate rule
checks whether the total count exceeds a threshold. The count grows across
evaluations — no external state store required.

## How working memory works

When you call `engine.assert_fact(template, data)`, the fact is written into
the embedded CLIPS environment that `Engine` wraps. That environment is stateful:
facts remain until you explicitly retract them or reset the environment.
`engine.evaluate()` runs the forward-chain cycle against *all* facts currently
in working memory — not just the ones asserted since the last call.

## Demonstration

The block below proves persistence with a rule that requires **two facts** — one
asserted in the first step, one in the second. That combined rule can only fire
on the second evaluation because it needs both facts in working memory at once.

1. Loads a template and rules into a single `Engine`.
2. Asserts `agent a-1` (`role: "requester"`), evaluates — the combined rule
   cannot fire yet because `agent a-2` is missing; only the single-fact rule fires.
3. Asserts `agent a-2` (`role: "approver"`), evaluates again — *both* facts are
   now in working memory, the combined rule fires.

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
      - name: role
        type: symbol
        required: true
        allowed_values: [requester, approver]
"""

MODULES_YAML = """
modules:
  - name: access
    description: Access-control module
focus_order:
  - access
"""

RULES_YAML = """
module: access
rules:
  - name: allow-requester-alone
    salience: 10
    when:
      - template: agent
        conditions:
          - slot: role
            expression: "equals(requester)"
    then:
      action: allow
      reason: "requester present"

  - name: allow-dual-approval
    salience: 20
    when:
      - template: agent
        conditions:
          - slot: role
            expression: "equals(requester)"
      - template: agent
        conditions:
          - slot: role
            expression: "equals(approver)"
    then:
      action: allow
      reason: "dual approval confirmed"
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

    # --- First evaluation: only the requester fact is in working memory ---
    engine.assert_fact("agent", {"id": "a-1", "role": "requester"})
    result1 = engine.evaluate()

    assert "access::allow-dual-approval" not in result1.rule_trace, (
        f"dual-approval should not fire yet, got {result1.rule_trace}"
    )

    # --- Second evaluation: approver fact is added; requester fact persists ---
    engine.assert_fact("agent", {"id": "a-2", "role": "approver"})
    result2 = engine.evaluate()

    # allow-dual-approval fires because BOTH facts are in working memory:
    # the requester fact asserted in step 1 is still present.
    assert "access::allow-dual-approval" in result2.rule_trace, (
        f"allow-dual-approval should fire on second evaluation, "
        f"got {result2.rule_trace}"
    )
    assert result2.reason == "dual approval confirmed", (
        f"unexpected reason: {result2.reason!r}"
    )
```

The key proof is `result2.rule_trace`: `allow-dual-approval` can only fire when
both a requester fact **and** an approver fact exist. The requester fact was
asserted in the first step, never retracted, and therefore still present when
the second evaluation runs. A stateless system would see only the approver fact
on the second call and the combined rule would never fire.

## Contrast with stateless systems

| | Fathom | OPA / Cedar |
|---|---|---|
| Facts between calls | Persist until retracted or reset | Discarded after each evaluation |
| Session-level accumulation | Built-in | Requires an external store |
| Rate / count policies | Native (working memory grows) | Must pass full history on every call |

## Clearing working memory

Two methods let you start fresh without constructing a new `Engine`:

### `engine.clear_facts()`

Retracts all user-asserted facts from every registered template. Internal CLIPS
facts (the decision template, `initial-fact`) are left intact. Rules and
templates remain loaded — only the data changes.

Use this when you want to start a new session but keep the same rule set.

```python no-verify
engine.clear_facts()
# Working memory is now empty; templates and rules are still loaded.
result = engine.evaluate()  # No facts → default decision ("deny")
```

### `engine.reset()`

Calls the underlying `clips.Environment.reset()`, which clears **all** facts
(including internal ones) and re-asserts `(initial-fact)`. The `__fathom_decision`
template is rebuilt automatically. Deftemplates, defmodules, and defrules survive
the reset — only facts are cleared.

Use this for a full session reset that mirrors starting a new CLIPS environment
while keeping compiled constructs.

```python no-verify
engine.reset()
```

### When to create a new `Engine`

If you need to change the rule set — load different templates, modules, or rules —
construct a new `Engine`. The current version does not support unloading individual
constructs. `clear_facts()` and `reset()` only affect data, not compiled constructs.

## What just happened?

- `Engine` wraps a single `clips.Environment` instance. That environment is
  stateful: `assert_fact` writes a CLIPS fact that persists until removed.
- `evaluate()` runs `env.run()` to quiescence each time. It does not reset the
  environment first, so all previously asserted facts participate in every run.
- `EvaluationResult.rule_trace` (defined in `src/fathom/models.py`) records
  every rule that fired during the run as `module::rule_name` strings.
- `clear_facts()` calls `FactManager.clear_all()`, which iterates the template
  registry and retracts each template's facts individually.
- `reset()` delegates to `clips.Environment.reset()`, which is the CLIPS standard
  reset — facts gone, constructs preserved.

## Next

- [Audit & Attestation](../concepts/audit-attestation.md) — every `evaluate()`
  call emits a structured JSON audit record; learn how to wire in a custom sink.
