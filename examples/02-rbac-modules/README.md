# Example 02 — RBAC with Modules

**Complexity:** Intermediate
**Concepts:** modules, focus order, rule metadata, rule trace

Role-based access control for four roles (`guest`, `viewer`, `editor`, `admin`)
split across two modules so that guardrails always get priority:

- `deny_checks` — hard denies (guests can't write, non-admins can't touch
  confidential data, etc.)
- `role_permits` — role-based allow rules

## What to notice

- **`focus_order`** in `modules/rbac.yaml` puts `deny_checks` before
  `role_permits`. CLIPS drains the first module's agenda, then the next — so
  a deny in the first module short-circuits the permit checks below.
- **Salience inside a module** still matters. The evaluator uses last-write-wins,
  so deny rules must fire LAST to win. Within `deny_checks`, deny rules have
  salience 10 and `non-admins-cannot-touch-confidential` has salience 20 so it
  fires last among the denies (overriding any earlier deny if needed).
- **`metadata`** on rules (e.g. `control: RBAC-001`) flows into the audit log
  for compliance traceability.
- **`result.rule_trace`** shows every rule that fired during the evaluation —
  useful for debugging policy stacks.

## Run it

```bash
uv run python examples/02-rbac-modules/main.py
```

You should see denies winning over permits on conflict, and confidential
resources blocked for non-admins before the permits module even gets a
chance to fire.

## Layout

```
02-rbac-modules/
  templates/rbac.yaml     user, action
  modules/rbac.yaml       deny_checks, role_permits, focus_order
  rules/denies.yaml       4 deny rules in deny_checks
  rules/permits.yaml      3 allow rules in role_permits
  main.py                 9 scenarios
```
