---
title: VSCode Tooling
summary: Snippets and JSON Schema association for Fathom YAML files
audience: [rule-authors]
diataxis: reference
status: draft
last_verified: 2026-04-15
---

# VSCode Tooling

## Snippets

Download [`fathom.code-snippets`](fathom.code-snippets) and drop it
into `.vscode/` at your repo root. Available prefixes:

- `fathom-template` — template skeleton
- `fathom-rule` — rule skeleton
- `fathom-module` — module skeleton
- `fathom-function` — function skeleton
- `fathom-schema` — `yaml-language-server` schema association header

## JSON Schema association

Add to your workspace `.vscode/settings.json`:

```json
{
  "yaml.schemas": {
    "https://fathom-rules.dev/reference/yaml/schemas/rule.schema.json": "rules/*.yaml",
    "https://fathom-rules.dev/reference/yaml/schemas/template.schema.json": "templates/*.yaml",
    "https://fathom-rules.dev/reference/yaml/schemas/module.schema.json": "modules/*.yaml",
    "https://fathom-rules.dev/reference/yaml/schemas/function.schema.json": "functions/*.yaml"
  }
}
```

Or add the `yaml-language-server` header to the top of any YAML file:

```yaml
# yaml-language-server: $schema=https://fathom-rules.dev/reference/yaml/schemas/rule.schema.json
```
