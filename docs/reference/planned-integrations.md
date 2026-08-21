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
  - packages/fathom-studio/pyproject.toml
  - src/fathom/integrations/langchain.py
  - src/fathom/integrations/crewai.py
  - src/fathom/integrations/openai_agents.py
  - src/fathom/integrations/google_adk.py
  - protos/fathom.proto
last_verified: 2026-08-21
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
generated gRPC bindings. Package contents: `client.go` (181 lines),
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
`@fathom-rules/sdk`, versioned in lockstep with the engine (release-please
writes `package.json` from the same tag, and `scripts/check_version_sync.py`
fails the build if the two drift). Source lives in
`src/client.ts` (215 lines), `src/errors.ts` (77 lines), and
`src/index.ts` (26 lines). Vitest suites in `test/client.test.ts` and
`test/errors.test.ts`.

**What works today:** A hand-written `FathomClient` plus a typed error
hierarchy. The package ships with 34
vitest tests passing (15 in `test/client.test.ts`, 19 in
`test/errors.test.ts`), and the typedoc reference is generated into
`docs/reference/typescript-sdk/` by the `docs` npm script in
`package.json`. The suite is wired into CI: `.github/workflows/ts-ci.yml`
runs typecheck, build and vitest as the required `ts-test` check on every
pull request.

**There is no generated client.** `src/generated/` used to hold one, and
this page used to describe it as working. It was generated once, in April
2026, from a copy of the spec at the repo root that was frozen at API
version 0.3.0 — two endpoints behind the live one — and nothing in the
package ever imported it. Its `generate` script emitted zero files against
the pinned `@hey-api/openapi-ts`, so it could not be refreshed either.
Both the dead tree and the stale root spec are gone; the single spec is
[`docs/reference/rest/openapi.json`](./rest/openapi.json), regenerated by
`scripts/export_openapi.py` and held to the running app by
`tests/test_scripts/test_export_openapi.py`.

**What is missing:**

- **The client covers 4 of the 10 documented endpoints** — `/v1/evaluate`,
  `/v1/facts` (assert and retract) and `/v1/query`. `/v1/compile`,
  `/v1/templates`, `/v1/modules`, `/v1/rules`, `/v1/rules/reload`,
  `/v1/status` and `/health` have no method on `FathomClient`.
- **No published npm release.** `repository.url` in `package.json` points
  at the monorepo; no `dist/` is published. Tracked as issue
  [#40](https://github.com/KrakenNet/fathom/issues/40).

**How to use today:** Clone the monorepo, `pnpm install` in
`packages/fathom-ts/`, and import from the local workspace path. The
generated API reference lives at
[TypeScript SDK](./typescript-sdk/index.md).

## Visual Rule Editor

**Status:** Planned.

The original v1 design named a browser-based rule editor. A React scaffold
lived at `packages/fathom-editor/` and was removed: six component stubs, no
tests, no backend wiring, and a CI job whose only assertion was that the tree
still compiled. It never round-tripped against a live Fathom server, and
Policy Studio (below) had meanwhile shipped
a working browser UI over a real engine. Building the editor out is tracked as
issue [#43](https://github.com/KrakenNet/fathom/issues/43); the scaffold is in
git history if it is ever the right starting point.

## Framework adapters

The original v1 design listed four framework adapters. All four are now shipped.

| Adapter                    | Status | Location |
|----------------------------|--------------------|-----------------|
| LangChain callback handler | **Shipped** | `src/fathom/integrations/langchain.py` |
| CrewAI before-tool-call hook | **Shipped** | `src/fathom/integrations/crewai.py` |
| OpenAI Agents SDK tool guardrail | **Shipped** | `src/fathom/integrations/openai_agents.py` |
| Google ADK before-tool callback | **Shipped** | `src/fathom/integrations/google_adk.py` |

Each adapter follows the same pattern: intercept tool calls, then evaluate a
`tool_request` fact against the policy through `Engine.evaluate_once`, which
asserts the fact, runs, and withdraws it again so one call cannot be decided
on the previous call's working memory.

The guard is **allowlist-only**: it permits the call when — and only when —
the decision is exactly `allow`. Every other outcome (`deny`, `escalate`,
`route`, `scope`, a missing decision, or any value a future release adds)
raises `PolicyViolation` — one class, defined in `fathom.integrations` and
re-exported by every adapter, so one `except` covers all four — or returns
an error dict for ADK. A denylist of
known-bad decisions would fail open on anything it had not heard of.
Install via `pip install fathom-rules[langchain]`, `fathom-rules[crewai]`,
`fathom-rules[openai-agents]`, or `fathom-rules[google-adk]`.

## Policy Studio — `packages/fathom-studio/`

**Status:** Partial.

**Location:** `packages/fathom-studio/` — package identity `fathom-studio` at
`0.1.0`, a uv workspace member of this repo. It depends on `fathom-rules`
like any other consumer; the engine wheel ships no Studio code.

**What works today:** A browser UI over a real engine — five views (Reasoning
Bench, Live Wire, Rules, Templates, Audit) served as a zero-build React SPA,
a JSON backend under `/studio/api`, server-rendered HTMX panels, and the
production REST app mounted in the same process under `/api`. Nine demo
scenarios ship as package data, held byte-identical to the repo's
`examples/0N-*` directories by a test. Its pytest suite runs in CI: root
`testpaths` includes `packages/fathom-studio/tests`, so the required `test`
job covers it.

**What is missing:**

- **No published release.** `fathom-studio` is not on PyPI and no workflow
  builds or publishes it; run it from a checkout with `uv run fathom-studio`.
- **No stability promise.** The `/studio/api/*` routes are unversioned and
  explicitly excluded from
  [VERSIONING.md](https://github.com/KrakenNet/fathom/blob/main/VERSIONING.md).
- **In-memory audit only.** The Audit view's chain is process-local, capped
  at 200 records, and signed with a keypair minted at startup. The durable
  equivalent is `fathom.chained_log.ChainedAttestationLog`.

**How to use today:** [Running Policy Studio](../how-to/policy-studio.md).

## Known blockers

- **Proto ↔ `go.mod` path alignment** — previously flagged as
  `REVIEW.md` M2 (proto declared `github.com/KrakenNet/fathom/gen/go/fathom/v1`
  while `go.mod` declared `github.com/KrakenNet/fathom-go`, which would
  have broken `protoc` output). Resolved at HEAD:
  `protos/fathom.proto:12` now declares
  `go_package = "github.com/KrakenNet/fathom-go/proto;fathomv1"`, matching
  `packages/fathom-go/go.mod:1`. Generated bindings now live in
  `packages/fathom-go/proto/{fathom.pb.go,fathom_grpc.pb.go}`.
- **Every in-tree package is now covered by CI.** The Python suite
  (`.github/workflows/ci.yml`, which also covers the Studio), the Go suite
  (`.github/workflows/go-ci.yml`, unit + `-tags integration`) and the
  TypeScript suite (`.github/workflows/ts-ci.yml`, the required `ts-test`
  check, closing issue
  [#39](https://github.com/KrakenNet/fathom/issues/39)) all run on every
  pull request.

## See also

- [Python SDK](./python-sdk/index.md) — the reference implementation; all
  shipped adapters (including LangChain) live here.
- [REST API](./rest/index.md) — the wire protocol the Go and TypeScript
  SDKs target.
- [gRPC API](./grpc/index.md) — the proto surface, which the Go SDK now
  implements through the generated bindings in `packages/fathom-go/proto/`.
- [Go SDK](./go-sdk/fathom-go.md) — gomarkdoc output for the clients
  described above.
- [TypeScript SDK](./typescript-sdk/index.md) — typedoc output for
  `@fathom-rules/sdk`.
