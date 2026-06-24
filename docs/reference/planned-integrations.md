---
title: Planned Integrations
summary: Reference catalog of scaffolded, partial, and planned Fathom integrations — what exists in-tree, what is missing, and what the original v1 design promised.
audience: [integrators]
diataxis: reference
status: stable
sources:
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
last_verified: 2026-06-24
---

# Planned Integrations

This page catalogs integrations that are **not** production-ready: scaffolded
SDKs, stub applications, and adapter surfaces named in the original v1
design that are not implemented. For shipped integrations, see the dedicated reference
pages ([Python SDK](./python-sdk/index.md), [REST API](./rest/index.md),
[gRPC API](./grpc/index.md), [MCP Tools](./mcp/index.md),
[CLI](./cli/index.md), [VSCode Tooling](./tooling/vscode/index.md),
[Rule Packs](./rule-packs/owasp-agentic.md)).

Each entry declares a **Status** of one of:

- **Shipped** — in-tree, tested, documented, and reachable from a release artifact.
- **Partial** — in-tree with working code but missing tests, packaging, or CI coverage.
- **Planned** — named in the original v1 design with no implementation in the source tree.

## Go SDK — `packages/fathom-go/`

**Status:** Partial.

**Location:** `packages/fathom-go/` — a hand-written REST client plus
generated gRPC bindings. Package contents: `client.go` (180 lines),
`client_test.go` (818 lines), `grpc_test.go` (230 lines, build-tagged
`integration`), `tools.go`, `go.mod`, `go.sum`, `Makefile`, and
`proto/` with `fathom.pb.go` + `fathom_grpc.pb.go`. `go.mod` declares
`module github.com/KrakenNet/fathom-go` at `go 1.25.0`.

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
- Unit tests in `client_test.go` exercise the REST surface against
  `httptest` servers.
- Generated gRPC stubs live in `packages/fathom-go/proto/` (built from
  `protos/fathom.proto`); `grpc_test.go` is a `-tags=integration` test
  that spawns the Python gRPC server and dials it via those stubs.

**What is missing:**

- **No released module.** Consumers must vendor the package from a local
  clone; nothing is published to a Go proxy. Tracked as issue
  [#41](https://github.com/KrakenNet/fathom/issues/41).

The Go suite **is** wired into CI:
`.github/workflows/go-ci.yml` runs `go vet`, `go build`, and
`go test ./...` on every pull request, with a second `integration` job
that spins up the Python gRPC server and runs `go test -tags integration
./...`. A `verify-grpc` step also fails the build if the generated
bindings drift from `protos/fathom.proto`.

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
hierarchy. The package ships at v0.1.0 with 34
vitest tests passing (15 in `test/client.test.ts`, 19 in
`test/errors.test.ts`), and the typedoc reference is generated into
`docs/reference/typescript-sdk/` by the `docs` npm script in
`package.json:14`.

**What works (additional):** The OpenAPI-generated client has been
produced and committed. `openapi.json` lives at the repo root, and
`packages/fathom-ts/src/generated/` contains `core/`, `index.ts`,
`schemas.gen.ts`, `services.gen.ts`, and `types.gen.ts` — the output of
the `generate` script at `package.json:12` (which shells out to
`scripts/generate.sh` calling `npx @hey-api/openapi-ts` against
`../../openapi.json`).

**What is missing:**

- **No published npm release.** `repository.url` in `package.json` points
  at the monorepo; no `dist/` is published. Tracked as issue
  [#40](https://github.com/KrakenNet/fathom/issues/40).
- **No CI for the TS suite.** Vitest suites pass locally only. Tracked as
  issue [#39](https://github.com/KrakenNet/fathom/issues/39).

**How to use today:** Clone the monorepo, `pnpm install` in
`packages/fathom-ts/`, and import from the local workspace path. The
generated API reference lives at
[TypeScript SDK](./typescript-sdk/index.md).

## Visual Rule Editor — `packages/fathom-editor/`

**Status:** Partial (stub).

**Location:** `packages/fathom-editor/` — package identity `@fathom/editor`
at `0.1.0` with `"private": true` set in `package.json:4`. Dependencies:
React `^19.2.7`, Vite `^8.0.16`; dev toolchain TypeScript `^6.0.3`.

**What exists:** Component stubs under `src/components/`: `RuleTree.tsx`,
`ConditionBuilder.tsx`, `TemplateBrowser.tsx`, `ClipsPreview.tsx`,
`TestRunner.tsx`, `YamlEditor.tsx`. Entry at `src/App.tsx`, Vite bootstrap
at `src/main.tsx`, and an `src/api/` directory for backend glue.

**What is missing:**

- **No tests.** `package.json` declares no `test` script and no test
  runner is installed.
- **No backend wiring.** The original v1 design described the editor as
  "components exist but not production-ready." The stubs do not round-trip against a live Fathom
  REST server.
- **Not publishable.** The package is marked `private: true` and has no
  build artifact consumers. Building this stub out into a working visual
  rule editor is tracked as issue
  [#43](https://github.com/KrakenNet/fathom/issues/43).

**How to use today:** `pnpm install && pnpm dev` inside
`packages/fathom-editor/` runs the Vite dev server. This is a development
scaffold, not a supported end-user artifact.

## Framework adapters

The original v1 design listed four framework adapters. All four are now shipped.

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
  `packages/fathom-go/go.mod:1`. Generated bindings now live in
  `packages/fathom-go/proto/{fathom.pb.go,fathom_grpc.pb.go}`.
- **No CI for the TypeScript or editor packages.** The Python test suite
  (1551 tests, `.github/workflows/ci.yml`) and the Go suite
  (`.github/workflows/go-ci.yml`, unit + `-tags integration`) both run on
  every pull request. The TypeScript vitest suite (tracked as issue
  [#39](https://github.com/KrakenNet/fathom/issues/39)) and the editor
  (issue [#43](https://github.com/KrakenNet/fathom/issues/43)) remain
  uncovered, so every "works today" claim for those two packages reduces
  to "works when run locally against a developer's machine."

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
