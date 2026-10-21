---
title: MCP Tool Manifest
summary: Machine-readable index of Fathom MCP tools
audience: [agent-engineers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# MCP Tool Manifest

Raw manifest: [`manifest.json`](manifest.json)

## Launching the server

Start the server over stdio with a rule pack (needs the `mcp` and `cli` extras):

```shell
fathom mcp path/to/rules
```

The pack is compiled before the server starts: a broken pack exits `1`, an unreadable one `2`. Once serving, stdout carries the MCP protocol. To register it with an MCP client, give the client that command, e.g.:

```json
{"mcpServers": {"fathom": {"command": "fathom", "args": ["mcp", "path/to/rules"]}}}
```

Only stdio is supported. The tools are unauthenticated and share one Engine, so each client gets its own server process. From Python, `FathomMCPServer(rules_path).run()` (`fathom.integrations.mcp_server`) does the same.

## Tools

| Tool | Description |
|---|---|
| [`fathom.agenda`](agenda.md) | List the activations waiting to fire |
| [`fathom.assert_fact`](assert_fact.md) | Assert a fact into working memory |
| [`fathom.evaluate`](evaluate.md) | Run forward-chain evaluation |
| [`fathom.query`](query.md) | Query working memory |
| [`fathom.retract`](retract.md) | Retract facts from working memory |
| [`fathom.rule_matches`](rule_matches.md) | Report how far a rule got toward firing: matches, partials, activations |
| [`fathom.trace`](trace.md) | Evaluate and return the decision with every rule firing in order |
