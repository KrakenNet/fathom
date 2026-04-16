---
title: fathom.query
summary: MCP tool — fathom.query
audience: [agent-engineers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom.query`

Query working memory

## Input schema

```json
{
  "properties": {
    "fact_filter": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Fact Filter"
    },
    "template": {
      "title": "Template",
      "type": "string"
    }
  },
  "required": [
    "template"
  ],
  "title": "tool_queryArguments",
  "type": "object"
}
```

[↩ Back to MCP tool index](./index.md) · short name: `query`
