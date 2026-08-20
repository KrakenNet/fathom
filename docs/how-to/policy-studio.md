---
title: Running Policy Studio
summary: Start the Studio from a checkout, get past its token gate, and know what its five views drive — the real engine, mounted in the same process.
audience: [app-developers, rule-authors]
diataxis: how-to
status: stable
sources:
  - packages/fathom-studio/src/fathom_studio/app.py
  - packages/fathom-studio/src/fathom_studio/auth.py
  - packages/fathom-studio/src/fathom_studio/studio_api.py
  - packages/fathom-studio/src/fathom_studio/scenarios.py
  - packages/fathom-studio/pyproject.toml
last_verified: 2026-08-20
---

# Running Policy Studio

Policy Studio is a local browser UI over a real Fathom engine: load a ruleset,
push facts at it, and read the decision, the rules that fired, and the audit
line that came out. It is a **separate package** — `fathom-studio`, its own
version line — because the engine wheel ships no UI code.

## Install and run

`fathom-studio` is not published to PyPI yet. Run it from a checkout, where
it is a workspace member and `uv sync` already installs it:

```bash
git clone https://github.com/KrakenNet/fathom.git
cd fathom
uv sync

export FATHOM_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run fathom-studio
```

The process prints the URL to open and binds `127.0.0.1:8020`. `--host` and
`--port` override the bind; `FATHOM_STUDIO_PORT` sets the port from the
environment.

Open it as `http://127.0.0.1:8020/?token=$FATHOM_API_TOKEN` **once**. The
token is validated and stored in the `fathom_token` cookie, which the SPA's
`fetch` calls and the plain HTML forms then carry for you.

## The token gate

The Studio mounts the production REST app in the same process, so it holds
itself to the same door: every route that loads a ruleset, drives the engine,
or mints an attestation token requires the same `FATHOM_API_TOKEN` the REST
app requires. There is no second secret. Present it as either
`Authorization: Bearer <token>` (for `curl` and tests) or the cookie above.

Only three things are ungated, and none of them carry engine data: `/health`,
the SPA shell at `/`, and its static assets under `/creem`. With
`FATHOM_API_TOKEN` unset, every gated route answers 401 — an unconfigured
Studio exposes nothing.

## What the views do

| View | What it drives |
|---|---|
| Reasoning Bench | Loads a bundled scenario, evaluates it, and shows decision, reason, and the firing rules |
| Live Wire | A rolling decision stream and deny-rate strip. The traffic is synthetic — it samples the bundled scenarios — but every packet is a real evaluation |
| Rules | The compiled rules of the selected ruleset, with their conditions |
| Templates | The fact schemas the ruleset declares |
| Audit | The signed, hash-linked record of what the Studio has evaluated so far |

Nine demo scenarios ship with the package, covering five example rulesets:
hello allow/deny, RBAC with modules, Bell-LaPadula classification, temporal
anomaly detection, and LangChain guardrails. Each is a copy of the matching
`examples/0N-*` directory, held byte-identical to it by a test. Point
`FATHOM_RULESET_ROOT` at your own directory to drive the Studio with your
rulesets instead.

Decisions are never faked. `POST /studio/api/evaluate` builds a fresh
`Engine` for the chosen ruleset, asserts the facts, evaluates, and renders
what came back — the same stateless shape `/v1/evaluate` uses, so working
memory never leaks from one bench run into the next.

## What it is not

- **Not a sandbox.** The REST app is *mounted*, not proxied: it runs in the
  Studio's process, under `/api`, sharing that module's in-memory session
  store. Anything driven through `/api` — including the server-rendered
  panels, which call it with a per-browser `X-Session-Id` — lands in the same
  working memory a REST client of that process sees.
- **Not a stable API.** The `/studio/api/*` routes are unversioned and
  excluded from [the compatibility policy](https://github.com/KrakenNet/fathom/blob/main/VERSIONING.md);
  they change with the UI.
- **Not your audit log.** The Audit view's chain lives in process memory,
  holds the most recent 200 records, and is signed with a keypair generated
  at startup — it dies with the process. For a durable, verifiable log, use
  `ChainedAttestationLog` from the library
  ([Audit & Attestation](../concepts/audit-attestation.md)).
- **Not hardened for exposure.** It binds loopback by default. Keep it there.
