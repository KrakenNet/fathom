---
title: YAML Reference
sources:
  - src/fathom/models.py
  - src/fathom/compiler.py
last_verified: 2026-10-21
---

# YAML Reference

Fathom's YAML authoring surface has one JSON Schema per construct.
Schemas are regenerated from `fathom.models` on every docs build.

## Per-construct reference

| Construct | Page |
|---|---|
| Template | [Template](template.md) |
| Rule | [Rule](rule.md) |
| Module | [Module](module.md) |
| Function | [Function](function.md) |
| Fact | [Fact](fact.md) |

## File-level keys

Each YAML file holds one kind of construct, named by its top-level key.
Any other top-level key is a `CompilationError` at load (`parse_*_file`,
`Engine.reload_rules`), an error from `fathom validate`, and an error
from `POST /v1/compile`:

| File | Allowed top-level keys |
|---|---|
| Template | `templates` |
| Module | `modules`, `focus_order` |
| Function | `functions` |
| Rule | `ruleset`, `version`, `module`, `rules` |

A mapping key given twice anywhere in a file (two `expression:` keys in
one condition, say) is invalid YAML to Fathom: every loader rejects it
instead of keeping the last value. Overriding a key merged in with `<<`
is not a duplicate.

## Downloads

| Construct | Schema |
|---|---|
| Template | [`template.schema.json`](schemas/template.schema.json) |
| Rule | [`rule.schema.json`](schemas/rule.schema.json) |
| Module | [`module.schema.json`](schemas/module.schema.json) |
| Function | [`function.schema.json`](schemas/function.schema.json) |
| Hierarchy | [`schemas/hierarchy.schema.json`](schemas/hierarchy.schema.json) |

See [VSCode tooling](../tooling/vscode/index.md) for editor setup.
