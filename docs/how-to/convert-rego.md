---
title: Converting a Rego policy
summary: Translate the stateless subset of an OPA Rego policy into Fathom YAML with fathom convert rego, and read what it refused to translate.
audience: [app-developers, rule-authors]
diataxis: how-to
status: stable
last_verified: 2026-08-26
sources:
  - src/fathom/rego.py
  - src/fathom/cli.py
---

# Converting a Rego policy

`fathom convert rego` translates an [OPA](https://www.openpolicyagent.org/)
Rego policy into a Fathom ruleset. It is a migration aid, not a compatibility
layer: it converts the part of Rego that has an exact Fathom equivalent and
**reports everything else instead of approximating it**.

That refusal is the design. A policy converter that mistranslates is worse
than one that declines, because the output looks finished — nobody re-reads a
generated `allow` rule that silently dropped one of its three conditions.

## Prerequisites

Parsing is delegated to the real OPA binary rather than reimplemented, so
`opa` must be on your `PATH`:

```shell
opa version
```

If it is missing, the command fails with a message naming
[where to get it](https://www.openpolicyagent.org/docs/latest/#running-opa).
Only the parse step needs it; the conversion itself is pure Python, and
nothing at Fathom runtime depends on OPA.

## Convert a policy

Given `authz.rego`:

```rego
package authz.basic

import rego.v1

default allow := false

allow if {
    input.user.role == "admin"
    input.action != "delete"
}

deny if {
    input.user.suspended == true
}
```

Print the YAML:

```shell
fathom convert rego authz.rego
```

Or write a loadable pack directory:

```shell
fathom convert rego authz.rego --out ./converted
```

`--out` writes `templates/`, `modules/` and `rules/`, which is the layout
[`Engine.from_rules`](load-rule-pack.md) expects:

```python
from fathom.engine import Engine

engine = Engine.from_rules("./converted")
result = engine.evaluate_once(
    [("input", {"user_role": "admin", "action": "read", "user_suspended": "false"})]
)
assert result.decision == "allow"
```

## What the mapping looks like

Rego evaluates one `input` document; Fathom matches typed facts. So the
converter synthesises **one template** holding the `input` fields the policy
actually reads, with nested paths flattened into slot names —
`input.user.role` becomes the slot `user_role`. Rename the template with
`--template`.

Rego ORs the bodies that share a rule name; Fathom ORs separate rules. Each
body therefore becomes its own rule, named `<decision>-<index>`: the policy
above converts to `allow-1` and `deny-2`.

Slot types are inferred from the literals each field is compared against, and
widen to `string` when one field is compared against literals of different
types. Rego has a single `number` type, so **every number becomes a `float`
slot** — inferring `integer` from a policy that happens to compare against a
whole number would produce a template that rejects the very input the policy
was written for. `flatten_input` feeds those slots floats to match.

### `deny` outranks `allow`

Rego keeps `allow` and `deny` in separate documents and leaves the
precedence to whoever queries them. Fathom renders one decision, last write
wins, so a converted policy has to pick: **converted `deny` rules carry
`salience: -10`**, which makes them fire last and beat a matching `allow`.
Without it the answer for an input matching both came down to the order the
rules happened to be written in — a suspended admin was allowed in one file
and denied in the other. A note names the choice; change the salience if
your caller resolved it the other way.

## The convertible subset

| Rego | Fathom condition |
|---|---|
| `input.x == "v"` | `equals(v)` |
| `input.x != "v"` | `not_equals(v)` |
| `input.n > 5`, `5 < input.n` | `greater_than(5)` |
| `input.n < 5`, `5 > input.n` | `less_than(5)` |
| `input.x in {"a", "b"}` | `in([a, b])` |
| `startswith(input.p, "/pub")` | `matches(^/pub)` |
| `endswith(input.p, ".key")` | `matches(\.key$)` |
| `contains(input.q, "DROP")` | `contains(DROP)` |
| `re_match("^t-[0-9]+$", input.id)` | `matches(^t-[0-9]+$)` |

`startswith` and `endswith` become anchored regexes with the literal escaped,
so a `.` in the needle stays a literal dot.

## What it refuses, and why

Each refusal is printed to stderr naming the rule and the construct.

| Construct | Why not |
|---|---|
| `not input.x` | Fathom fact patterns have no negation; a rule cannot match on the absence of a value. |
| `input.n >= 3`, `<= 3` | Fathom has no inclusive comparison. Rewriting `>= n` as `> n-1` is right for integers and wrong for everything else, so it is not done for you. |
| `input.a == input.b` | Both operands are references. A Fathom condition compares one slot against a literal. |
| `data.roles[_] == input.user` | `data` is a second document Fathom has no counterpart for. |
| `count(input.tags) > 2` | The operand is a function call or a computed reference, not a field. |
| `input.enabled` | A bare truthiness check. Compare the value explicitly. |
| Rules not named `allow` / `deny` | Only those two head names have an unambiguous Fathom decision. |
| `allow if { ... } else = false { ... }` | An `else` branch is a second rule body with its own value. Write it as a separate Fathom rule whose salience orders it. |
| `input.x in {1, "two"}` | The set mixes types and a Fathom slot holds one. Widening to `string` would leave the numbers unmatchable rather than merely imprecise. |
| Any other built-in | Unsupported; reported by name. |

### A rule with one unconvertible condition is dropped whole

This is the case that matters. Half of an `allow` rule matches **more
broadly** than the whole one, so keeping the convertible conditions would
quietly widen the policy. The whole rule is dropped and the reason says so.
Slots that only that rule read are dropped with it, so every slot in the
generated template is one a converted rule actually uses.

## Reading the output

The command exits non-zero when *nothing* converted. Use `--strict` to also
fail when anything at all was skipped — the right setting for a pipeline that
wants all-or-nothing, versus the default best-effort behaviour.

Two things are reported as notes rather than refusals:

- **`default allow := false`.** Fathom's default decision is set on the
  engine, not in the ruleset, so the declaration is not converted.
- **Booleans.** Fathom has no boolean slot type, so Rego's `true` / `false`
  become the symbols `true` / `false`. Assert them as the **strings**
  `"true"` / `"false"`; a Python `True` is rejected by slot validation rather
  than silently failing to match.

## What conversion cannot carry over

The subset is stateless by construction: one `input` fact, compared against
literals. Everything Fathom adds on top of that — facts that persist across
evaluations, cross-fact joins, temporal operators, classification hierarchies
— has no Rego source to convert *from*. Those are written by hand after the
conversion, against the template the converter generated. See
[Writing rules](writing-rules.md).
