# Fathom Examples

Five runnable examples that climb the learning curve, from a 30-line
allow/deny policy to a full LangChain agent guardrail.

| #  | Example                                                | Complexity     | What it shows |
|----|--------------------------------------------------------|----------------|---------------|
| 01 | [Hello Allow/Deny](01-hello-allow-deny/)               | Beginner       | Templates, rules, salience, fail-closed default |
| 02 | [RBAC with Modules](02-rbac-modules/)                  | Intermediate   | Modules, focus order, rule trace, metadata |
| 03 | [Bell-LaPadula Classification](03-classification-blp/) | Intermediate+  | Hierarchies, classification ops, compartments, cross-fact refs |
| 04 | [Temporal Anomaly Detection](04-temporal-anomaly/)     | Advanced       | Working memory, TTL, `rate_exceeds`, `distinct_count`, `escalate` |
| 05 | [LangChain Tool Guardrails](05-langchain-guardrails/)  | Expert         | `FathomCallbackHandler`, `PolicyViolation`, trust tiers |

## Run any example

Each directory is self-contained:

```bash
uv run python examples/01-hello-allow-deny/main.py
uv run python examples/02-rbac-modules/main.py
uv run python examples/03-classification-blp/main.py
uv run python examples/04-temporal-anomaly/main.py
uv run python examples/05-langchain-guardrails/main.py
```

## What the examples teach (in order)

1. **Example 01** — the engine, templates, and rules. A 60-second tour of
   the README's Quick Start.
2. **Example 02** — modules and `focus_order` carve up policy into
   layered concerns; `rule_trace` shows the audit path.
3. **Example 03** — hierarchies and classification operators express
   multi-level security in declarative YAML; cross-fact references
   (`$alias.field`) replace what would be Python join logic.
4. **Example 04** — working memory **persists across evaluations** within
   a session, so temporal operators can detect bursts and anomalies that
   stateless engines (OPA, Cedar) cannot.
5. **Example 05** — the same engine slots into a LangChain agent as a
   callback handler, raising `PolicyViolation` on `deny`/`escalate` so
   the agent loop can react.

## Tips for adapting

- **Symbol vs string slot type.** Use `symbol` for small enumerated values
  (`read`, `write`, `secret`); strings won't `eq`-match against unquoted
  symbols in rules.
- **Cross-fact references need binding.** `$req.agent_id` resolves to a
  CLIPS variable bound by an earlier pattern. The earlier pattern must
  contain a condition on that slot — otherwise the variable is fresh
  and the join doesn't constrain anything.
- **Pattern ordering matters for cross-refs.** Put the binding pattern
  before the referencing pattern.
- **Reserved CLIPS names.** Don't use `object`, `class`, or other CLIPS
  keywords as template names (use `resource`, `entity`, etc.).
- **`has_compartments("")`** is a useful tautology that binds the
  `compartments` slot variable for a downstream cross-reference.

## Where to go next

- Browse `src/fathom/rule_packs/` for production-grade rule packs
  (NIST 800-53, HIPAA, CMMC) you can load with `engine.load_pack("nist_800_53")`.
- Read `design.md` for the full runtime specification.
- Run `fathom --help` (the CLI lives in `fathom.cli`) for `validate`,
  `compile`, `bench`, and `repl` commands.
