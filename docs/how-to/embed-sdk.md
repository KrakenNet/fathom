---
title: Embedding via SDK
summary: Embed Fathom in Python (in-process Engine), Go, or TypeScript (both HTTP clients to the REST server).
audience: [app-developers]
diataxis: how-to
status: stable
last_verified: 2026-05-01
sources:
  - src/fathom/engine.py
  - src/fathom/integrations/rest.py
  - packages/fathom-go/client.go
  - packages/fathom-ts/src/client.ts
---

# Embedding via SDK

Fathom ships three client surfaces. Pick one based on how your application
is shaped:

- **Python in-process** (`fathom-rules`) — the `Engine` class runs in your
  process, holding working memory directly in memory. No server, lowest
  latency.
- **Go HTTP client** (`packages/fathom-go`) — talks to a running Fathom
  REST server at `POST /v1/evaluate` and friends. Session state lives on
  the server.
- **TypeScript HTTP client** (`@fathom-rules/sdk`) — same REST server,
  same four operations, `fetch`-based.

All three expose the same four working-memory operations —
`evaluate`, `assert_fact`, `query`, and `retract` — but Python embeds
the engine in your process while Go and TypeScript are thin wrappers
around the REST API.

## Python — in-process Engine

Install the package:

```bash
pip install fathom-rules
```

Load a rules directory with `Engine.from_rules`, assert facts, and
evaluate:

```python
from fathom.engine import Engine

engine = Engine.from_rules("examples/01-hello-allow-deny")
engine.assert_fact("access", {"role": "admin", "resource": "db"})

result = engine.evaluate()
print(result.decision)      # "allow" | "deny" | "escalate" | None
print(result.reason)
print(result.rule_trace)    # list[str] — rules that fired
print(result.module_trace)  # list[str] — modules traversed
print(result.duration_us)   # int — evaluation time in microseconds
```

`EvaluationResult` also carries `attestation_token` and `metadata`
(see [`EvaluationResult`](../reference/python-sdk/evaluationresult.md)).

### Working memory across calls

The embedded `Engine` is stateful — facts you assert remain in working
memory until you retract them or call `engine.reset()`. A second
`evaluate()` call on the same engine still sees the fact from the
first round:

```python
engine.assert_fact("access", {"role": "admin", "resource": "db"})
engine.evaluate()  # rules see the fact
engine.evaluate()  # second call — the fact is still there

engine.reset()     # clear all facts and reinitialise the environment
```

Use `engine.clear_facts()` to drop user facts without rebuilding
templates and rules.

### Query and retract

`query` returns facts matching a template and optional slot filter;
`retract` removes them and returns how many rows it pulled out:

```python
engine.query("access")
# [{"role": "admin", "resource": "db"}]

engine.query("access", fact_filter={"role": "admin"})
# [{"role": "admin", "resource": "db"}]

removed = engine.retract("access", fact_filter={"role": "admin"})
# removed == 1
```

Both operate on live working memory, so the results reflect rules
that asserted during the most recent `evaluate()` plus anything you
asserted by hand.

## Go — HTTP client

The Go client is published as a standalone module. Install it:

```bash
go get github.com/KrakenNet/fathom-go
```

Prerequisite: a running Fathom REST server — see the
[FastAPI how-to](fastapi.md) for how to start one and configure
`FATHOM_API_TOKEN` and `FATHOM_RULESET_ROOT`.

Minimal example — construct a client with a bearer token and call
`Evaluate`:

```go
package main

import (
    "context"
    "fmt"
    "log"

    fathom "github.com/KrakenNet/fathom-go"
)

func main() {
    client := fathom.NewClient(
        "http://localhost:8000",
        fathom.WithBearerToken("your-token"),
    )

    resp, err := client.Evaluate(context.Background(), &fathom.EvaluateRequest{
        Ruleset:   "",
        SessionID: "session-1",
        Facts: []fathom.FactInput{
            {Template: "access", Data: map[string]any{"role": "admin", "resource": "db"}},
        },
    })
    if err != nil {
        log.Fatal(err)
    }
    fmt.Println(resp.Decision, resp.Reason)
    fmt.Println(resp.RuleTrace)
    fmt.Println(resp.DurationUS)
}
```

`Ruleset` is a path under the server's `FATHOM_RULESET_ROOT`; empty
string evaluates against the root itself. `SessionID` is optional for
stateless evaluation — passing one creates a server-side session that
later `AssertFact` / `Query` / `Retract` calls can reuse.

### Working memory across calls

`AssertFact`, `Query`, and `Retract` all operate on a session
previously created by an `Evaluate` call with the same `session_id`.
Unknown session ids return `404`.

```go
ctx := context.Background()

// Create the session by evaluating once.
_, _ = client.Evaluate(ctx, &fathom.EvaluateRequest{
    Ruleset:   "",
    SessionID: "session-1",
    Facts:     []fathom.FactInput{},
})

_, err := client.AssertFact(ctx, &fathom.AssertFactRequest{
    SessionID: "session-1",
    Template:  "access",
    Data:      map[string]any{"role": "admin", "resource": "db"},
})
if err != nil {
    log.Fatal(err)
}

q, _ := client.Query(ctx, &fathom.QueryRequest{
    SessionID: "session-1",
    Template:  "access",
    Filter:    map[string]any{"role": "admin"},
})
fmt.Println(q.Facts) // []map[string]any{{"role": "admin", "resource": "db"}}

r, _ := client.Retract(ctx, &fathom.RetractRequest{
    SessionID: "session-1",
    Template:  "access",
    Filter:    map[string]any{"role": "admin"},
})
fmt.Println(r.RetractedCount) // 1
```

All methods return `(*Response, error)`; a non-2xx HTTP status is
surfaced as an `error` that includes the server's status code and
response body.

## TypeScript — HTTP client

Install the package:

```bash
npm install @fathom-rules/sdk
```

Construct a `FathomClient` and call `evaluate`:

```ts
import { FathomClient } from "@fathom-rules/sdk";

const client = new FathomClient({
  baseURL: "http://localhost:8000",
  bearerToken: "your-token",
});

const result = await client.evaluate({
  facts: [{ template: "access", data: { role: "admin", resource: "db" } }],
  ruleset: "",
  session_id: "session-1",
});

console.log(result.decision);    // "allow" | "deny" | "escalate" | null
console.log(result.reason);
console.log(result.rule_trace);  // string[]
console.log(result.duration_us); // number
```

The constructor accepts `baseURL` (required), `bearerToken` (optional
— injected as `Authorization: Bearer <token>`), and `headers` (optional
extras). Prefer `bearerToken` over hand-crafting an `Authorization`
header; the option takes precedence.

### Working memory across calls

`assertFact`, `query`, and `retract` target a server session created
by a prior `evaluate` call with the same `session_id`. Request
payloads use snake-case keys to match the REST schema:

```ts
await client.evaluate({
  ruleset: "",
  session_id: "session-1",
  facts: [],
});

await client.assertFact({
  session_id: "session-1",
  template: "access",
  data: { role: "admin", resource: "db" },
});

const q = await client.query({
  session_id: "session-1",
  template: "access",
  filter: { role: "admin" },
});
console.log(q.facts); // [{ role: "admin", resource: "db" }]

const r = await client.retract({
  session_id: "session-1",
  template: "access",
  filter: { role: "admin" },
});
console.log(r.retracted_count); // 1
```

### Error handling

Every failure raises a typed subclass of `FathomError`. Discriminate
with `instanceof`:

- `PolicyViolation` — HTTP `403`, the engine denied the request.
- `ValidationError` — HTTP `400` or `422`, the request body failed
  validation.
- `ConnectionError` — HTTP `>= 500` or a network/abort failure
  (status `0`).
- `FathomError` — base class, used for any other non-2xx status.

```ts
import {
  FathomClient,
  PolicyViolation,
  ValidationError,
  ConnectionError,
} from "@fathom-rules/sdk";

try {
  await client.evaluate({ ruleset: "", facts: [] });
} catch (e) {
  if (e instanceof PolicyViolation) { /* 403 */ }
  else if (e instanceof ValidationError) { /* 400 / 422 */ }
  else if (e instanceof ConnectionError) { /* 5xx or network */ }
  else throw e;
}
```

## Picking the right embedding

| Mode | When to choose it |
|---|---|
| **Python in-process** | Lowest latency, single-process Python app, no need to share session state with other processes or tenants. |
| **Go or TypeScript HTTP client** | Multi-language stack, multi-process deployment, centralised session state, horizontal scaling of the engine tier. |

REST trades a network hop for operational simplicity: one server
serves any language, sessions survive client restarts, and the engine
tier scales independently. The embedded Engine wins on latency and
removes the server from the deployment diagram entirely.

## Related reading

- [Integrating with FastAPI](fastapi.md) — run the REST server the
  Go and TypeScript clients talk to.
- [Python SDK reference](../reference/python-sdk/index.md) — full
  `Engine` surface including `EvaluationResult` fields.
- [Go SDK reference](../reference/go-sdk/fathom-go.md) — generated
  reference for every exported type and method.
- [TypeScript SDK reference](../reference/typescript-sdk/index.md)
  — typedoc-generated client, interface, and error reference.
