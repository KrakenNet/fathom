---
title: Five Primitives
summary: Templates, Facts, Rules, Modules, Functions — the author-level vocabulary Fathom compiles to CLIPS.
audience: [rule-authors, app-developers]
diataxis: explanation
status: stable
last_verified: 2026-05-01
sources:
  - src/fathom/models.py
  - src/fathom/compiler.py
  - src/fathom/engine.py
---

# Five Primitives

Fathom's YAML author surface is deliberately small: five primitives that compile
one-to-one to CLIPS constructs running inside clipspy. Four of them —
**Templates**, **Rules**, **Modules**, **Functions** — are written by hand. The
fifth, **Facts**, is a runtime artifact: facts are instances of a template,
asserted by your application or by rules as they fire. Understanding where each
primitive lives (author-time vs. runtime) and what it becomes in CLIPS is the
shortest path to a working mental model of the engine.

The rest of this page walks the five in the order the engine loads them
(`templates → modules → functions → rules` — see
`src/fathom/engine.py`, `Engine.from_rules`, lines 452–489) and closes with how
they fit together at evaluate time.

## Templates

A **template** declares the schema of a kind of fact: its name, its slots, and
per-slot typing and constraints. Templates are the only way to introduce a new
fact shape; everything downstream — rule patterns, asserts, working memory —
references a template by name.

The `TemplateDefinition` model (`src/fathom/models.py`) carries:

- `name` — a CLIPS identifier.
- `description` — free prose for generated reference docs.
- `slots` — a list of `SlotDefinition`, each with a `name`, a `type`, and
  optional `required`, `allowed_values`, and `default`.
- `ttl` — optional integer time-to-live used by the fact manager.
- `scope` — `"session"` (default) or `"fleet"`.

Slot types come from the `SlotType` enum and map directly to CLIPS primitives:
`string`, `symbol`, `float`, `integer`.

A minimal template:

```yaml
templates:
  - name: session
    description: An authenticated session.
    slots:
      - { name: session_id, type: string, required: true }
      - { name: user_role,  type: symbol, allowed_values: [admin, user, guest] }
      - { name: created_at, type: integer }
```

The compiler (`compile_template`, `src/fathom/compiler.py` around line 90)
emits a single CLIPS construct scoped to the `MAIN` module:

```clips
(deftemplate MAIN::session
    (slot session_id (type STRING))
    (slot user_role  (type SYMBOL) (allowed-symbols admin user guest))
    (slot created_at (type INTEGER)))
```

Templates always live in `MAIN` so that any user-defined module can reference
them after importing `MAIN` (see Modules, below).

## Facts

A **fact** is a runtime instance of a template — the data rules actually match
against. Facts are **not** authored in YAML alongside the other primitives;
they enter working memory at runtime in one of three ways:

- The host program calls `Engine.assert_fact(template, data)` to inject facts
  from request payloads, database rows, or upstream events.
- A rule's `then:` block includes an `assert:` clause, which the compiler
  represents as an `AssertSpec` (`src/fathom/models.py`). When the rule fires,
  CLIPS materializes the spec into a new fact.
- A bundled rule pack may ship sample facts to load via `load_rules`-adjacent
  helpers, but these are still asserted at runtime, not compiled.

Two types describe facts at different lifecycle stages:

- **`AssertSpec`** — the *compile-time* description of a fact a rule will
  assert. Its `slots` are `dict[str, str]` because the values are CLIPS source
  text: either a literal, or a `?var` bound on the LHS and spliced into the
  RHS by the compiler.
- **`AssertedFact`** — a *runtime* snapshot captured for audit, with
  `slots: dict[str, Any]` because the values have been materialized by CLIPS
  back into Python types (int, str, symbol, float).

Facts in working memory persist across `Engine.evaluate` calls within the same
`Engine` instance. This is the core difference between Fathom and stateless
policy engines: forward chaining can accumulate derived facts over many
evaluations until you explicitly retract them or the session ends. The Runtime
concept page goes into the focus stack and working-memory lifecycle in more
detail.

## Rules

A **rule** is a pattern-action pair: a list of fact patterns to match, and a
`then` block describing what to do when the LHS becomes satisfied. The
`RuleDefinition` model (`src/fathom/models.py`) carries `name`, `description`,
`salience`, `when`, and `then`; rules are grouped into a `RulesetDefinition`
that declares which `module` they belong to.

Each entry in `when` is a `FactPattern` — a template name plus a list of
`ConditionEntry` items. A condition entry has four shapes, and which slots you
set determines which one the compiler emits:

1. **`slot` + `expression`** — constrain a slot with an operator (`== "admin"`,
   `> 3`, etc.).
2. **`slot` + `bind`** — capture the slot's value into a `?var` for use
   elsewhere in the rule.
3. **`slot` + `bind` + `expression`** — bind and constrain in one step.
4. **`test` alone** — a raw parenthesized CLIPS expression emitted verbatim as
   a `(test …)` conditional element; the escape hatch for calling
   Python-registered functions or CLIPS built-ins outside the allow-list.

The `then` block is a `ThenBlock` with an `action` (one of `allow`, `deny`,
`escalate`, `scope`, `route`), a `reason`, a `log` level, optional `notify`,
`attestation`, `metadata`, and `scope`, and an `asserts` list (spelled
`assert:` in YAML) of `AssertSpec` entries for facts the rule should add to
working memory when it fires.

The compiler (`compile_rule`, `src/fathom/compiler.py` around line 137) emits
a rule qualified by the owning module:

```clips
(defrule governance::deny-low-clearance
    (declare (salience -10))
    (session (user_role ?role))
    (test (eq ?role guest))
    =>
    (assert (__fathom_decision (action deny) (reason "guest role"))))
```

### Salience

`salience` is an integer; higher values fire first within a module. Fathom's
decision model is **last-write-wins**: whichever decision fact is written last
becomes the result. To make denial fail-closed by default, `deny` rules
conventionally get **lower** salience than `allow` rules so they fire *after*
allow and overwrite the allow decision. The `runtime-and-working-memory.md`
concept page and [`../how-to/writing-rules.md`](../how-to/writing-rules.md)
cover the convention and its trade-offs in depth.

## Modules

A **module** is a namespace for rules. The `ModuleDefinition` model
(`src/fathom/models.py`) is intentionally tiny — `name`, `description`, and a
`priority` integer — because a module's job at author time is just to exist
and let rules declare their home.

`compile_module` (`src/fathom/compiler.py` line 352) emits:

```clips
(defmodule governance (import MAIN ?ALL))
```

Every non-MAIN module imports all exports from `MAIN`, which is why templates
declared in `MAIN` are visible everywhere. Modules never contain inline rules
in Fathom's YAML surface; a rule's membership is set by the `module:` field on
its enclosing `RulesetDefinition`, and `compile_rule` prefixes the emitted
defrule name with `<module>::`.

At runtime, modules are the unit of ordered evaluation: the CLIPS **focus
stack** controls which module's agenda is active, and `load_modules` honours
an optional `focus_order` in the module file. Ordering, the focus stack, and
how `(focus …)` interacts with `allow`/`deny` salience belong in the Runtime
concept page.

## Functions

A **function** is a named, pure-ish computation callable from rule LHS `test`
CEs or from slot expressions. The `FunctionDefinition` model
(`src/fathom/models.py`) has `name`, `description`, `params`, an optional
`hierarchy_ref`, and a `type` field with three values:

- **`classification`** — generated from a `HierarchyDefinition` (e.g. a
  clearance ladder like `[public, confidential, secret, top-secret]`). Used
  for ordered-level comparisons; the `hierarchy_ref` points at the hierarchy
  the function is derived from.
- **`temporal`** — a time-window or decay helper generated from the YAML spec.
- **`raw`** — an escape hatch: the `body` is emitted verbatim as CLIPS source,
  so you can write any `(deffunction …)` you want.

`compile_function` (`src/fathom/compiler.py` line 359) emits one or more
`(deffunction <name> …)` constructs.

A second path exists for host-language helpers: `Engine.register_function(name,
callable)` makes a Python callable visible to CLIPS under the given name, so
a rule's `test` CE can invoke it like any other function. See
[`../how-to/register-function.md`](../how-to/register-function.md) for the
contract and the supported parameter/return shapes.

## How they fit together

The primitives layer cleanly because their dependencies run in one direction.
At load time, `Engine.from_rules` (and the `load_*` methods on `Engine`) walk
the bundle in a fixed order so every construct has what it needs:

```
templates        (deftemplate MAIN::…)
   │
   ▼
modules          (defmodule … (import MAIN ?ALL))
   │
   ▼
functions        (deffunction … )
   │
   ▼
rules            (defrule <module>::… … => … )
```

- Templates come first so module-scoped rules can pattern-match on them.
- Modules come next because rules are emitted qualified by their module.
- Functions come before rules because `test` CEs and slot expressions may
  reference them.
- Rules come last; loading a rule whose module is not yet registered is a
  `CompilationError`.

At evaluate time the picture inverts: the host asserts facts, CLIPS matches
them against rule LHS patterns, the rule with the highest salience on the
active module's agenda fires, its `then` block emits a decision and any
`AssertSpec` facts, and those new facts feed further matches. Working memory
accumulates across `evaluate` calls on the same `Engine` until you retract or
discard the session.

## Related reading

- [Writing rules](../how-to/writing-rules.md) — field-by-field reference for
  `RulesetDefinition` and the salience/last-write-wins convention.
- [Registering a function](../how-to/register-function.md) — how host-language
  callables become available to rule LHS expressions.
- [YAML reference](../reference/yaml/index.md) — generated schema index for
  every primitive's YAML surface.
