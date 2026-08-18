# fathom-studio

The Fathom Policy Studio: a local FastAPI UI over the Fathom rules engine. It is
a **separate package** from `fathom-rules` — the engine wheel ships no Studio
code — and depends on `fathom-rules` like any other consumer.

## Install and run

```bash
pip install fathom-studio
export FATHOM_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
fathom-studio            # binds 127.0.0.1:8020
```

Startup prints the URL to open, including `?token=<FATHOM_API_TOKEN>`.

## Auth

The Studio mounts the production REST app (`fathom.integrations.rest`) in the
same process under `/api`, so it must not be a weaker door onto the same engine.
Every Studio route that loads a ruleset, drives the engine or mints an
attestation token requires the same `FATHOM_API_TOKEN` the REST app requires —
there is no second secret. Present it as either:

* `Authorization: Bearer <token>` — JSON API, `curl`, tests; or
* the `fathom_token` cookie, granted by opening `/?token=<FATHOM_API_TOKEN>`
  once, so the panels' plain HTML forms and the SPA's same-origin `fetch` calls
  work in a browser.

Only `/health`, the SPA shell at `/` and its static `/creem` assets are ungated;
they carry no engine data. With `FATHOM_API_TOKEN` unset, every gated route
401s — an unconfigured Studio exposes nothing.

`--host` defaults to `127.0.0.1`. The Studio is a local development tool; its
`/studio/api/*` routes are unversioned and carry no stability promise.

## Bundled demo rulesets

`src/fathom_studio/demo_rulesets/0N-*/` holds copies of the repo's `examples/0N-*`
ruleset YAML (`templates/`, `modules/`, `rules/`, `functions/`, `hierarchies/`),
shipped as package data and resolved with `importlib.resources`. They must stay
byte-identical to `examples/` — `tests/test_studio_api.py::test_packaged_rulesets_match_the_repo_examples`
enforces that from a source checkout. `FATHOM_RULESET_ROOT` overrides them.

## Tests

```bash
uv run pytest packages/fathom-studio/tests -q
```
