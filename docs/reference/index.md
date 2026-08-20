---
title: Reference
summary: Generated reference for every Fathom SDK, API, and tooling surface.
audience: [app-developers, rule-authors, contributors]
diataxis: reference
status: stable
last_verified: 2026-08-20
---

# Reference

Every public surface of Fathom is documented here.

Most pages under this tab are generated from source — the SDK, REST, gRPC, MCP,
CLI, and rule-pack references are rewritten by `make docs-gen`, so hand edits to
them are overwritten on the next build. The YAML pages and
[Configuration](configuration.md) are hand-written and cite the files they
describe in their frontmatter.

Which of these surfaces the project promises to keep working is
[VERSIONING.md](https://github.com/KrakenNet/fathom/blob/main/VERSIONING.md).

## Deployment

- [Configuration](configuration.md) — every `FATHOM_*` variable, gRPC TLS, and
  the server token scopes

## SDKs

- [Python SDK](python-sdk/index.md)
- [Go SDK](go-sdk/index.md)
- [TypeScript SDK](typescript-sdk/index.md)

## APIs

- [REST](rest/index.md) · [Try It](rest/try.md)
- [gRPC](grpc/index.md)
- [MCP Tools](mcp/index.md)

## YAML

- [Schemas](yaml/index.md)

## Tooling

- [CLI](cli/index.md)
- [VSCode snippets + schemas](tooling/vscode/index.md)

## Rule Packs

- [OWASP Agentic](rule-packs/owasp-agentic.md)
- [NIST 800-53](rule-packs/nist-800-53.md)
- [HIPAA](rule-packs/hipaa.md)
- [CMMC](rule-packs/cmmc.md)
