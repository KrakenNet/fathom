---
title: fathom.rule_matches
summary: MCP tool — fathom.rule_matches
audience: [agent-engineers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom.rule_matches`

Report how far a rule got toward firing: matches, partials, activations

## Input schema

```json
{
  "properties": {
    "rule": {
      "title": "Rule",
      "type": "string"
    }
  },
  "required": [
    "rule"
  ],
  "title": "tool_rule_matchesArguments",
  "type": "object"
}
```

[↩ Back to MCP tool index](./index.md) · short name: `rule_matches`
