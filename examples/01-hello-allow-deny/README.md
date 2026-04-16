# Example 01 — Hello Allow/Deny

**Complexity:** Beginner
**Concepts:** templates, rules, salience, fail-closed default

The simplest Fathom policy: check an agent's clearance against a data request's
classification, deny the read when the clearance is insufficient, allow it
otherwise.

## What to notice

- Allow rules have `salience: 100`, deny rules `salience: 10`. CLIPS fires the
  higher-salience rule first; the evaluator uses **last-write-wins** on the
  decision fact, so the deny rule (firing last) overwrites the allow — this is
  the **fail-closed default**.
- `load_templates` and `load_rules` point at directories — each `*.yaml` inside
  is parsed and compiled to a CLIPS `deftemplate` / `defrule`.
- When no rule fires, the engine returns its configured default decision
  (`"deny"`), not an error.

## Run it

```bash
uv run python examples/01-hello-allow-deny/main.py
```

Expected output (timings will vary):

```
  [  top-secret -> unclassified] allow  (~90us)  Top-secret clearance may read any classification
  [confidential -> unclassified] allow  (~60us)  Any clearance may read unclassified data
  [confidential -> secret      ] deny   (~50us)  Confidential clearance cannot read secret or top-secret data
  [      secret -> top-secret  ] deny   (~50us)  Secret clearance insufficient for top-secret data
  [unclassified -> unclassified] allow  (~95us)  Any clearance may read unclassified data
```

## Layout

```
01-hello-allow-deny/
  templates/access.yaml      Fact schemas: agent, data_request
  modules/governance.yaml    One module, focus order
  rules/access.yaml          3 deny rules, 3 allow rules
  main.py                    Runs five scenarios
```
