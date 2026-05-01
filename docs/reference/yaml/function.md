---
title: Function
summary: YAML reference for FunctionDefinition and HierarchyDefinition — the deffunction authoring surface.
audience: [rule-authors]
diataxis: reference
status: stable
sources:
  - src/fathom/models.py
  - src/fathom/compiler.py
last_verified: 2026-05-01
---

# Function

A **function** exposes a CLIPS `deffunction` that rules may call from
either the LHS (inside a `test:` escape hatch) or the RHS. Fathom
recognizes three function subtypes: `classification` (emitted as a
family of rank/below/meets-or-exceeds/within-scope deffunctions driven
by a `HierarchyDefinition`), `raw` (the author-supplied CLIPS source
is emitted verbatim), and `temporal` (reserved — currently a stub).
For conceptual context see
[Five Primitives](../../concepts/five-primitives.md); for exposing
Python callables instead of authoring CLIPS, see
[Register a Python function](../../how-to/register-function.md).

## Top-level fields — `FunctionDefinition`

| Field           | Type                                             | Default            | Required | Description                                                                                                                                                            |
|-----------------|--------------------------------------------------|--------------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `name`          | `str`                                            | —                  | yes      | CLIPS identifier. Must match `^[A-Za-z_][A-Za-z0-9_\-]*$` (validated by `_name_must_be_clips_ident`). For `raw` functions this is authoring metadata only — the emitted CLIPS name comes from `body`. For `classification` the hierarchy name drives the emitted function names (see below). |
| `description`   | `str`                                            | `""`               | no       | Author-facing prose. Not emitted to CLIPS.                                                                                                                             |
| `params`        | `list[str]`                                      | —                  | yes      | Parameter names. Used when authoring `raw` bodies; the classification path ignores `params` and generates its own `(?level)` / `(?a ?b)` signatures from the hierarchy. |
| `hierarchy_ref` | `str \| None`                                    | `None`             | no       | **Required** when `type == "classification"`. Names the hierarchy whose `levels` drive emission. A trailing `.yaml` is stripped: `hier_name = defn.hierarchy_ref.rsplit(".", 1)[0]`. Ignored for `temporal` and `raw`. |
| `type`          | `Literal["classification", "temporal", "raw"]`   | `"classification"` | no       | Selects the emission strategy. Default is `classification`.                                                                                                            |
| `body`          | `str \| None`                                    | `None`             | no       | Raw CLIPS source. **Required** when `type == "raw"`. Ignored for `classification` and `temporal`.                                                                      |

Emission is dispatched in `compile_function` in
`src/fathom/compiler.py`. Empty `name`, missing `body` for a `raw`
function, missing `hierarchy_ref` for a `classification` function, and
a `hierarchy_ref` that does not resolve to a registered hierarchy all
raise `CompilationError`.

## Type subtypes

### `classification`

A classification function expands to a **family** of deffunctions
named by the hierarchy — not by `FunctionDefinition.name`. The
authoring `name` is a handle for the YAML bundle; the emitted CLIPS
identifiers all begin with the hierarchy name (e.g. `clearance-rank`,
`clearance-below`). The expansion, from
`_compile_classification_functions`, is:

- `(deffunction MAIN::<hier>-rank (?level) (switch ?level (case LEVEL then INDEX) … (default -1)))` — one `case` per level, in declaration order; out-of-hierarchy inputs return `-1`.
- `(deffunction MAIN::<hier>-below (?a ?b) (< (<hier>-rank ?a) (<hier>-rank ?b)))`.
- `(deffunction MAIN::<hier>-meets-or-exceeds (?a ?b) (>= (<hier>-rank ?a) (<hier>-rank ?b)))`.
- `(deffunction MAIN::<hier>-within-scope (?a ?b) (and (>= (<hier>-rank ?a) 0) (>= (<hier>-rank ?b) 0)))` — both inputs must be in-hierarchy.

The compiler also emits **unscoped backward-compat shims** —
`below`, `meets-or-exceeds`, `within-scope` — that delegate to the
scoped versions. These shims are emitted **only for the first loaded
hierarchy** (tracked via `self._first_hierarchy_name`); subsequent
hierarchies add their scoped deffunctions but do not overwrite the
unscoped shims.

Compilation failures:

- Missing `hierarchy_ref` → `CompilationError`.
- `hierarchy_ref` not registered in the bundle → `CompilationError`.

### `raw`

`compile_function` returns `defn.body` as-is. There is no `(deffunction
…)` wrapping, no parameter binding from `params`, and no escaping — the
YAML author supplies a complete, parenthesis-balanced CLIPS source
string, which is inserted into the compiled program verbatim.

Compilation failures:

- Missing `body` → `CompilationError`.

### `temporal`

Currently a stub. `compile_function` returns `""` (empty string) for
`type: temporal` — the YAML surface accepts the subtype, but emission
is a no-op at this phase of development. Temporal operators in rules
(`changed_within`, `count_exceeds`, `rate_exceeds`, `last_n`,
`distinct_count`, `sequence_detected`) are served by Python-side
external functions the engine registers under the reserved `fathom-`
prefix, not by compiled CLIPS deffunctions. Authors typically do not
need to declare a `type: temporal` function for these operators to
work. See
[Register a Python function](../../how-to/register-function.md) for
the external-function path and
[Not in v1](../../concepts/not-in-v1.md) for the broader roadmap.

## `HierarchyDefinition` fields

Classification functions consume a `HierarchyDefinition` from the same
YAML bundle.

| Field          | Type               | Default | Required | Description                                                                                                                                       |
|----------------|--------------------|---------|----------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| `name`         | `str`              | —       | yes      | Hierarchy name. Drives the emitted deffunction prefix (`<name>-rank`, `<name>-below`, …).                                                          |
| `levels`       | `list[str]`        | —       | yes      | Ordered lowest-to-highest. `rank` returns the 0-based index of a level; `below` / `meets-or-exceeds` compare ranks; out-of-hierarchy inputs rank `-1`. |
| `compartments` | `list[str] \| None`| `None`  | no       | Accepted by the model but **not** consumed by `_compile_classification_functions` today. Reserved for future compartment-aware emission.           |

## Worked example — `classification`

### YAML input

```yaml
hierarchies:
  - name: clearance
    levels: [unclassified, confidential, secret, top-secret]

functions:
  - name: clearance-check
    type: classification
    params: [a, b]
    hierarchy_ref: clearance
```

### CLIPS output

```
(deffunction MAIN::clearance-rank (?level)
    (switch ?level
        (case unclassified then 0)
        (case confidential then 1)
        (case secret then 2)
        (case top-secret then 3)
        (default -1)))

(deffunction MAIN::clearance-below (?a ?b)
    (< (clearance-rank ?a) (clearance-rank ?b)))

(deffunction MAIN::clearance-meets-or-exceeds (?a ?b)
    (>= (clearance-rank ?a) (clearance-rank ?b)))

(deffunction MAIN::clearance-within-scope (?a ?b)
    (and (>= (clearance-rank ?a) 0) (>= (clearance-rank ?b) 0)))

(deffunction MAIN::below (?a ?b)
    (clearance-below ?a ?b))

(deffunction MAIN::meets-or-exceeds (?a ?b)
    (clearance-meets-or-exceeds ?a ?b))

(deffunction MAIN::within-scope (?a ?b)
    (clearance-within-scope ?a ?b))
```

Notes:

- The unscoped `below` / `meets-or-exceeds` / `within-scope` shims
  appear because `clearance` is the **first** hierarchy loaded. A
  second hierarchy would emit only its scoped deffunctions; it would
  not shadow the shims.
- `FunctionDefinition.name` (`clearance-check`) and `params` (`[a, b]`)
  are not reflected in the output — the classification path drives
  emission purely from the hierarchy.
- Indentation is four spaces; function definitions are joined by blank
  lines.

## Worked example — `raw`

### YAML input

```yaml
functions:
  - name: double
    type: raw
    params: [x]
    body: "(deffunction MAIN::double (?x) (* ?x 2))"
```

### CLIPS output

```
(deffunction MAIN::double (?x) (* ?x 2))
```

The `body` string is emitted exactly — `params` is authoring metadata
only, and the deffunction's parameter list comes from whatever the
`body` declares.

Naming convention: the `fathom-` prefix is **reserved** for
Engine-registered builtins (`fathom-matches`, `fathom-count-exceeds`,
`fathom-rate-exceeds`, `fathom-changed-within`, `fathom-last-n`,
`fathom-distinct-count`, `fathom-sequence-detected`,
`fathom-parse-compartments`, `fathom-has-compartment`,
`fathom-compartments-superset`, `fathom-dominates`). Python callers of
`Engine.register_function` are rejected with `ValueError` if the
requested name starts with `fathom-`. YAML `raw` bodies are not
re-checked by the compiler, but avoid the prefix in authored CLIPS to
prevent collisions with the runtime's own bindings.

## Validators — what is rejected

| Condition                                            | Where raised                   | Error              |
|------------------------------------------------------|--------------------------------|--------------------|
| `name` that is not a valid CLIPS identifier          | Pydantic validator             | `ValueError`       |
| Empty `name` at compile time                         | `compile_function`             | `CompilationError` |
| `type: raw` with `body is None`                      | `compile_function`             | `CompilationError` |
| `type: classification` without `hierarchy_ref`       | `compile_function`             | `CompilationError` |
| `type: classification` with unknown `hierarchy_ref`  | `compile_function`             | `CompilationError` |

## What is not emitted

- `description` — author-facing only.
- `type: temporal` — emits the empty string.
- `HierarchyDefinition.compartments` — accepted by the model, unused by
  today's classification emission.
- `FunctionDefinition.name` and `params` — ignored by the
  `classification` path (the hierarchy drives names; parameter
  signatures are fixed).
- `FunctionDefinition.params` — informational for `raw` (the emitted
  signature comes from `body`).

## See also

- [Five Primitives](../../concepts/five-primitives.md)
- [YAML Compilation](../../concepts/yaml-compilation.md)
- [Register a Python function](../../how-to/register-function.md)
- [Rule reference](./rule.md) — `test:` escape hatch for calling these functions from the LHS.
- [Template reference](./template.md)
