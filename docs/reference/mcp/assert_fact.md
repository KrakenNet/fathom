---
title: fathom.assert_fact
summary: MCP tool — fathom.assert_fact
audience: [agent-engineers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom.assert_fact`

Assert a fact into working memory

## Input schema

```json
{
  "properties": {
    "data": {
      "additionalProperties": true,
      "title": "Data",
      "type": "object"
    },
    "template": {
      "title": "Template",
      "type": "string"
    }
  },
  "required": [
    "template",
    "data"
  ],
  "title": "tool_assert_factArguments",
  "type": "object"
}
```

[↩ Back to MCP tool index](./index.md) · short name: `assert_fact`
