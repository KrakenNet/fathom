---
title: Template
summary: YAML reference for TemplateDefinition — the deftemplate authoring surface.
audience: [rule-authors]
diataxis: reference
status: stable
sources:
  - src/fathom/models.py
  - src/fathom/compiler.py
  - src/fathom/facts.py
last_verified: 2026-04-15
---

# Template

A **template** declares the shape of a fact: its name and the typed slots
that facts of that kind carry. Templates compile to CLIPS `deftemplate`
constructs and live in the `MAIN` module regardless of which rule module
references them. For the conceptual role of templates among Fathom's five
primitives, see [Five Primitives](../../concepts/five-primitives.md).

## Top-level fields — `TemplateDefinition`

| Field         | Type                              | Default     | Required | Description                                                                                          |
|---------------|-----------------------------------|-------------|----------|------------------------------------------------------------------------------------------------------|
| `name`        | `str`                             | —           | yes      | CLIPS identifier. Must match `^[A-Za-z_][A-Za-z0-9_\-]*$`. Emitted as `(deftemplate MAIN::<name> …)`. |
| `description` | `str`                             | `""`        | no       | Author-facing prose. Not emitted to CLIPS.                                                           |
| `slots`       | `list[SlotDefinition]`            | —           | yes      | One or more slot definitions. Empty list is accepted by Pydantic but rejected at compile time.       |
| `ttl`         | `int \| None`                     | `None`      | no       | Fact-expiry metadata (seconds). Not emitted to CLIPS; reserved for runtime fact-expiry.              |
| `scope`       | `Literal["session", "fleet"]`     | `"session"` | no       | Authoring hint consumed by the fleet layer. Not emitted to CLIPS.                                    |

The `name` field is validated by `_name_must_be_clips_ident` at model
construction and re-checked (for emptiness) by `compile_template`.

## Slot fields — `SlotDefinition`

| Field            | Type                              | Default | Required | Description                                                                                                                       |
|------------------|-----------------------------------|---------|----------|-----------------------------------------------------------------------------------------------------------------------------------|
| `name`           | `str`                             | —       | yes      | Slot identifier. No regex validator is applied in the current model; the compiler emits it verbatim into `(slot <name> …)`.       |
| `type`           | `SlotType`                        | —       | yes      | One of `string`, `symbol`, `float`, `integer`. See [SlotType](#slottype-enum).                                                    |
| `required`       | `bool`                            | `False` | no       | If True, FactManager rejects asserts that omit this slot with a ValidationError (src/fathom/facts.py:274-283). Not emitted to CLIPS; the rule-RHS assert path bypasses this check because it doesn't run through FactManager._validate. |
| `allowed_values` | `list[str] \| None`               | `None`  | no       | Emitted only for `string` and `symbol` slots (see [`_CLIPS_ALLOWED_MAP`](#slottype-enum)). Silently ignored for numeric slots.    |
| `default`        | `str \| float \| int \| None`     | `None`  | no       | Emitted as `(default <value>)`. String defaults are CLIPS-quoted and escaped; numeric defaults are emitted raw.                   |

## SlotType enum

`SlotType` is a `StrEnum` with four members. The compiler maps each to a
CLIPS type keyword via `_CLIPS_TYPE_MAP` and — for the two symbolic
types — to an allowed-values directive via `_CLIPS_ALLOWED_MAP`.

| YAML value | CLIPS type keyword | Allowed-values directive |
|------------|--------------------|--------------------------|
| `string`   | `STRING`           | `allowed-strings`        |
| `symbol`   | `SYMBOL`           | `allowed-symbols`        |
| `float`    | `FLOAT`            | *(none — silently dropped)* |
| `integer`  | `INTEGER`          | *(none — silently dropped)* |

Source: `src/fathom/compiler.py` lines 29–40.

## CLIPS emission

`compile_template` (in `src/fathom/compiler.py`) emits a multi-line
`deftemplate` form. Every template is scoped to the `MAIN` module;
per-module scoping happens on `defrule`, not on `deftemplate`.

### YAML input

```yaml
templates:
  - name: access-request
    description: An agent's request to perform an action on a resource.
    slots:
      - name: subject
        type: symbol
      - name: action
        type: string
        allowed_values: [read, write, delete]
      - name: amount
        type: integer
        default: 0
```

### CLIPS output

```
(deftemplate MAIN::access-request
    (slot subject (type SYMBOL))
    (slot action (type STRING) (allowed-strings "read" "write" "delete"))
    (slot amount (type INTEGER) (default 0)))
```

### Emission rules

1. First line: `(deftemplate MAIN::<name>`.
2. Each slot is indented four spaces and wrapped as
   `(slot <name> <parts>)`.
3. Slot parts are emitted in this fixed order: `(type <CLIPS_TYPE>)`,
   `(<allowed-directive> <values>)` (string/symbol only), `(default <value>)`.
4. For `string` slots, each `allowed_values` entry and any string default
   is run through `_escape_clips_string` (backslash first, then
   double-quote) and wrapped in `"…"`. `symbol` allowed values are emitted
   unquoted.
5. Numeric defaults (`int`, `float`) are emitted via `str(slot.default)`
   with no quoting.
6. The template closes with `)` on its own line.

## Validators

Pydantic-level rejections (raised at `TemplateDefinition(...)` or during
YAML load):

- `name` that does not match `^[A-Za-z_][A-Za-z0-9_\-]*$` →
  `ValueError` from `_name_must_be_clips_ident`.

Compile-time rejections (raised by `Compiler.compile_template`):

- `name` that is an empty string → `CompilationError` with
  `construct="template:<empty>"`.
- `slots` is an empty list → `CompilationError` with
  `construct="template:<name>"`. Note: the `slots` field has no Pydantic
  `min_length=1` constraint, so an empty list passes model validation
  and only fails at compile time.

No validator is applied to `SlotDefinition.name`, `slot.allowed_values`,
or `slot.default` — the compiler trusts these fields and emits them
verbatim or via `_escape_clips_string`.

## What is not emitted

These YAML fields are accepted by the model but do not appear in the
compiled CLIPS `deftemplate`:

- `TemplateDefinition.description` — metadata only.
- `TemplateDefinition.ttl` — reserved for runtime fact-expiry; has no
  CLIPS counterpart. A template with `ttl: 300` emits the same
  `deftemplate` as one without.
- `TemplateDefinition.scope` — consumed by the fleet layer, not the
  compiler.
- `SlotDefinition.required` — the flag itself is not emitted to CLIPS.
  Runtime enforcement happens in `FactManager._check_required`
  (`src/fathom/facts.py:274-283`) on the SDK and REST paths, but it is
  not checked on the rule-RHS assert path.
- `SlotDefinition.allowed_values` on `float` or `integer` slots —
  silently dropped because these types have no entry in
  `_CLIPS_ALLOWED_MAP`.

If you need one of these to influence runtime behavior today, enforce it
in a rule (for example, an explicit `allowed-values`-style test CE for a
numeric slot) rather than relying on the template to do so.

## See also

- [Five Primitives](../../concepts/five-primitives.md) — conceptual
  overview of templates, facts, rules, modules, and functions.
- [YAML Compilation](../../concepts/yaml-compilation.md) — how YAML
  documents are loaded and compiled to CLIPS source.
- [Audit & Attestation](../../concepts/audit-attestation.md) — how
  asserted-fact slots surface in audit records.
