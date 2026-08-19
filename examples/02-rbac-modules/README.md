# Example 02 — RBAC with Modules

**Complexity:** Intermediate
**Concepts:** modules, focus order, rule metadata, rule trace

Role-based access control for four roles (`guest`, `viewer`, `editor`, `admin`)
split across two modules so that guardrails always get the last word:

- `role_permits` — role-based allow rules
- `deny_checks` — hard denies (guests can't write, non-admins can't touch
  confidential data, etc.)

## What to notice

- **`focus_order`** in `modules/rbac.yaml` is execution order: the engine
  drains `role_permits`, then `deny_checks`. Both modules always run — CLIPS
  does not short-circuit — so the guardrail module is listed LAST on purpose.
  The evaluator is last-write-wins, which makes "runs last" and "wins" the
  same thing. Scenario 8 shows it: an editor reading a confidential sheet
  gets `role_permits::editor-read-write` and then
  `deny_checks::non-admins-cannot-touch-confidential`, and the deny is what
  the caller sees.
- **Salience inside a module** orders rules within one module the same way.
  Within `deny_checks`, deny rules have salience 10 and
  `non-admins-cannot-touch-confidential` has salience 20, so it fires last
  among the denies and overrides any earlier one.
- **`metadata`** on rules (e.g. `control: RBAC-001`) flows into the audit log
  for compliance traceability.
- **`result.rule_trace`** shows every rule that fired during the evaluation —
  useful for debugging policy stacks.

## Run it

```bash
uv run python examples/02-rbac-modules/main.py
```

You should see denies winning over permits on conflict — including
confidential resources blocked for non-admins, whose trace shows the permit
firing first and then being overridden.

## Layout

```
02-rbac-modules/
  templates/rbac.yaml     user, action
  modules/rbac.yaml       role_permits, deny_checks, focus_order
  rules/permits.yaml      3 allow rules in role_permits
  rules/denies.yaml       4 deny rules in deny_checks
  main.py                 9 scenarios
```
