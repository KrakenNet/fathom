---
title: REST API
summary: Fathom REST API reference, try-it console, and client exports
audience: [app-developers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# REST API

Fathom exposes the engine over HTTP via FastAPI. The canonical schema is
exported at [`openapi.json`](openapi.json) and is regenerated on every
build.

## Quick links

- **Interactive try-it:** [Swagger UI](try.md)
- **Raw schema:** [`openapi.json`](openapi.json)
- **Postman:** *Import → OpenAPI* pointed at `openapi.json`.
- **Insomnia:** use *Import from URL* pointed at `openapi.json`.

## Contract

- **Auth.** Every route except `GET /health` and `GET /v1/status` needs
  `Authorization: Bearer <FATHOM_API_TOKEN>`; `POST /v1/rules/reload` takes
  `FATHOM_ADMIN_TOKEN` when that is set. The schema declares this as the
  `HTTPBearer` security scheme. A missing or wrong token is 401.
- **Unknown keys.** Request bodies refuse keys they do not declare with
  422 `validation_error`, so a misspelled `sesion_id` fails instead of
  running stateless. `/v1/data` is the exception: it follows OPA's Data
  API, which ignores unknown keys.
- **Sessions.** `POST /v1/evaluate` with a `session_id` and a `ruleset`
  opens a session bound to that ruleset; `/v1/facts`, `/v1/query`,
  `/v1/templates`, `/v1/rules` and `/v1/modules` address it (the GET routes
  by the `X-Session-Id` header). A session id is at most 128 characters
  (422 in a body, 400 in the header). A server holds at most 1000 live
  sessions per app; a session idles out after 30 minutes without a call.
  Opening one more past the ceiling answers 503 `session_limit_exceeded`
  until one expires. Neither bound is configurable, so on a shared server
  one caller opening sessions can lock others out for up to 30 minutes:
  put per-caller rate limits in front of it, or use stateless evaluation
  (no `session_id`). gRPC shares the same bounds (`RESOURCE_EXHAUSTED`).
- **Metrics.** With `FATHOM_METRICS=1` the app also serves `GET /metrics`
  (Prometheus text format, same bearer auth). It is not in `openapi.json`,
  which is exported with metrics off. See
  [Configuration](../configuration.md).

## Reference

<swagger-ui src="./openapi.json"/>
