---
title: fathom.retract
summary: MCP tool — fathom.retract
audience: [agent-engineers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom.retract`

Retract facts from working memory

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
  "title": "tool_retractArguments",
  "type": "object"
}
```

[↩ Back to MCP tool index](./index.md) · short name: `retract`
