---
title: YAML Compilation
summary: How authored YAML becomes CLIPS source — parse, validate, compile — and why Pydantic sits in the middle as the safety boundary.
audience: [rule-authors, app-developers]
diataxis: explanation
status: stable
last_verified: 2026-04-15
sources:
  - src/fathom/compiler.py
  - src/fathom/models.py
---

# YAML Compilation

The [Five Primitives](./five-primitives.md) page describes *what* you author
in Fathom's YAML. The
[Runtime & Working Memory](./runtime-and-working-memory.md) page describes
*what happens* once the engine is running. This page is about the pipeline
in between: how a YAML file becomes the CLIPS source string that clipspy's
`env.build()` consumes.

## The pipeline in one picture

Compilation is three stages — **parse**, **validate**, **compile** —
with two models in between:

```
YAML text
  │  yaml.safe_load()       (parse)
  ▼
Python dicts / lists
  │  Pydantic validation    (validate)
  ▼
TemplateDefinition / RuleDefinition / ModuleDefinition / FunctionDefinition
  │  Compiler.compile_*     (compile)
  ▼
CLIPS source string
  │  env.build(...)
  ▼
Construct live in the CLIPS environment
```

Parsing is boring: `yaml.safe_load` turns text into nested Python
containers. Validation is where the interesting work happens — Pydantic
rejects malformed or unsafe input *before* any CLIPS source is generated.
Compilation is a string transform: each validated model goes through a
matching `Compiler.compile_*` method that returns a CLIPS construct as
text. The compiler never talks to CLIPS directly; the engine is what
hands the output to `env.build()`.

## Why Pydantic sits in the middle

Fathom emits CLIPS source as text. clipspy's `env.build()` takes a source
string and parses it — there is no structured builder API for assembling
a `deftemplate` piece by piece. Every name and every slot value Fathom
writes into that string has to be safe.

The Pydantic layer is where that safety is enforced. Two regexes in
`src/fathom/models.py` define the safe grammar:

- `_CLIPS_IDENT_RE = r"^[A-Za-z_][A-Za-z0-9_\-]*$"` — all identifiers
  (template names, rule names, module names, function names, slot names,
  and the `AssertSpec.template` field) must match this pattern.
- `_SLOT_VAR_RE = r"^\?[A-Za-z_][A-Za-z0-9_\-]*$"` — LHS bind variables
  and `?var` references inside `AssertSpec.slots` must match this pattern.

Two helpers apply them. `_validate_clips_ident(name, kind)` is called
from field validators on every identifier field — `TemplateDefinition.name`,
`RuleDefinition.name`, `ModuleDefinition.name`, `FunctionDefinition.name`,
`RulesetDefinition.ruleset`/`module`, and `AssertSpec.template`.
`_validate_slot_value(value)` inspects each value in `AssertSpec.slots`:
values starting with `?` must match `_SLOT_VAR_RE`; values starting with
`(` must be balanced s-expressions; plain string values are accepted
provided they contain no NUL bytes.

Invalid input produces a structured Pydantic error pointing at the
offending field. Valid input produces models the compiler can emit
without further escaping of names — only slot string *literals* need
quoting, because those are the only place user-supplied text lands
inside a CLIPS double-quoted string.

## What each YAML construct compiles to

Each top-level model has a dedicated `compile_*` method on `Compiler`.

`TemplateDefinition` → a `deftemplate` scoped to `MAIN`:

```clips
(deftemplate MAIN::session
    (slot session_id (type STRING))
    (slot user_role  (type SYMBOL) (allowed-symbols admin user guest)))
```

Emitted by `compile_template`. Templates always live in `MAIN` so every
module can see them via `(import MAIN ?ALL)`. Slot type and
allowed-value directives come from `_CLIPS_TYPE_MAP` and
`_CLIPS_ALLOWED_MAP`; string defaults are quoted and escaped.

`ModuleDefinition` → a `defmodule` that imports everything from `MAIN`:

```clips
(defmodule governance (import MAIN ?ALL))
```

Emitted by `compile_module`. `ModuleDefinition` carries a `priority`
integer consumed by focus-stack ordering at load time, not serialized
into the CLIPS source.

`RuleDefinition` → a `defrule` qualified by its owning module:

```clips
(defrule governance::deny-low-clearance
    (declare (salience -10))
    (session (user_role ?role))
    (test (eq ?role guest))
    =>
    (assert (__fathom_decision (action deny) (reason "guest role") ...)))
```

Emitted by `compile_rule(defn, module)`. A `(declare (salience N))` clause
appears only when `salience != 0`. LHS and RHS rendering are covered below.

`FunctionDefinition` → one or more `deffunction` constructs:

```clips
(deffunction MAIN::classification-rank (?level)
    (switch ?level
        (case public then 0)
        (case secret then 1)
        (default -1)))
```

Emitted by `compile_function`. The `type` field is a literal of
`"classification" | "temporal" | "raw"`. Classification functions come
from a `HierarchyDefinition` as a family of deffunctions (`<hier>-rank`,
`<hier>-below`, `<hier>-meets-or-exceeds`, `<hier>-within-scope`) plus
backward-compatible unscoped shims for the first hierarchy loaded.
Temporal functions are registered as Python externals by a later stage
and return an empty string here. Raw functions return `defn.body`
verbatim — the escape hatch for hand-written CLIPS.

## The LHS: fact patterns and condition entries

Every entry in a rule's `when` list is a `FactPattern`: one template name,
an optional `alias`, and a list of `ConditionEntry` items. The compiler
emits one parenthesized pattern per `FactPattern` on the rule's LHS.

A `ConditionEntry` has four shapes, enforced by the `model_validator` on
the model:

1. **`slot` + `expression`** — constrain a slot with an operator
   (`equals(admin)`, `greater_than(3)`, and so on).
2. **`slot` + `bind`** — capture the slot's value into a `?var` that peer
   conditions and the RHS can reference.
3. **`slot` + `bind` + `expression`** — bind and constrain in one step.
4. **`test` alone** — an already-parenthesized CLIPS expression, emitted
   verbatim as a `(test …)` conditional element.

`Compiler._compile_fact_pattern` walks the list into two buckets: slot
constraints (concatenated inside the fact pattern) and test CEs (appended
*after* all fact patterns, because CLIPS semantics require tests to
reference variables already bound by earlier patterns).
`_compile_condition` produces the per-slot string, including the
`?bind&<expr>` form when a condition both binds and constrains.

Shape 4 is the primary escape hatch on the LHS. A `test` entry lets a
rule call any CLIPS-visible function, including host-language callables
registered via `Engine.register_function`. See
[Registering a Python function](../how-to/register-function.md).

## The RHS: asserts and decisions

Every `AssertSpec` in `then.asserts` becomes one `(assert …)` form on the
rule's RHS. For each spec, the compiler emits:

```clips
(assert (<template> (<slot> <value>) (<slot> <value>) ...))
```

Slot values go through `Compiler._emit_slot_value`, which is a three-way
switch mirroring `_validate_slot_value`:

- Starts with `?` → emitted verbatim as a variable reference.
- Starts with `(` → emitted verbatim as an s-expression.
- Otherwise → emitted as a quoted, escaped CLIPS string literal.

This is why `AssertSpec.slots` is typed `dict[str, str]` even though the
materialized fact can hold ints, symbols, and floats at runtime: at
compile time the value *is* a fragment of CLIPS source.

If `then.action` is set, `_compile_action` prepends an `__fathom_decision`
assert before any user asserts. `action` is emitted as a SYMBOL
(unquoted); `reason` becomes a quoted literal, or a `(str-cat …)`
expression interpolating LHS binds when it contains `{variable}`
placeholders. The engine reads `__fathom_decision` facts back at the end
of `evaluate()` to determine the winning decision — see
[Runtime & Working Memory](./runtime-and-working-memory.md). Assert-only
rules (no `action`) skip the decision block entirely.

## Safety: why the validators matter

Because Fathom builds CLIPS source by string concatenation, a malicious
or accidental identifier like `"foo) (deftemplate evil"` would break out
of the enclosing construct. Substituted into `compile_template`, it would
produce two top-level constructs where the author wrote one:

```clips
(deftemplate MAIN::foo) (deftemplate evil
    (slot ...))
```

The Pydantic layer blocks this before the compiler runs.
`_validate_clips_ident` rejects anything outside
`[A-Za-z_][A-Za-z0-9_-]*`, and `_validate_slot_value` ensures that a
slot value starting with `(` is a balanced s-expression — so an attacker
cannot smuggle a `))` that terminates the surrounding assert form.

The general rule: **if it ends up as raw text in CLIPS source without
quoting, it goes through `_validate_clips_ident` or
`_validate_slot_value` first**. Identifier validation on
`AssertSpec.template` and every slot key inside `AssertSpec.slots`
closes the loop on the RHS.

## The raw escape hatch

Some things the YAML surface does not express directly — complex
deffunctions, custom conditional elements, CLIPS-side state machinery.
Two escape hatches exist, and both sit on the far side of the safety
validators on purpose.

`FunctionDefinition(type="raw", body=...)` emits arbitrary CLIPS
function source:

```yaml
functions:
  - name: my-helper
    type: raw
    params: ["?x"]
    body: |
      (deffunction MAIN::my-helper (?x)
          (+ ?x 1))
```

`compile_function` returns `defn.body` verbatim when `type == "raw"`.
The `params` field is informational in this path; the author owns the
entire deffunction source.

`ConditionEntry(test="(my-fn ?x)")` emits an arbitrary `(test …)` CE on
the LHS:

```yaml
rules:
  - name: flag-risky
    when:
      - template: session
        conditions:
          - slot: session_id
            bind: "?sid"
          - test: "(risk-score-exceeds ?sid 0.9)"
    then:
      action: deny
      reason: risky session
```

This is how you reach anything registered via `Engine.register_function`
or any CLIPS built-in outside Fathom's operator allow-list. The `test`
field is only checked for being a non-empty parenthesized expression;
the contents are not parsed. That is the point — it is the escape hatch
— and raw passthrough sidesteps the per-operator safety net. With the
hatch comes the author's responsibility for the CLIPS it emits.

## Loading order

Compiled constructs are loaded into the CLIPS environment in a fixed
order — templates, modules, functions, rules — reflecting the dependency
graph between primitives. See
[Runtime & Working Memory](./runtime-and-working-memory.md) for why this
order is the only one that works.

## Related reading

- [Five Primitives](./five-primitives.md) — what each YAML construct means
  before compilation.
- [Runtime & Working Memory](./runtime-and-working-memory.md) — what the
  compiled constructs do once loaded.
- [Registering a Python function](../how-to/register-function.md) — the
  companion to the `test` escape hatch on the LHS.
