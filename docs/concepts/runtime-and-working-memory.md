---
title: Runtime & Working Memory
summary: How the Fathom engine runs — sessions, the evaluation loop, module focus, and why deny rules take lower salience under last-write-wins.
audience: [rule-authors, app-developers]
diataxis: explanation
status: stable
last_verified: 2026-04-27
sources:
  - src/fathom/engine.py
  - src/fathom/evaluator.py
  - src/fathom/compiler.py
---

# Runtime & Working Memory

The [Five Primitives](./five-primitives.md) page introduces the author-level
vocabulary — templates, facts, rules, modules, functions — and how each one
compiles to a CLIPS construct. This page is about the other half of the picture:
what actually happens when you call `evaluate()`. It walks the runtime's
moving parts from the top down — the session, how facts enter working memory,
the evaluation loop, module focus, and the salience/last-write-wins contract
that makes deny rules fail closed.

The mental model to hold: a Fathom engine is a stateful CLIPS environment with
a thin orchestration layer that drives the inference loop and reads a single
distinguished fact template back out.

## The engine as a session

Each `Engine` instance owns exactly one CLIPS environment, stored on
`self._env` in `src/fathom/engine.py`:

```python
self._env: clips.Environment = clips.Environment()
```

That environment is the session. Templates are built into it once at load
time, rules are built once at load time, and working memory — the full
collection of asserted facts — lives on it for as long as the engine lives.

This is the main thing that distinguishes Fathom from stateless policy
engines like OPA or Cedar. Those evaluate a single input document against a
policy and return a decision; nothing carries over. A Fathom engine can hold
facts asserted by one request, receive new facts from a second request, and
let rules that match on the combination fire on the third — all inside one
process, all without re-parsing rule sources. Rate-limit rules, trust-score
aggregation, and any policy whose correct answer depends on prior events are
expressible precisely because working memory persists across `evaluate()`
calls within a session.

Sessions do not persist to disk by default. If the process exits, working
memory goes with it. The REST layer adds a `SessionStore` with TTL and a
session cap to manage many concurrent engines — see the
[FastAPI how-to](../how-to/fastapi.md) for those transport details. This
page is about the runtime in isolation.

An engine can also be cleared without being destroyed. `Engine.reset()`
calls `env.reset()` (which clears facts and re-asserts `(initial-fact)`) and
then rebuilds the internal `__fathom_decision` template. `Engine.clear_facts()`
is narrower: it retracts only the user-asserted facts and leaves CLIPS
internals alone.

## Entry paths for facts

A fact is an instance of a template. There are three ways one lands in
working memory:

1. **REST / gRPC transports.** `POST /v1/facts` and the equivalent gRPC RPC
   call `Engine.assert_fact()` under the hood. Both transports accept one or
   many facts per request.
2. **Direct Python call.** `Engine.assert_fact(template, data)` from embedded
   use. `assert_facts([...])` is the atomic multi-fact form: every fact is
   validated against its template before any is asserted, so a bad slot value
   in the fifth entry aborts the whole batch.
3. **Rule RHS.** A rule's `then.asserts` list — modeled as `AssertSpec` in
   `src/fathom/models.py` — compiles to additional `(assert ...)` forms on
   the rule's right-hand side. When the rule fires, those facts enter working
   memory alongside the `__fathom_decision` fact that carries the rule's
   action.

In all three paths, Python values cross into CLIPS through clipspy: strings
become `STRING`, ints and floats become their CLIPS numeric counterparts,
and slot-level type constraints declared on the template are enforced at
assertion time, not at rule-fire time. Facts that successfully assert are
read back out as `AssertedFact` records in query results and audit
snapshots.

## The evaluation loop

`Engine.evaluate()` is short; the work is delegated to
`src/fathom/evaluator.py`. The sequence inside `Evaluator.evaluate()` is:

1. **Push the focus stack.** `_setup_focus_stack()` emits a single
   `(focus ...)` eval with the registered module order reversed, so the
   first module in the configured list ends up on top of the stack and
   runs first.
2. **Expire TTL facts.** If a `FactManager` is wired in, expired facts are
   retracted before any rules get a chance to match them.
3. **Run to quiescence.** `self._env.run()` fires rules until no activations
   remain on any focused module.
4. **Read the winning decision.** `_read_decision()` iterates the
   `__fathom_decision` facts that rules emitted and picks a winner (next
   section).
5. **Capture traces.** `_capture_trace()` walks the same decision facts in
   order and records every rule that fired plus the modules those rules
   came from.
6. **Clean up.** All `__fathom_decision` facts are retracted so the next
   `evaluate()` call starts with a clean decision slate. User facts are
   not touched.

The return value is an `EvaluationResult` — decision, reason, rule trace,
module trace, duration in microseconds, and parsed metadata. If an
`AttestationService` is configured on the engine, the engine layer signs
the result before returning it.

One thing worth noting: `env.run()` is the single point where CLIPS does
inference. Fathom never calls it more than once per `evaluate()`. A rule
that needs to react to facts another rule asserted sees them because the
rete network is notified as part of that same run, not because the
runtime loops.

## Module focus

CLIPS's focus stack is the mechanism Fathom uses to make module ordering
deterministic. The compiler emits every non-MAIN module as:

```clips
(defmodule <n> (import MAIN ?ALL))
```

(see `Compiler.compile_module` in `src/fathom/compiler.py`). `MAIN` itself
is created with `(defmodule MAIN (export ?ALL))` the first time modules are
loaded, so every module can see the shared `__fathom_decision` template.

At evaluation, the runtime pushes each registered module onto the focus
stack. CLIPS only considers activations from the module at the top of the
stack; when no rules in that module can fire, it pops, and the next module
gets its turn. Fathom's rule is that the first module in `focus_order` is
the first to run, which is why `_setup_focus_stack()` emits modules in
reverse order — the last `(focus X)` argument ends up on top.

The practical upshot is that modules are a coarse-grained ordering tool.
If `policy` comes before `logging` in the focus order, every
activatable `policy` rule fires before any `logging` rule gets a chance,
regardless of salience across module boundaries. Within a single module,
salience takes over.

## Fail-closed salience and last-write-wins

This is the section [Five Primitives](./five-primitives.md) deferred.

When a rule with an `action` fires, its compiled right-hand side asserts a
`__fathom_decision` fact carrying the action (`allow`, `deny`, `escalate`,
`scope`, or `route`), a reason string, the rule name, and JSON-serialized
metadata. The compiler emits this block verbatim; see
`Compiler._compile_action` in `src/fathom/compiler.py`.

After `env.run()` returns, the evaluator reads decisions back in the order
they were asserted:

```python
facts = list(self._iter_decision_facts())
...
winner = facts[-1]
```

That is `src/fathom/evaluator.py`, around line 127. The last decision fact
asserted wins. Everything else about the salience contract follows from
that single line.

CLIPS fires higher-salience rules first. If an `allow` rule has salience
100 and a `deny` rule has salience 50, the `allow` rule fires first, then
the `deny` rule. Both assert `__fathom_decision` facts, both get collected,
and `facts[-1]` — the `deny` fact, the one asserted second — wins. The
final decision is deny.

That is Fathom's fail-closed default. To get it, author deny rules with
**lower** salience than allow rules. If you inverted the numbers, deny
would fire first and allow would overwrite it, which is the opposite of
what a safety-oriented policy usually wants.

A few consequences follow:

- **No rule fires ⇒ default decision.** The engine is constructed with
  `default_decision="deny"`, so an empty `facts` list after `env.run()`
  returns `("deny", "default decision (no rules fired)", {})`. The only
  way to get `allow` out of a Fathom engine is to have a rule explicitly
  assert one.
- **One rule fires ⇒ that decision wins trivially.** No ordering concerns.
- **Both fire ⇒ salience determines order, last-asserted wins.** The
  failure mode to avoid is giving deny rules *higher* salience than the
  allow rules they are supposed to override, because then deny asserts
  first and allow clobbers it.
- **Reason strings track the winner.** The `reason` field on
  `EvaluationResult` comes from the winning decision fact, not a
  concatenation of every rule that fired. If you need the full firing
  history, use `rule_trace`.

The salience field is declared on each rule's YAML and compiles to
`(declare (salience N))` inside the `defrule` — see
`Compiler.compile_rule` around line 165. Salience 0 is the default and is
omitted from the compiled output. For authoring guidance, see the
[writing rules how-to](../how-to/writing-rules.md).

## Conflict resolution within a salience bucket

What if two rules share the same salience and both activate? CLIPS uses a
conflict resolution strategy to break the tie. The default is `depth`,
which roughly prefers activations whose supporting facts were asserted
more recently. Fathom does not override this.

The strategy is deterministic given a fixed CLIPS state, but the order
it produces is an implementation detail of CLIPS, not a contract Fathom
exposes. Do not rely on it for semantic ordering. If two rules should fire
in a specific order, give them distinct salience values and make the
intent explicit in the YAML.

The pragmatic rule: use salience coarsely. A handful of well-known bands
(for example, a `deny` band below an `allow` band below a logging band) is
easier to audit than dozens of one-off values.

## How it all fits together

Reading back through the primitives with the runtime in hand:

1. **Templates** define the shape of facts and build CLIPS `deftemplate`
   constructs on the environment at load time.
2. **Facts** populate working memory — asserted through the REST/gRPC
   transports, the SDK, or by rules firing.
3. **Modules** namespace rules and are pushed onto the focus stack in the
   order the author declared; the top module runs to local quiescence
   before the next one is considered.
4. **Functions** extend the conditions and actions rules can express —
   custom CLIPS deffunctions or Python callables exposed through clipspy.
5. **Rules** fire during `env.run()` in order of salience within a module,
   asserting `__fathom_decision` facts on their RHS.
6. **The evaluator** reads the last `__fathom_decision` fact as the winner
   and returns an `EvaluationResult`.

The stateful working memory in step 2 and the last-write-wins contract in
step 6 are the two properties that most shape how a Fathom policy behaves
in practice. The rest of the runtime is plumbing arranged around them.

For the mechanics of expressing the rules themselves, see
[writing rules](../how-to/writing-rules.md).
