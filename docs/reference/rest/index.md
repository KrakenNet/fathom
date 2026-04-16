---
title: REST API
summary: Fathom REST API reference, try-it console, and client exports
audience: [app-developers]
diataxis: reference
status: draft
last_verified: 2026-04-15
---

# REST API

Fathom exposes the engine over HTTP via FastAPI. The canonical schema is
exported at [`openapi.json`](openapi.json) and is regenerated on every
build.

## Quick links

- **Interactive try-it:** [Swagger UI](try.md)
- **Raw schema:** [`openapi.json`](openapi.json)
- **Postman collection:** [`fathom.postman_collection.json`](fathom.postman_collection.json)
- **Insomnia:** use *Import from URL* pointed at `openapi.json`.

## Reference

<swagger-ui src="./openapi.json"/>
