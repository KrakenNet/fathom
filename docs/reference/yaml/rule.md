---
title: Rule
summary: YAML reference for RuleDefinition — the defrule authoring surface.
audience: [rule-authors]
diataxis: reference
status: stable
sources:
  - src/fathom/models.py
  - src/fathom/compiler.py
last_verified: 2026-04-27
---

# Rule

A **rule** pairs fact-pattern conditions (the `when` clause) with a
decision and optional fact assertions (the `then` clause). Rules compile
to CLIPS `defrule` constructs scoped to their enclosing module. For
conceptual context see [Five Primitives](../../concepts/five-primitives.md);
for how salience and last-write-wins interact at evaluation time see
[Runtime & Working Memory](../../concepts/runtime-and-working-memory.md).

## Top-level fields — `RuleDefinition`

| Field         | Type                 | Default | Required | Description                                                                                                              |
|---------------|----------------------|---------|----------|--------------------------------------------------------------------------------------------------------------------------|
| `name`        | `str`                | —       | yes      | CLIPS identifier. Must match `^[A-Za-z_][A-Za-z0-9_\-]*$`. Emitted as `(defrule <module>::<name> …)`.                     |
| `description` | `str`                | `""`    | no       | Author-facing prose. Not emitted to CLIPS.                                                                               |
| `salience`    | `int`                | `0`     | no       | Priority hint. Emitted as `(declare (salience N))` only when `!= 0`.                                                     |
| `when`        | `list[FactPattern]`  | —       | yes      | LHS fact patterns. Pydantic accepts an empty list; `compile_rule` raises `CompilationError` when empty.                  |
| `then`        | `ThenBlock`          | —       | yes      | RHS decision and/or asserts. See [`ThenBlock`](#thenblock-fields) below.                                                 |

`name` is validated by `_name_must_be_clips_ident`. `compile_rule` in
`src/fathom/compiler.py` re-checks emptiness and the `when`-list.

## Fact-pattern fields — `FactPattern`

| Field        | Type                     | Default | Required | Description                                                                                                                  |
|--------------|--------------------------|---------|----------|------------------------------------------------------------------------------------------------------------------------------|
| `template`   | `str`                    | —       | yes      | The template name this pattern matches. Emitted as the head of the pattern CE: `(<template> …)`.                              |
| `alias`      | `str \| None`            | `None`  | no       | Optional name used as the cross-fact prefix in other patterns' expressions (`$alias.slot`). Resolved via `_resolve_cross_refs`. |
| `conditions` | `list[ConditionEntry]`   | —       | yes      | Slot constraints and/or test CEs. An empty list emits a bare `(<template>)` pattern.                                         |

## Condition entry — `ConditionEntry`

A `ConditionEntry` supports four shapes. The enforcing validator is
`_require_bind_or_expression` in `src/fathom/models.py`.

### Shape 1 — slot + expression

```yaml
- slot: role
  expression: equals(admin)
```

Emits a CLIPS slot constraint via `_compile_condition`. See
[Supported operators](#supported-operators-in-expression).

### Shape 2 — slot + bind (no expression)

```yaml
- slot: subject_id
  bind: ?sid
```

`bind` must start with `?` (enforced by `_bind_must_start_with_question_mark`).
Emits `(<slot> ?sid)` — captures the slot's value so peer conditions and
the RHS can refer to it.

### Shape 3 — standalone test

```yaml
- test: (my-fn ?sid)
```

Only `test` is set. `test` must be a parenthesized CLIPS expression
(enforced by `_test_must_be_wrapped`). Emits `(test <expr>)` on the rule
LHS **after** all pattern CEs — the escape hatch for custom functions
registered via `Engine.register_function`.

### Shape 4 — combinations

`bind` + `expression` constrains and captures in the same slot;
`test` combined with a slot/expression appends a `(test …)` CE after
the enclosing pattern.

```yaml
- slot: amount
  bind: ?amt
  expression: greater_than(100)
  test: (policy-allows ?amt)
```

### What the validator rejects

- Empty entry (no `expression`, `bind`, or `test`).
- `slot` set but neither `expression` nor `bind` provided.
- `slot` set alongside a standalone `test` with no `expression`/`bind` —
  the slot would have no effect; drop it or add an `expression`/`bind`.
- `bind` that does not start with `?`.
- `test` that is empty or not parenthesized.

## Supported operators in `expression`

Syntax: `operator(arg)`. `arg` may be a literal or a cross-fact reference
`$alias.field` (resolved via `_resolve_cross_refs` to `?alias-field`).
Source: `_compile_condition` docstring in `src/fathom/compiler.py`.

| Group          | Operator                                                                                                    |
|----------------|-------------------------------------------------------------------------------------------------------------|
| Comparison     | `equals`, `not_equals`, `greater_than`, `less_than`                                                         |
| Set            | `in`, `not_in`                                                                                              |
| String         | `contains`, `matches`                                                                                       |
| Classification | `below`, `meets_or_exceeds`, `within_scope`                                                                 |
| Temporal       | `changed_within`, `count_exceeds`, `rate_exceeds`, `last_n`, `distinct_count`, `sequence_detected`          |

Classification operators require a classification function declared with
a `hierarchy_ref` elsewhere in the YAML bundle — the operator emits a
call to the generated `below` / `meets-or-exceeds` / `within-scope`
CLIPS deffunction. Temporal operators emit `(test …)` CEs that call
external functions registered at runtime.

Any other operator raises `CompilationError` from `_compile_condition`.
For worked examples of each operator see
[Writing rules](../../how-to/writing-rules.md).

## `ThenBlock` fields

| Field         | Type                      | Default             | Description                                                                                                                |
|---------------|---------------------------|---------------------|----------------------------------------------------------------------------------------------------------------------------|
| `action`      | `ActionType \| None`      | `None`              | One of `allow`, `deny`, `escalate`, `scope`, `route`. Emitted as an unquoted symbol on the `__fathom_decision` fact.        |
| `reason`      | `str`                     | `""`                | Free text. `{placeholder}` refs compile via `_compile_reason` to `(str-cat "…" ?placeholder "…")`; otherwise a quoted literal. |
| `log`         | `LogLevel`                | `LogLevel.SUMMARY`  | One of `none`, `summary`, `full`. Emitted as the `log-level` slot on the decision fact.                                    |
| `notify`      | `list[str]`               | `[]`                | Notification targets. Joined with `", "` and emitted as a single quoted string in the `notify` slot.                        |
| `attestation` | `bool`                    | `False`             | Emitted as `TRUE`/`FALSE` on the decision fact's `attestation` slot. **Not** a signing switch — see [Audit & Attestation](../../concepts/audit-attestation.md). |
| `metadata`    | `dict[str, str]`          | `{}`                | JSON-serialized (sorted keys) and emitted as a quoted string when non-empty; otherwise an empty quoted string.              |
| `scope`       | `str \| None`             | `None`              | Accepted for authoring but not emitted by `_compile_action` (reserved).                                                    |
| `asserts`     | `list[AssertSpec]`        | `[]`                | YAML key is the singular `assert` (mapped via `populate_by_name`). Each entry becomes one `(assert (<template> …))` on the RHS. |

### `ThenBlock` validator

`_require_action_or_asserts` enforces that at least one of `action` or a
non-empty `assert` list is provided. Rules may assert-only (no
`__fathom_decision` fact is emitted), decide-only, or do both.

## `AssertSpec` fields

| Field      | Type              | Default | Description                                                                                                                               |
|------------|-------------------|---------|-------------------------------------------------------------------------------------------------------------------------------------------|
| `template` | `str`             | —       | Must match `^[A-Za-z_][A-Za-z0-9_\-]*$`.                                                                                                  |
| `slots`    | `dict[str, str]`  | `{}`    | Keys must be valid CLIPS identifiers. Values pass through `_validate_slot_value`: `?var` refs must be well-formed, s-expressions must have balanced parens, and embedded NULs are rejected. |

## Enums

### `ActionType`

| YAML value  | Meaning                              |
|-------------|--------------------------------------|
| `allow`     | Permit the operation.                |
| `deny`      | Refuse the operation.                |
| `escalate`  | Forward for human/higher review.     |
| `scope`     | Narrow the action's scope.           |
| `route`     | Direct to a different handler/path.  |

### `LogLevel`

| YAML value | Emitted audit verbosity |
|------------|-------------------------|
| `none`     | No audit entry.         |
| `summary`  | Decision + rule id.     |
| `full`     | Decision + all facts.   |

## Salience convention

Fathom's fail-closed default is **deny** rules at **lower** salience than
**allow** rules, so `deny` fires last and wins under last-write-wins on
the decision fact. Mechanics in
[Runtime & Working Memory](../../concepts/runtime-and-working-memory.md).

## CLIPS emission

`compile_rule` composes the rule in this fixed order: header,
`(declare (salience N))` (only when non-zero), pattern CEs in `when`
order, test CEs collected from every pattern, the `=>` arrow, the
`__fathom_decision` assert (only when `action` is set), then user
asserts in declared order. Indentation is four spaces.

### YAML input

```yaml
- name: deny_large_transfer
  salience: -10
  when:
    - template: transfer
      alias: $t
      conditions:
        - slot: amount
          bind: ?amt
          expression: greater_than(100)
        - slot: currency
          bind: ?ccy
        - test: (blocked-country ?amt)
  then:
    action: deny
    reason: "Transfer of {amt} {ccy} exceeds limit"
    notify: [compliance, ops]
    attestation: true
    assert:
      - template: audit-log
        slots:
          subject: "?amt"
```

### CLIPS output

```
(defrule finance::deny_large_transfer
    (declare (salience -10))
    (transfer (amount ?amt&?s_amount&:(> ?s_amount 100)) (currency ?ccy))
    (test (blocked-country ?amt))
    =>
    (assert (__fathom_decision
        (action deny)
        (reason (str-cat "Transfer of " ?amt " " ?ccy " exceeds limit"))
        (rule "finance::deny_large_transfer")
        (log-level summary)
        (notify "compliance, ops")
        (attestation TRUE)
        (metadata "")))
    (assert (audit-log (subject ?amt))))
```

Notes on the shape:

- `(declare (salience N))` is omitted when `salience == 0`.
- Test CEs appear after all pattern CEs, in source order across
  patterns.
- `reason` with `{placeholder}` placeholders becomes `(str-cat …)`;
  literal reasons are emitted as plain quoted strings.
- `notify` is always quoted — empty list emits `""`.
- `metadata` is empty-string when `{}`, otherwise
  `json.dumps(metadata, sort_keys=True)`.
- The `__fathom_decision` assert precedes user asserts in document
  order (AC-1.3).
- When `action` is `None`, the decision assert is skipped entirely and
  only user asserts are emitted.

## Validators — what is rejected

Model- or compile-time errors you will hit:

- Empty `name` or invalid CLIPS identifier — `ValueError` /
  `CompilationError`.
- Empty `when` — `CompilationError` from `compile_rule`.
- Unsupported operator in an `expression` — `CompilationError` from
  `_compile_condition`.
- `AssertSpec.template` or slot key that is not a valid CLIPS
  identifier — `ValueError`.
- Slot value with unbalanced parens, malformed `?var`, or embedded
  `\x00` — `ValueError` from `_validate_slot_value`.
- `ThenBlock` with neither `action` nor a non-empty `assert` list —
  `ValueError` from `_require_action_or_asserts`.
- `ConditionEntry` rejections listed under
  [What the validator rejects](#what-the-validator-rejects).

## See also

- [Five Primitives](../../concepts/five-primitives.md)
- [YAML Compilation](../../concepts/yaml-compilation.md)
- [Runtime & Working Memory](../../concepts/runtime-and-working-memory.md)
- [Writing rules](../../how-to/writing-rules.md)
- [Template reference](./template.md)
