---
title: YAML Reference
sources:
  - src/fathom/models.py
  - src/fathom/compiler.py
last_verified: 2026-04-15
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

## Downloads

| Construct | Schema |
|---|---|
| Template | [`template.schema.json`](schemas/template.schema.json) |
| Rule | [`rule.schema.json`](schemas/rule.schema.json) |
| Module | [`module.schema.json`](schemas/module.schema.json) |
| Function | [`function.schema.json`](schemas/function.schema.json) |
| Hierarchy | [`schemas/hierarchy.schema.json`](schemas/hierarchy.schema.json) |

See [VSCode tooling](../tooling/vscode/index.md) for editor setup.
