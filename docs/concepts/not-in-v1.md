---
title: CLIPS Features Not In v1
summary: The CLIPS features Fathom deliberately omits from its authored surface in v1, and what to use instead.
audience: [rule-authors, app-developers]
diataxis: explanation
status: stable
last_verified: 2026-04-15
sources:
  - src/fathom/compiler.py
  - src/fathom/models.py
---

# CLIPS Features Not In v1

Fathom is not "CLIPS with YAML." It's a curated subset of CLIPS with an
opinionated authoring surface — the [Five Primitives](./five-primitives.md) —
and most of CLIPS's surface area is deliberately left out. This page lists
what's missing and why, so if you come from a CLIPS background and find
yourself hunting for a feature that isn't there, you can stop hunting.

There are two lists below. The first is the short, canonical list from
`design.md` — three features that are explicitly deferred. The second is
longer and less formal: parts of CLIPS that simply aren't plumbed through the
YAML grammar or the Python API. Those aren't *forbidden* — a determined
embedder can still hand-build raw CLIPS constructs — but they sit outside the
Pydantic safety layer that makes authored rules reviewable.

## Explicitly deferred (per `design.md`)

These three are called out by name in the design document's
"Explicitly Not in v1" section.

### COOL — the CLIPS Object System

CLIPS ships a full object layer — `defclass`, `definstances`,
`defmessage-handler`, slot inheritance, message dispatch. It's powerful,
and it's a different mental model from the rule-and-fact model Fathom is
built around. The design note is blunt: the OOP layer "adds massive surface
area," and the use cases it covers are covered well enough by Templates plus
Functions.

What to use instead: model your domain with `TemplateDefinition` slots and
express behavior with rules that match those templates. If you want shared
computation, lift it into a `FunctionDefinition`.

### Backward chaining

CLIPS supports goal-driven reasoning — "does this fact follow from what we
know?" — in addition to the forward chaining Fathom uses. Fathom's target
problems (governance, routing, classification) are natural fits for forward
chaining: you have a situation, you want to know what decision applies.
The design note marks backward chaining as a v2 consideration.

What to use instead: frame the question as forward chaining. Assert the
facts that describe the situation, `evaluate()`, and read the decision.

### Generic functions and message handlers

CLIPS's `defgeneric` / `defmethod` lets you dispatch a function call to
different implementations based on argument types — the procedural equivalent
of method resolution in an OO language. The design note calls it
"over-engineering for the current problem space," and that's accurate: the
rule pack is already a dispatch layer, and `deffunction` plus clear naming
covers the rest.

What to use instead: author distinct `FunctionDefinition` instances with
clear names, or do the type branching inside a single function body.

## Not exposed in the YAML grammar

These aren't in the design doc's deferred list, but they aren't surfaced
in the authored YAML or the Pydantic models either. They're omitted by
absence rather than by policy.

### `defglobal` — global variables

CLIPS `defglobal` lets you declare module-scoped mutable variables
(`?*max-retries*`, for instance) that rules can read and write. Fathom has
no top-level YAML key for globals, and no `GlobalDefinition` in
`models.py`. The design choice is that all interesting state should live
in working memory — as typed facts — where it's visible to the audit log,
queryable, and versioned through the normal assert/retract path.

What to use instead: model what you'd put in a global as a small
single-instance template (e.g. `config` with the knobs as slots), assert one
fact at session start, and match against it in rules that need it.

### `deffacts` — initial facts blocks

CLIPS `deffacts` lets a construct file declare facts that get asserted
when the environment is reset. Fathom's rule packs have no `facts:` section
that auto-asserts on engine start — facts enter working memory through
`Engine.assert_fact()`, the REST/gRPC fact endpoints, or the RHS of a rule.
The compiler never emits `deffacts`.

What to use instead: if you need a consistent set of starting facts, assert
them from your application's bootstrap code right after constructing the
engine, or drive them from a rule that fires once under a startup focus.

### Logical CEs (truth maintenance)

CLIPS supports `(logical ...)` on the LHS of a rule: facts asserted by that
rule's RHS are *logically dependent* on the matched LHS facts, and when a
supporting fact is retracted, the derived facts are retracted with it.
Fathom's `ConditionEntry` doesn't model `logical`, and the compiler doesn't
emit it. Truth maintenance is useful but carries subtle semantics, and
getting it wrong is hard to debug.

What to use instead: keep dependencies explicit. If a derived fact should
go away when an input fact does, retract it yourself — either from a rule
that watches for the input's absence, or from application code after the
next `evaluate()`.

### Conflict-resolution strategy configuration

CLIPS exposes several strategies for picking which activation fires next
when multiple rules are ready: `depth`, `breadth`, `lex`, `mea`, `random`,
`simplicity`, `complexity`. Fathom uses the CLIPS default (`depth`) and does
not expose a configuration knob. The [Runtime & Working Memory](./runtime-and-working-memory.md)
page explains how salience and the module focus stack give you enough
ordering control for the problem classes Fathom targets.

What to use instead: set explicit `salience` on rules that must fire in a
particular order, and use modules plus focus to partition evaluation into
phases.

### Runtime agenda inspection

CLIPS provides `(get-agenda)`, `(refresh-agenda)`, and similar functions to
inspect or manipulate the agenda — the queue of rule activations — at
runtime. Fathom's Python API doesn't expose these, and there's no YAML way
to ask "what's about to fire?" from inside a rule pack.

What to use instead: inspect the `rule_trace` and `module_trace` fields on
the `EvaluationResult` after the fact. That tells you what fired and in
which module, which is what most agenda questions are really asking.

### Pattern-network and debug introspection

CLIPS has `(watch rules)`, `(watch facts)`, `(dribble-on)`, and a suite of
debug hooks that dump RETE activity to stderr. Fathom doesn't expose these
as YAML features or Python API, because the audit log and the
`rule_trace` / `module_trace` fields on `EvaluationResult` cover the same
need with structured output that a host application can parse.

What to use instead: read the audit log for decisions, and the evaluation
traces for the firing sequence.

### FuzzyCLIPS and temporal CLIPS extensions

These are third-party CLIPS extensions (fuzzy-set reasoning; temporal
operators). They aren't part of base CLIPS, `clipspy` doesn't ship them, and
Fathom hasn't re-implemented them.

What to use instead: encode uncertainty or time explicitly as slot values
(confidence scores, timestamps) and reason about them with ordinary
conditions and custom functions.

## The raw escape hatch

The YAML grammar is a safety layer, not a cage. When you genuinely need
CLIPS expressiveness that the authored surface doesn't reach, Fathom offers
three documented escape hatches:

- **`FunctionDefinition(type="raw", body=...)`** — write a CLIPS
  `deffunction` body verbatim. Useful for CLIPS built-ins that Fathom's
  expression operators don't cover, or for multi-line CLIPS logic that
  would be awkward to shoehorn into a structured function.
- **`ConditionEntry(test=...)`** — emit a raw `(test ...)` conditional
  element on the rule LHS. This is the most common use of the escape hatch:
  calling a custom Python function you've registered.
- **`Engine.register_function(name, fn)`** — expose a Python callable as a
  CLIPS external function, callable from rule RHS actions or from `test`
  conditional elements. See
  [Register a function](../how-to/register-function.md) for the recipe.

The [YAML Compilation](./yaml-compilation.md) page describes the compiler's
raw-passthrough paths in more detail. The rule of thumb: prefer the
structured YAML surface, and reach for raw only when the alternative would
be contorted.

## What's shipped vs what's deferred

| Feature | Status |
|---|---|
| Templates (`deftemplate`) | Shipped |
| Facts (assert/retract/query) | Shipped |
| Rules (`defrule`) with salience | Shipped |
| Modules + focus stack | Shipped |
| Functions (`deffunction`) — structured + raw | Shipped |
| Custom Python functions via `register_function` | Shipped |
| Audit log + attestation | Shipped |
| COOL (`defclass`, message handlers) | Not in v1 |
| Backward chaining | v2 consideration |
| Generic functions (`defgeneric`, `defmethod`) | Not in v1 |
| `defglobal` | Not exposed |
| `deffacts` | Not exposed |
| Logical CEs / truth maintenance | Not exposed |
| Conflict-resolution strategy config | Uses CLIPS default (`depth`) |
| Agenda inspection at runtime | Not exposed |
| `watch` / `dribble` debug hooks | Not exposed (use `rule_trace`) |
| FuzzyCLIPS / temporal extensions | Not shipped |

## Versioning

v1 is the Phase 3 milestone on the Fathom roadmap. "v2 considerations" —
notably backward chaining — are possibilities, not commitments, and the
design document doesn't promise dates. If a feature on this page matters
to you, open an issue describing the use case; that's the input the v2
scoping will work from.
