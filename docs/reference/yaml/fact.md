---
title: Fact
summary: Reference for Fact assertion and query — the runtime surface for CLIPS working memory.
audience: [rule-authors]
diataxis: reference
status: stable
sources:
  - src/fathom/models.py
  - src/fathom/engine.py
  - src/fathom/facts.py
  - src/fathom/integrations/rest.py
last_verified: 2026-05-01
---

# Fact

A **fact** is a concrete instance of a template — the pair
`(template_name, data_dict)` — living in CLIPS working memory. Unlike
templates, rules, modules, and functions, facts are **not declared in
YAML**: they are asserted at runtime through the SDK, the REST API, or
as a side effect of a rule firing. All facts live under the `MAIN`
module (templates are compiled there; see
[Template reference](./template.md)). For conceptual context see
[Five Primitives](../../concepts/five-primitives.md); for working-memory
mechanics see
[Runtime & Working Memory](../../concepts/runtime-and-working-memory.md).

## Three entry paths

Facts enter working memory through exactly three surfaces. The first
two share the `FactManager` validation chain; the third (rule RHS)
bypasses it — see each subsection.

### REST — `POST /v1/facts`

`AssertFactRequest` body (`src/fathom/models.py`):

```json
{
  "session_id": "abc-123",
  "template": "access-request",
  "data": {
    "subject": "alice",
    "action": "read",
    "amount": 0
  }
}
```

The endpoint (`src/fathom/integrations/rest.py` lines 326–343) requires
an existing session created via `POST /v1/evaluate`; an unknown
`session_id` returns **404 session not found**. Companion endpoints
`POST /v1/query` and `DELETE /v1/facts` accept `session_id`,
`template`, and an optional `filter` dict with the same semantics as
the SDK.

### SDK — `Engine.assert_fact` / `Engine.assert_facts`

Single (`src/fathom/engine.py` line 757):

```python
engine.assert_fact("access-request", {"subject": "alice", "action": "read"})
```

Atomic batch (`src/fathom/engine.py` line 775) — every fact is
validated first; if any fails, **none** are asserted:

```python
engine.assert_facts([
    ("access-request", {"subject": "alice", "action": "read"}),
    ("access-request", {"subject": "bob",   "action": "write"}),
])
```

`Engine.assert_fact` raises `ScopeError` when the referenced template's
`scope` is `"fleet"` — fleet-scoped facts must go through
`FleetEngine.assert_fact`.

### Rule RHS — `then.assert`

Rules may assert facts as a side effect of firing. The YAML surface is
the `assert:` key on a `ThenBlock`, with one `AssertSpec` entry per
fact; slot values are CLIPS source text (literals, `?var` bindings,
balanced s-expressions) — **not** Python data. See the
[Rule reference](./rule.md) for `AssertSpec` and `ThenBlock` shape.

Rule-RHS asserts **do not pass through `FactManager._validate`** — the
compiler emits `(assert (<template> (<slot> <value>) …))` directly into
the CLIPS RHS, and CLIPS itself enforces the deftemplate's type and
allowed-value constraints. The FactManager's Python-level checks do
not run for this path.

## `FactInput` — embedded in `EvaluateRequest`

`FactInput` (`src/fathom/models.py`) is the `(template, data)` shape
used inside `EvaluateRequest.facts[]` — the enclosing request carries
the `session_id`:

```json
{
  "ruleset": "access",
  "session_id": "abc-123",
  "facts": [
    {"template": "access-request", "data": {"subject": "alice", "action": "read"}}
  ]
}
```

Each `FactInput` is asserted into the session before rules fire.

## Validation chain

`FactManager._validate` (`src/fathom/facts.py` lines 200–228) runs seven
steps, in order. The first to fail raises `ValidationError` and aborts
the assertion.

1. **Template registered.** If the template name is not in the
   engine's registry, raise `ValidationError("Unknown template 'X'")`.
2. **Unknown-slot check** (`_check_unknown_slots`, lines 230–243). Any
   key in `data` that is not a declared slot is rejected. The error
   sorts the unknown set and suggests the closest known slot via
   `difflib.get_close_matches(..., n=1)`.
3. **Apply defaults** (`_apply_defaults`, lines 245–253). Every slot
   with a non-`None` `SlotDefinition.default` missing from `data` gets
   the default copied in.
4. **Required check** (`_check_required`, lines 274–283). Slots marked
   `required: true` still missing after defaults raise
   `ValidationError("Missing required slot(s) […] in template 'X'")`.
   **Note:** [Template reference](./template.md) documents
   `SlotDefinition.required` as "not currently enforced" — that is
   accurate for the compiler and CLIPS emission, but `FactManager`
   enforces it at assertion time on the SDK and REST paths.
5. **Type coercion** (`_coerce_types`, lines 255–272):
   - `INTEGER` slot with a `float` value where `value == int(value)` →
     coerced to `int` (excluding `bool`).
   - `STRING` slot with a non-`str` value → coerced via `str(value)`.
   `FLOAT` slots accept `int` without coercion (type check allows
   both). `SYMBOL` slots are wrapped later — see
   [CLIPS coercion](#clips-coercion).
6. **Type check** (`_check_types`, lines 285–320). Validates against
   `_PYTHON_TYPE_MAP` (facts.py lines 18–23):

   | `SlotType` | Accepted Python types |
   |------------|------------------------|
   | `STRING`   | `str`                 |
   | `SYMBOL`   | `str`                 |
   | `FLOAT`    | `float`, `int`        |
   | `INTEGER`  | `int`                 |

   `bool` is **explicitly rejected** for `INTEGER` and `FLOAT` slots
   (facts.py lines 296–312) even though Python's `bool` is a subclass
   of `int` — the check runs before the `isinstance` comparison.
7. **Allowed-values check** (`_check_allowed_values`, lines 322–337).
   When `SlotDefinition.allowed_values` is set, the value is coerced
   with `str(value)` and compared against the list. Comparison is by
   string equality, so `allowed_values: ["1", "2"]` accepts
   `data = {"n": 1}` after stringification.

### Example — unknown-slot rejection

```python
engine.assert_fact("access-request", {"subjects": "alice"})
# ValidationError: Unknown slot(s) ['subjects'] in template
# 'access-request'. Did you mean 'subject'?
```

The suggestion is computed from the first unknown slot in sorted order.

## CLIPS coercion

After `_validate` returns, `_coerce_for_clips` (`src/fathom/facts.py`
lines 185–196) walks the validated data once more: for every slot
whose `type` is `SYMBOL` and whose value is still a plain `str`, the
value is wrapped in `clips.Symbol(value)` before being passed to
`template.assert_fact(**coerced)`. All other values pass through
unchanged.

## Query semantics

`Engine.query(template, fact_filter=None) -> list[dict]` forwards to
`FactManager.query` (`src/fathom/facts.py` lines 76–105). Returns one
dict per matching fact keyed by slot name. `clips.Symbol` values are
stringified on readout (facts.py lines 96–98), so callers receive plain
`str` for `SYMBOL` slots. When `fact_filter` is a non-empty dict, a
fact matches only when **every** filter key satisfies
`row.get(k) == v` (facts.py lines 100–104) — equality is Python `==`,
values are not coerced. A `None` or empty filter returns all facts.
Unknown template raises `ValidationError("Unknown template 'X'")`.
`Engine.count` is `len(query(...))` (facts.py lines 107–113).

```python
engine.query("access-request", {"subject": "alice"})
# [{"subject": "alice", "action": "read", "amount": 0}, ...]
```

## Retract semantics

`Engine.retract(template, fact_filter=None) -> int` forwards to
`FactManager.retract` (`src/fathom/facts.py` lines 115–147). Filter
semantics match `query`: a `None`/empty filter retracts **all** facts
of the template. Matches are collected first, then retracted, to avoid
mutating the CLIPS fact list during iteration. Returns the retracted
count. Accessible via `DELETE /v1/facts`
(`src/fathom/integrations/rest.py` lines 366–384), which takes a
`RetractFactsRequest` and returns
`RetractFactsResponse(retracted_count)`.

```python
removed = engine.retract("access-request", {"subject": "alice"})
```

`Engine.clear_facts()` retracts every user fact in the registry;
`__fathom_decision` and `initial-fact` are untouched.

## TTL and expiration

Fact expiration is configured **at runtime** via the Python API only —
there is no YAML surface for per-fact TTL. `Engine.load_templates`
forwards `TemplateDefinition.ttl` to `FactManager.set_ttl` (engine.py
lines 511–512; facts.py lines 41–42), which stores a per-template TTL.
Assertion timestamps are captured in `_fact_timestamps` keyed by CLIPS
fact index. `FactManager.cleanup_expired()` (facts.py lines 166–181)
retracts facts whose stored timestamp plus TTL is in the past and
returns the count retracted. Cleanup is not automatic — callers invoke
it explicitly.

## What is not surfaced

- **Internal decision facts.** Rules assert a `__fathom_decision` fact
  to carry the outcome; the template is built by `Engine.__init__`
  (engine.py lines 51–60, 198) and deliberately kept out of
  `_template_registry`, so it never appears in `query`, `retract`, or
  the audit fact-snapshot.
- **`initial-fact`.** Asserted by `env.reset()`; excluded by the same
  registry-gated mechanism.
- **Compile-time YAML documents.** Templates, modules, functions, and
  rules are CLIPS constructs, not facts.

## See also

- [Template reference](./template.md) — slot types, defaults,
  allowed-values.
- [Rule reference](./rule.md) — `then.assert` and `AssertSpec` shape
  for rule-RHS assertions.
- [Runtime & Working Memory](../../concepts/runtime-and-working-memory.md)
  — the evaluation loop and fact lifetime.
- [Five Primitives](../../concepts/five-primitives.md)
