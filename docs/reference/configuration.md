---
title: Configuration
summary: Every FATHOM_* environment variable the runtime reads, what it defaults to, and the gRPC TLS and token setup the servers require.
audience: [app-developers]
diataxis: reference
status: stable
sources:
  - src/fathom/integrations/rest.py
  - src/fathom/integrations/grpc_server.py
  - src/fathom/integrations/auth.py
  - src/fathom/metrics.py
  - src/fathom/cli.py
last_verified: 2026-08-21
---

# Configuration

Fathom as a library takes its configuration through `Engine(...)` arguments and
needs no environment. Everything below configures the **servers** — the REST
app, the gRPC server, and the CLI's client commands.

Each variable is read from the process environment. Where a variable is read
per request rather than once at import, the table says so: those can be changed
without a restart.

## All variables

| Variable | Read by | Default | Effect |
|---|---|---|---|
| `FATHOM_API_TOKEN` | REST, gRPC | *(none — required)* | The data-plane bearer token. Every `/v1/*` route and every RPC compares the presented `Authorization: Bearer …` against it with `hmac.compare_digest`. Unset means server mode refuses to authenticate anything. Read per verification. |
| `FATHOM_ADMIN_TOKEN` | REST, gRPC | *(unset)* | Scopes the reload surface. When set, `POST /v1/rules/reload` and the `Reload` RPC accept **only** this token and the data-plane token stops working for them. When unset, reload falls back to `FATHOM_API_TOKEN`. |
| `FATHOM_RULESET_ROOT` | REST | *(none — required)* | Directory that every caller-supplied ruleset path is jailed under. A request naming a path outside it is rejected with 400; an unset root is a 500, never an unjailed read. |
| `FATHOM_RULESET_PUBKEY_PATH` | REST | *(none)* | PEM path of the public key that signed rulesets are verified against. Required at startup unless the dev escape below is engaged — a missing or unreadable key is a startup failure, not a warning. |
| `FATHOM_ALLOW_UNSIGNED_RULESETS` | REST | `0` | Set to `1` **and** build the app with `require_signature=False` to accept unsigned reload payloads. Both are required; either alone keeps signature checking on. Logs a warning on every boot that uses it. |
| `FATHOM_MAX_REQUEST_BYTES` | REST | `2097152` (2 MB) | Body cap on the data-plane routes, enforced on bytes actually received rather than `Content-Length`. `/v1/evaluate` runs a quadratic join over the facts it is given, so this bounds server CPU, not just memory. A non-numeric or non-positive value falls back to the default. Read per request. |
| `FATHOM_MAX_RELOAD_BYTES` | REST, gRPC | `5242880` (5 MB) | Body cap on the reload route specifically, which the data-plane cap skips. gRPC's own receive limit is set below this. Same fallback behaviour. Read per request. |
| `FATHOM_EXPOSE_DOCS` | REST | `0` | Set to `1` to serve `/docs`, `/redoc`, and `/openapi.json`. Off by default because they publish route and schema names to unauthenticated callers. Read once at import. |
| `FATHOM_GRPC_TLS_CERT` | gRPC | *(none)* | PEM certificate path. Required with `FATHOM_GRPC_TLS_KEY` unless insecure mode is opted into. |
| `FATHOM_GRPC_TLS_KEY` | gRPC | *(none)* | PEM private-key path, paired with the certificate above. |
| `FATHOM_GRPC_ALLOW_INSECURE` | gRPC | `0` | Set to `1` to bind a plaintext port when no TLS pair is configured. See the warning below. |
| `FATHOM_METRICS` | Engine | `0` | Set to `1` to enable Prometheus metrics collection without passing `enabled=True` to `MetricsCollector`. No-ops when `prometheus_client` is not installed, so setting it is safe on an install without the `metrics` extra. |
| `FATHOM_TOKEN` | CLI | *(unset)* | Default bearer token for CLI commands that call a server. `--token` overrides it. |

## gRPC TLS

**The gRPC server refuses to start without TLS.** `serve()` binds a secure port
only when both `FATHOM_GRPC_TLS_CERT` and `FATHOM_GRPC_TLS_KEY` name readable
PEM files:

```bash
export FATHOM_GRPC_TLS_CERT=/etc/fathom/tls/server.crt
export FATHOM_GRPC_TLS_KEY=/etc/fathom/tls/server.key
export FATHOM_API_TOKEN="$(cat /run/secrets/fathom-api-token)"
```

```python
from fathom.integrations.grpc_server import serve

server = serve(port=50051)
server.wait_for_termination()
```

With neither the pair nor an explicit opt-in, `serve()` raises `RuntimeError`
naming the three variables. That is deliberate: the bearer token travels in an
RPC metadata header, so an insecure port hands every token to any passive
observer on the path.

The opt-in exists for local development and for deployments that terminate TLS
in a sidecar on the same host:

```bash
export FATHOM_GRPC_ALLOW_INSECURE=1   # plaintext port; token sent in the clear
```

Do not set it on a port reachable from another host. If a service mesh already
terminates TLS, keep the plaintext listener bound to loopback.

Client-certificate authentication (mTLS) is not wired up: the server passes a
single key pair to `grpc.ssl_server_credentials` and does not request a client
certificate. Callers are authenticated by bearer token only.

## Server tokens

Both server surfaces authenticate the same way — a bearer token compared in
constant time — and both distinguish two scopes:

- **Data plane** (`FATHOM_API_TOKEN`): evaluate, assert, query, retract.
- **Admin** (`FATHOM_ADMIN_TOKEN`): ruleset reload.

Setting only `FATHOM_API_TOKEN` means one token does both. Setting both means
a leaked data-plane token cannot swap the policy the server enforces, which is
the split worth having in production. See
[Hot-reloading rulesets](../how-to/hot-reload.md) for the rest of the reload
security model.

## What is not configurable by environment

- **Rule paths and engine options** — `Engine(...)` arguments: audit sink,
  attestation service, session id, evaluation `run_limit`, `match_evidence`.
- **Ports and worker counts** — `serve(port=…, max_workers=…)` for gRPC, and
  the ASGI server's own flags for REST (`uvicorn --port`).
- **Per-rule behaviour** — salience, module focus, and log level are properties
  of the ruleset, not of the deployment.
