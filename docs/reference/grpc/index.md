---
title: gRPC API
summary: Fathom gRPC service reference, generated from protos/fathom.proto
audience: [app-developers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# gRPC API

Fathom's gRPC service is defined in
[`protos/fathom.proto`](https://github.com/KrakenNet/fathom/blob/master/protos/fathom.proto).

- **Generated reference:** [`fathom.md`](fathom.md)
- **Raw `.proto`:** [`fathom.proto`](fathom.proto)

The Go SDK's typed client wraps this service — see
[Go SDK reference](../go-sdk/index.md).

## Sessions

- **No `session_id`:** `Evaluate` is stateless. Its facts are asserted,
  evaluated and withdrawn against the server's engine. `AssertFact`,
  `Query`, `Retract` and `SubscribeChanges` need a session and answer
  `INVALID_ARGUMENT` without one.
- **Opening a session:** `Evaluate` with a `session_id` opens an unknown
  session, bound to the `ruleset` it names (a path under
  `FATHOM_RULESET_ROOT`; empty binds the empty ruleset). It is the only RPC
  that creates one; the others answer `NOT_FOUND` for an unknown id.
- **Joining:** a later `Evaluate` with no `ruleset` joins the session. Naming
  a different ruleset than the session was opened with is
  `FAILED_PRECONDITION`.
- **Mounted engine:** a server built with an engine (`serve(engine)`) serves
  stateless evaluation only and refuses every `session_id` with
  `FAILED_PRECONDITION`.
- **JSON fields:** `data_json` must be a JSON object. `filter_json` must be a
  JSON object or empty, and empty matches every fact of the template. Any
  other JSON, `null` included, is `INVALID_ARGUMENT`.

## Reload

`Reload` needs an attestation service to sign the reload event; without one
it answers `FAILED_PRECONDITION` "not_ready". Pass it to `serve()` along with
the signature settings:

```python
from fathom.integrations.grpc_server import serve

server = serve(
    port=50051,
    attestation=attestation_service,
    ruleset_pubkey=pubkey_pem,      # verify signed rulesets
    require_signature=True,         # the default: refuse unsigned ones
    audit_sink=sink,                # optional: receives reload audit records
)
```
