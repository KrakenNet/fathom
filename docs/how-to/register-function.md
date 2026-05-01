---
title: Registering a Python function
summary: Expose a Python callable to CLIPS rules via Engine.register_function and call it with a raw-CLIPS test clause.
audience: [app-developers, rule-authors]
diataxis: how-to
status: stable
last_verified: 2026-05-01
sources:
  - src/fathom/engine.py
  - src/fathom/models.py
---

# Registering a Python function

Sometimes a predicate or classifier is much easier to express in Python than in CLIPS —
regex matching, set overlap, temporal math, or an external lookup. Fathom lets you
register a plain Python callable once, then invoke it from the left-hand side of any
rule through the raw-CLIPS `test:` escape hatch on a `ConditionEntry`.

## Register the function

Call `Engine.register_function(name, callable)`. The callable becomes invokable from
CLIPS as `(name arg1 arg2 ...)`.

```python
from fathom.engine import Engine

engine = Engine()
engine.register_function("overlaps", lambda a, b: bool(set(a) & set(b)))
```

A few constraints worth knowing up front (see `src/fathom/engine.py`):

- `name` must be non-empty and match the regex `[A-Za-z][A-Za-z0-9_-]*`.
- `name` must not start with the reserved `fathom-` prefix — that namespace is
  reserved for builtins the engine registers itself.
- The callable takes positional arguments only.
- Re-registering an existing name overwrites the prior binding. This matches
  clipspy's semantics and is documented behaviour, not an error.

## Call it from a rule

`ConditionEntry.test` (defined in `src/fathom/models.py`) is the escape hatch for
calling user-registered functions from a rule's LHS. It emits a raw `(test <expr>)`
conditional element verbatim, so Fathom's operator allow-list does not apply — you
get the full CLIPS expression language, including any function you registered.

The value of `test` must be a parenthesized CLIPS expression. The Pydantic validator
rejects anything that does not both start with `(` and end with `)`.

```yaml
ruleset: demo
module: MAIN
rules:
  - name: route-shared-tag
    when:
      - template: request
        conditions:
          - slot: tags
            bind: ?req_tags
      - template: allowed
        conditions:
          - slot: tags
            bind: ?allowed_tags
          - test: "(overlaps ?req_tags ?allowed_tags)"
    then:
      action: allow
```

The `(fn-name ?arg1 ?arg2)` form is the convention: the function name comes first and
the arguments follow, all inside a single pair of parentheses. Bindings established
earlier in the `when:` block (here `?req_tags` and `?allowed_tags`) are in scope for
the test expression.

`test` may appear standalone in a `ConditionEntry` (no `slot`, `expression`, or
`bind`), in which case the pattern emits only the test CE. Combined with a slot
constraint, as above, both are emitted on the LHS.

## Name restrictions

`register_function` raises `ValueError` at registration time when the name violates
any of these rules:

- The name must be non-empty.
- The name must match `[A-Za-z][A-Za-z0-9_-]*` — an ASCII letter followed by letters,
  digits, underscores, or hyphens.
- The name must not start with the reserved `fathom-` prefix.

All three errors are raised synchronously by `register_function` before the callable
is handed to the underlying CLIPS environment, so misnamed registrations fail fast.

## When not to use this

Prefer the built-in YAML operators whenever the check can be expressed as a slot
comparison. A condition like `expression: equals(critical)` keeps the logic in YAML,
stays inside Fathom's operator allow-list, and is visible to static tooling.

Reach for `register_function` plus a `test:` clause only when you need Python that
CLIPS cannot express directly: regex matching, set membership or overlap, arithmetic
on timestamps, or calling out to an external service. Every custom function widens
your rule surface beyond what the allow-list can vet, so use it deliberately and
keep each registered callable small, pure, and deterministic.

## Related reading

- [Python SDK reference](../reference/python-sdk/index.md)
- [Writing rules](writing-rules.md)
