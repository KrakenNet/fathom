---
title: Writing rules
summary: How to author a Fathom ruleset in YAML, covering patterns, conditions, actions, and salience.
audience: [rule-authors]
diataxis: how-to
status: stable
last_verified: 2026-05-01
sources:
  - src/fathom/models.py
  - src/fathom/compiler.py
---

# Writing rules

Fathom rules are YAML files that compile to CLIPS `defrule` constructs. This guide covers
the full structure of a ruleset file, each field that the compiler accepts, and the
validation constraints enforced by the Pydantic models.

## Rule skeleton

Every rule file is a single YAML document that matches the `RulesetDefinition` model
(`src/fathom/models.py`).

```yaml
ruleset: access-control          # unique name — CLIPS identifier chars only
version: "1.0"                   # free string; no runtime effect
module: governance               # CLIPS module all rules belong to

rules:
  - name: deny-low-clearance
    description: "Deny when agent clearance is below data classification"
    salience: 10
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: unclassified
    then:
      action: deny
      reason: "Clearance insufficient"
```

The four top-level keys map directly to `RulesetDefinition` fields:

| Field | Type | Notes |
|-------|------|-------|
| `ruleset` | string | CLIPS identifier — `[A-Za-z_][A-Za-z0-9_-]*` |
| `version` | string | Defaults to `"1.0"` |
| `module` | string | CLIPS identifier; routes rules to a CLIPS module |
| `rules` | list | One or more `RuleDefinition` objects |

Each rule inside `rules` is a `RuleDefinition` and must supply `name`, `when`, and `then`.
`description` and `salience` are optional (salience defaults to `0`).

## `when` clauses: `FactPattern`

Each entry in `when` is a `FactPattern` (`src/fathom/models.py`). It matches a single
fact type in working memory.

```yaml
when:
  - template: data-request       # name of the deftemplate to match
    alias: req                   # optional — bind the whole fact to a CLIPS variable
    conditions:
      - slot: action
        expression: read
```

| Field | Required | Notes |
|-------|----------|-------|
| `template` | yes | Must match a loaded `TemplateDefinition` name |
| `alias` | no | When set, the compiler emits `?alias <- (template ...)` |
| `conditions` | yes | List of `ConditionEntry` objects |

A rule with two `when` entries fires only when **both** facts exist simultaneously in
working memory — CLIPS evaluates the conjunction.

## `ConditionEntry` fields

`ConditionEntry` (`src/fathom/models.py`, lines 105–171) represents one slot constraint
inside a `FactPattern`. At least one of `expression`, `bind`, or `test` must be present.

### `slot` + `expression`: value match

Use `expression` to require an exact slot value (compiled to a CLIPS equality
constraint).

```yaml
conditions:
  - slot: status
    expression: active
```

`slot` is required when `expression` is set.

### `slot` + `bind`: capture a value

Use `bind` to capture a slot value into a CLIPS variable for use in other conditions or
the `then` block. The value **must start with `?`** — the validator rejects anything else.

```yaml
conditions:
  - slot: subject-id
    bind: "?sid"
```

`slot` is required when `bind` is set.

### `test`: standalone CLIPS expression

Use `test` for arbitrary CLIPS conditional elements — custom functions registered via
`Engine.register_function`, or any CLIPS built-in not in Fathom's operator allow-list.
The value **must be a parenthesized expression** (start with `(`, end with `)`).

```yaml
conditions:
  - test: "(my-fn ?sid)"
```

The compiler emits `(test (my-fn ?sid))` on the rule LHS after all slot patterns.

You can combine `bind` and `test` in the same `ConditionEntry` to both capture a slot
and run a test against it:

```yaml
conditions:
  - slot: subject-id
    bind: "?sid"
    test: "(> (string-length ?sid) 0)"
```

**Validator rules enforced by `ConditionEntry`:**

- `bind` must start with `?` — e.g. `?sid`, not `sid`.
- `test` must be a parenthesized CLIPS expression — e.g. `(my-fn ?sid)`.
- `slot` must be present when `expression` or `bind` is set.
- Setting `slot` alongside `test` alone (no `expression` or `bind`) is **rejected** —
  the compiler has no slot position to emit; either add `expression`/`bind` or drop
  `slot`.
- At least one of `expression`, `bind`, or `test` must be set.

## `then` block: `ThenBlock`

The `then` block is a `ThenBlock` (`src/fathom/models.py`). It declares the decision and
any side effects when the rule fires.

```yaml
then:
  action: deny
  reason: "Subject ?sid is not authorized"
  log: full
  notify: [security-ops]
  attestation: true
  metadata:
    control: AC-3
  assert:
    - template: audit-record
      slots:
        subject: "?sid"
        outcome: denied
```

| Field | Type | Notes |
|-------|------|-------|
| `action` | `ActionType` or null | The decision outcome (see below) |
| `reason` | string | Human-readable explanation; defaults to `""` |
| `log` | `LogLevel` | `none`, `summary` (default), or `full` |
| `notify` | list of strings | Channel names to notify |
| `attestation` | bool | Whether to produce an attestation token |
| `metadata` | dict | Arbitrary string key-value pairs |
| `scope` | string or null | Scope qualifier for `scope` actions |
| `assert` | list of `AssertSpec` | Facts to assert when the rule fires |

Either `action` or a non-empty `assert` list is required — a `ThenBlock` with neither
is rejected by the model validator.

Note: in YAML files use the key `assert`; in Python you may use the attribute name
`asserts` (the model sets `populate_by_name=True`).

### `assert` examples

`AssertSpec` (`src/fathom/models.py`) lets rules write new facts into working memory.
Slot values starting with `?` are emitted as CLIPS variable references; values starting
with `(` are emitted as CLIPS s-expressions; all other values are emitted as quoted
string literals.

```yaml
assert:
  - template: decision
    slots:
      subject: "?sid"          # ?-prefixed → CLIPS variable reference
      outcome: "denied"        # plain string → CLIPS quoted literal
      score: "(compute-score ?sid)"  # (...) → CLIPS s-expression
```

Validators on `AssertSpec`:

- `template` must be a valid CLIPS identifier.
- Slot names must be valid CLIPS identifiers.
- `?`-prefixed values must be valid CLIPS variable references (e.g. `?sid`).
- `(`-prefixed values must have balanced parentheses.

## Salience overview

Salience is an integer on each `RuleDefinition` that controls firing order within a
module. Higher salience fires first. When salience is omitted it defaults to `0`.

Under Fathom's last-write-wins convention for the `__fathom_decision` fact, the rule
that fires **last** sets the final decision. This means **deny rules should be given
lower salience** so they fire after allow rules and their outcome wins. See
[Modules and salience](../tutorials/modules-and-salience.md) for a full worked example
and focus-stack ordering.

## Action values

The `action` field accepts any value from the `ActionType` enum
(`src/fathom/models.py`):

| Value | Meaning |
|-------|---------|
| `allow` | Permit the request |
| `deny` | Reject the request |
| `escalate` | Route to a human or higher-authority system |
| `scope` | Narrow the permission to a specific scope |
| `route` | Redirect to an alternate handler or service |
