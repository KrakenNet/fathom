---
title: Integrating with FastAPI
summary: Mount the bundled Fathom REST app or wrap Engine directly to add rule evaluation to your FastAPI service.
audience: [app-developers]
diataxis: how-to
status: stable
last_verified: 2026-04-27
sources:
  - src/fathom/integrations/rest.py
  - src/fathom/engine.py
---

# Integrating with FastAPI

## What ships

Fathom includes a ready-made FastAPI application at
`src/fathom/integrations/rest.py`. The module-level object is named `app`
(a `FastAPI` instance). It exposes bearer-token-authenticated endpoints for
evaluation, compilation, and session inspection. For a full description of
every endpoint, request model, and response model, see
[REST API Reference](../reference/rest/index.md).

## Option A: Mount the bundled app

If you already have a FastAPI application and want to add Fathom under a
path prefix, import `app` from the integration module and mount it.

```python no-verify
from fastapi import FastAPI
from fathom.integrations.rest import app as fathom_app

app = FastAPI()
app.mount("/fathom", fathom_app)
```

After mounting, every Fathom endpoint is available under the `/fathom`
prefix — for example `/fathom/v1/evaluate` and `/fathom/v1/compile`. The
`FATHOM_API_TOKEN` and `FATHOM_RULESET_ROOT` environment variables must be
set before starting the server (see [Auth](#auth) below).

## Option B: Wrap Engine directly

For callers who need custom endpoints — different request shapes, streaming
responses, or tighter control over fact lifecycle — you can instantiate
`Engine` yourself and wire it into your own FastAPI routes.

```python no-verify
from fastapi import FastAPI
from fathom.engine import Engine
from fathom.models import FactInput

engine = Engine()
engine.load_templates("rules/templates")
engine.load_rules("rules/rulesets")

app = FastAPI()

@app.post("/evaluate")
def evaluate(fact: FactInput):
    engine.assert_fact(fact.template, fact.data)
    result = engine.evaluate()
    return {
        "decision": result.decision,
        "reason": result.reason,
        "rule_trace": result.rule_trace,
        "module_trace": result.module_trace,
        "duration_us": result.duration_us,
    }
```

`Engine.evaluate()` returns an `EvaluationResult` with the fields shown
above. The engine accumulates facts across calls in this example; call
`engine.clear_facts()` or `engine.reset()` between requests if you need
stateless evaluation.

For stateless, per-request evaluation, use the class method
`Engine.from_rules(path)` inside the route handler instead:

```python no-verify
from fastapi import FastAPI
from fathom.engine import Engine
from fathom.models import FactInput

app = FastAPI()

@app.post("/evaluate")
def evaluate(fact: FactInput):
    engine = Engine.from_rules("rules/")
    engine.assert_fact(fact.template, fact.data)
    result = engine.evaluate()
    return {"decision": result.decision, "rule_trace": result.rule_trace}
```

## Auth

The bundled `app` enforces bearer-token authentication on every endpoint
except `GET /health`. The implementation lives in
`src/fathom/integrations/auth.py` and works as follows:

1. Every protected endpoint declares `Depends(_require_auth)`.
2. `_require_auth` reads the `Authorization` HTTP header and calls
   `verify_token`.
3. `verify_token` expects the header value to be `Bearer <token>` and
   compares the presented token against `FATHOM_API_TOKEN` using a
   constant-time `hmac.compare_digest` to prevent timing attacks.
4. A missing, malformed, or incorrect token returns `401 Unauthorized`.

**Required environment variables when running the bundled app:**

| Variable | Purpose |
|---|---|
| `FATHOM_API_TOKEN` | Bearer token that clients must send in the `Authorization` header |
| `FATHOM_RULESET_ROOT` | Filesystem root that the server jails all ruleset paths under |

Set both before starting `uvicorn`:

```bash
export FATHOM_API_TOKEN="$(openssl rand -hex 32)"
export FATHOM_RULESET_ROOT="/var/lib/fathom/rulesets"
uvicorn fathom.integrations.rest:app --host 0.0.0.0 --port 8080
```

Clients pass the token in every request:

```bash
curl -H "Authorization: Bearer $FATHOM_API_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"ruleset": "access-control", "facts": [{"template": "request", "data": {"action": "read"}}]}' \
     http://localhost:8080/v1/evaluate
```

**Option B (Engine directly):** the bare `Engine` class has no built-in
auth. Add authentication via FastAPI middleware, an `HTTPBearer` dependency,
or a reverse proxy such as nginx or a cloud API gateway before exposing the
endpoint in production.

### OpenAPI / Swagger UI

API docs are disabled by default to avoid leaking route names to
unauthenticated callers. Set `FATHOM_EXPOSE_DOCS=1` to re-enable them for
local development:

```bash
FATHOM_EXPOSE_DOCS=1 uvicorn fathom.integrations.rest:app --reload
```

## Next

- [REST API Reference](../reference/rest/index.md) — full Swagger spec,
  request/response schemas, and error codes.
- [Python SDK Reference](../reference/python-sdk/index.md) — `Engine`
  constructor, `assert_fact`, `evaluate`, and the full public surface.
