---
title: Planned Integrations
summary: Reference catalog of scaffolded, partial, and planned Fathom integrations — what exists in-tree, what is missing, and what design.md promises.
audience: [integrators]
diataxis: reference
status: stable
sources:
  - design.md
  - packages/fathom-go/client.go
  - packages/fathom-go/go.mod
  - packages/fathom-ts/package.json
  - packages/fathom-ts/src/client.ts
  - packages/fathom-editor/package.json
  - src/fathom/integrations/langchain.py
  - src/fathom/integrations/crewai.py
  - src/fathom/integrations/openai_agents.py
  - src/fathom/integrations/google_adk.py
  - protos/fathom.proto
last_verified: 2026-04-16
---

# Planned Integrations

This page catalogs integrations that are **not** production-ready: scaffolded
SDKs, stub applications, and adapter surfaces named in `design.md` that are
not implemented. For shipped integrations, see the dedicated reference
pages ([Python SDK](./python-sdk/index.md), [REST API](./rest/index.md),
[gRPC API](./grpc/index.md), [MCP Tools](./mcp/index.md),
[CLI](./cli/index.md), [VSCode Tooling](./tooling/vscode/index.md),
[Rule Packs](./rule-packs/owasp-agentic.md)).

Each entry declares a **Status** of one of:

- **Shipped** — in-tree, tested, documented, and reachable from a release artifact.
- **Partial** — in-tree with working code but missing tests, packaging, or CI coverage.
- **Planned** — named in `design.md` with no implementation in the source tree.

## Go SDK — `packages/fathom-go/`

**Status:** Partial.

**Location:** `packages/fathom-go/` — a hand-written REST client. The
package contents are `client.go` (180 lines), `go.mod`, and a `Makefile`;
no other Go files exist. `go.mod` declares `module
github.com/KrakenNet/fathom-go` at `go 1.21`.

**What works today:**

- `NewClient(baseURL, opts...)` constructor at `client.go:39-48`, with
  functional options `WithBearerToken` (`client.go:25-27`) and
  `WithHTTPClient` (`client.go:31-33`).
- Four request/response pairs covering the REST surface: `Evaluate`,
  `AssertFact`, `Query`, `Retract` (`client.go:74-144`).
- Shared transport at `client.go:148-180`: JSON marshal/unmarshal,
  `Content-Type: application/json`, optional `Authorization: Bearer
  <token>` header, and error surfacing on any non-2xx status with the
  server body embedded in the returned error.

**What is missing:**

- **No tests.** A directory listing of `packages/fathom-go/` contains no
  `*_test.go` files; nothing is exercised by CI.
- **No gRPC client.** Only REST is wired up. `protos/fathom.proto:12`
  declares `go_package = "github.com/KrakenNet/fathom-go/proto;fathomv1"`,
  but no generated bindings are checked in and no `protoc` step runs in
  the repo.
- **No released module.** Consumers must vendor the package from a local
  clone; nothing is published to a Go proxy.

**How to use today:** Clone the monorepo, `go get` against the local path
(or add a `replace` directive), and point the client at a running REST
server. For the current public API surface, see the generated reference
at [Go SDK](./go-sdk/fathom-go.md).

## TypeScript SDK — `packages/fathom-ts/`

**Status:** Partial.

**Location:** `packages/fathom-ts/` — published identity
`@fathom-rules/sdk` at `0.1.0` per `package.json`. Source lives in
`src/client.ts` (215 lines), `src/errors.ts` (77 lines), and
`src/index.ts` (26 lines). Vitest suites in `test/client.test.ts` and
`test/errors.test.ts`.

**What works today:** A hand-written `FathomClient` plus a typed error
hierarchy. Per `design.md:571`, the package ships at v0.1.0 with 19
vitest tests passing, and the typedoc reference is generated into
`docs/reference/typescript-sdk/` by the `docs` npm script in
`package.json:14`.

**What is missing:**

- **No OpenAPI-generated client.** `package.json:12` declares a
  `generate` script that shells out to `scripts/generate.sh`, which
  invokes `npx @hey-api/openapi-ts` against `../../openapi.json` and
  writes into `src/generated/`. Neither `openapi.json` nor `src/generated/`
  is in the tree — the generator has never been run and committed.
- **No published npm release.** `repository.url` in `package.json` points
  at the monorepo; no `dist/` is published.

**How to use today:** Clone the monorepo, `pnpm install` in
`packages/fathom-ts/`, and import from the local workspace path. The
generated API reference lives at
[TypeScript SDK](./typescript-sdk/index.md).

## Visual Rule Editor — `packages/fathom-editor/`

**Status:** Partial (stub).

**Location:** `packages/fathom-editor/` — package identity `@fathom/editor`
at `0.1.0` with `"private": true` set in `package.json:4`. Dependencies:
React `^19.1.0`, Vite `^7.1.0`; dev toolchain TypeScript `^5.9.0`.

**What exists:** Component stubs under `src/components/`: `RuleTree.tsx`,
`ConditionBuilder.tsx`, `TemplateBrowser.tsx`, `ClipsPreview.tsx`,
`TestRunner.tsx`, `YamlEditor.tsx`. Entry at `src/App.tsx`, Vite bootstrap
at `src/main.tsx`, and an `src/api/` directory for backend glue.

**What is missing:**

- **No tests.** `package.json` declares no `test` script and no test
  runner is installed.
- **No backend wiring.** Per `design.md:572`, "components exist but not
  production-ready." The stubs do not round-trip against a live Fathom
  REST server.
- **Not publishable.** The package is marked `private: true` and has no
  build artifact consumers.

**How to use today:** `pnpm install && pnpm dev` inside
`packages/fathom-editor/` runs the Vite dev server. This is a development
scaffold, not a supported end-user artifact.

## Framework adapters

`design.md:490-495` lists four framework adapters. All four are now shipped.

| Adapter                    | Status | Location |
|----------------------------|--------------------|-----------------|
| LangChain callback handler | **Shipped** | `src/fathom/integrations/langchain.py` |
| CrewAI before-tool-call hook | **Shipped** | `src/fathom/integrations/crewai.py` |
| OpenAI Agents SDK tool guardrail | **Shipped** | `src/fathom/integrations/openai_agents.py` |
| Google ADK before-tool callback | **Shipped** | `src/fathom/integrations/google_adk.py` |

Each adapter follows the same pattern: intercept tool calls, assert a
`tool_request` fact into Fathom, evaluate policy rules, and raise
`PolicyViolation` (or return an error dict for ADK) on deny/escalate.
Install via `pip install fathom-rules[langchain]`, `fathom-rules[crewai]`,
`fathom-rules[openai-agents]`, or `fathom-rules[google-adk]`.

## Known blockers

- **Proto ↔ `go.mod` path alignment** — previously flagged as
  `REVIEW.md` M2 (proto declared `github.com/KrakenNet/fathom/gen/go/fathom/v1`
  while `go.mod` declared `github.com/KrakenNet/fathom-go`, which would
  have broken `protoc` output). Resolved at HEAD:
  `protos/fathom.proto:12` now declares
  `go_package = "github.com/KrakenNet/fathom-go/proto;fathomv1"`, matching
  `packages/fathom-go/go.mod:1`. Generated bindings still need to be
  produced via `protoc` and checked into `packages/fathom-go/proto/`
  before a gRPC client can be built.
- **No CI for the Go, TypeScript, or editor packages.** The Python test
  suite (1361 tests per `design.md:544`) is the only suite wired into CI;
  every "works today" claim above reduces to "works when run locally
  against a developer's machine."

## See also

- [Python SDK](./python-sdk/index.md) — the reference implementation; all
  shipped adapters (including LangChain) live here.
- [REST API](./rest/index.md) — the wire protocol the Go and TypeScript
  SDKs target.
- [gRPC API](./grpc/index.md) — the proto surface the Go SDK does **not**
  yet implement.
- [Go SDK](./go-sdk/fathom-go.md) — gomarkdoc output for the REST client
  described above.
- [TypeScript SDK](./typescript-sdk/index.md) — typedoc output for
  `@fathom-rules/sdk`.
