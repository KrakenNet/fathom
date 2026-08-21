---
title: Module
summary: YAML reference for ModuleDefinition — the defmodule authoring surface.
audience: [rule-authors]
diataxis: reference
status: stable
sources:
  - src/fathom/models.py
  - src/fathom/compiler.py
  - src/fathom/evaluator.py
  - src/fathom/engine.py
last_verified: 2026-08-21
---

# Module

A **module** is a CLIPS namespace for rules. Every rule lives in exactly
one module, and Fathom's deterministic ordering is driven by the order
those modules are pushed onto the CLIPS focus stack. For the role of
modules among Fathom's five primitives, see
[Five Primitives](../../concepts/five-primitives.md); for the focus-stack
mechanics at evaluation time, see
[Runtime & Working Memory](../../concepts/runtime-and-working-memory.md).

## Top-level fields — `ModuleDefinition`

| Field         | Type    | Default | Required | Description                                                                                                                  |
|---------------|---------|---------|----------|------------------------------------------------------------------------------------------------------------------------------|
| `name`        | `str`   | —       | yes      | CLIPS identifier. Must match `^[A-Za-z_][A-Za-z0-9_\-]*$`. Emitted as `(defmodule <name> …)`.                                |
| `description` | `str`   | `""`    | no       | Author-facing prose. Not emitted to CLIPS.                                                                                    |
| `priority`    | `int`   | `0`     | no       | Author-facing metadata. **Not emitted to CLIPS** and **not used to drive the focus stack** in the current runtime (see below). |

The `name` field is validated by `_name_must_be_clips_ident` at model
construction and re-checked (for emptiness) by `compile_module`.

## CLIPS emission

`compile_module` (in `src/fathom/compiler.py`) emits a single-line
`defmodule` form. Every non-`MAIN` module imports `?ALL` from `MAIN` so
that templates declared in `MAIN` — including the built-in
`__fathom_decision` decision template — are visible to rules in the
module.

### YAML input

```yaml
modules:
  - name: access-control
    description: Core access decisions.
    priority: 100
```

### CLIPS output

```
(defmodule access-control (import MAIN ?ALL))
```

### Emission rules

1. The emitted form is exactly
   `(defmodule <name> (import MAIN ?ALL))` — one line, no variations
   for `description` or `priority`.
2. `description` is never emitted. It exists for authoring only.
3. `priority` is never emitted as a CLIPS construct attribute. CLIPS has
   no module-level priority concept; module ordering is done by the
   focus stack, not by attributes on `defmodule`.
4. An empty `name` at compile time raises `CompilationError` with
   `construct="module:<empty>"`.

## Priority and the focus stack

`ModuleDefinition.priority` is a stored integer (default `0`) that the
runtime **does not read** when setting focus. Focus order is driven by
the explicit `focus_order:` list at the top of the module YAML file (or
by a later `Engine.set_focus(...)` call). When no `focus_order:` is
given anywhere in the pack, `load_modules` falls back to the order the
modules were declared in — see
[When `focus_order` is omitted](#when-focus_order-is-omitted).

At evaluation time, `_setup_focus_stack` in `src/fathom/evaluator.py`
emits a single `(focus ...)` eval listing the modules in the order they
appear in `focus_order` — `(focus A B C)` gives A the focus first and
queues B and C behind it. `priority` is never consulted during this step.

Every module in the list runs: CLIPS drains the first module's agenda,
then moves to the next. A decision in an earlier module does **not**
short-circuit the ones after it. Because the evaluator is
last-write-wins, the module you list **last** is the one whose decision
the caller sees — so a guardrail module belongs at the end of
`focus_order`, not the start.

What `priority` is actually used for today:

- It is surfaced by `fathom inspect` as metadata for each loaded
  module (see `src/fathom/cli.py`).
- It is preserved on the `ModuleDefinition` in the engine's
  `module_registry` for external tooling.

See [Runtime & Working Memory](../../concepts/runtime-and-working-memory.md)
for the full focus-stack mechanics.

### When `focus_order` is omitted

A pack that declares modules and no `focus_order:` is focused on every
declared module, in declaration order: files in load order, and within a
file the order the `modules:` list is written. `Engine.load_modules`
applies this once, after every module file is parsed, and only if
nothing has set a focus order already — so a `focus_order:` in any file,
or an earlier `Engine.set_focus(...)`, wins outright.

The fallback exists because omitting `focus_order:` is not a request for
a different order; it is the absence of a request. CLIPS drains only the
agenda of the module that holds the focus, so with no focus set at all,
rules scoped to a declared module never fire and the caller silently
receives the default decision — a wrong answer rather than an error.

Declaration order is not a substitute for stating the order you want.
It is stable, but it moves when you add a module or rename a file, and
because the evaluator is last-write-wins, the module that lands last
writes the decision. Any pack whose modules must run in a particular
sequence should say so with `focus_order:`.

### Declaring focus order

```yaml
modules:
  - name: classification
    description: Label-derivation rules.
  - name: access-control
    description: Core access decisions.
    priority: 100   # metadata only — does not affect ordering

focus_order:
  - classification
  - access-control
```

Here `classification` runs first because it appears first in
`focus_order`, and `access-control` runs after it — so `access-control`
writes the final decision. The `priority: 100` is informational and does
not reorder anything.

## The MAIN module

`MAIN` is created implicitly by Fathom the first time `load_modules` is
called, via `(defmodule MAIN (export ?ALL))` (see `src/fathom/engine.py`).
Authors do not declare `MAIN` in YAML. All `deftemplate` constructs —
including the built-in `__fathom_decision` template that Fathom
installs at engine startup — live in `MAIN`, and every non-`MAIN`
module imports from it. Rules are scoped to a module by the `module:`
key on the enclosing `RulesetDefinition`; see [Rule](./rule.md) for the
rule emission.

## Validators

Pydantic-level rejections (raised at `ModuleDefinition(...)` or during
YAML load):

- `name` that does not match `^[A-Za-z_][A-Za-z0-9_\-]*$` →
  `ValueError` from `_name_must_be_clips_ident`.

Compile-time rejections (raised by `Compiler.compile_module`):

- `name` that is an empty string → `CompilationError` with
  `construct="module:<empty>"`.

Duplicate module names are rejected by `parse_module_file` (at YAML
load) and again by `Engine.load_modules` (across files), both as
`CompilationError`.

## What is not emitted

These YAML fields are accepted by the model but never appear in the
compiled CLIPS `defmodule`:

- `ModuleDefinition.description` — metadata only.
- `ModuleDefinition.priority` — metadata only; does not influence
  focus-stack ordering in the current runtime. Ordering comes from
  `focus_order:`, or from declaration order when that key is absent.

## See also

- [Five Primitives](../../concepts/five-primitives.md) — conceptual
  overview of templates, facts, rules, modules, and functions.
- [Runtime & Working Memory](../../concepts/runtime-and-working-memory.md)
  — focus-stack mechanics and the evaluation loop.
- [Rule](./rule.md) — how rules are scoped to a module via
  `RulesetDefinition.module`.
- [Template](./template.md) — why templates live in `MAIN`.
