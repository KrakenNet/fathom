---
title: Serving an OPA client
summary: Answer OPA Data API requests from Fathom, so an existing OPA caller keeps working against a converted policy.
audience: [app-developers]
diataxis: how-to
status: stable
last_verified: 2026-08-26
sources:
  - src/fathom/integrations/rest.py
  - src/fathom/rego.py
---

# Serving an OPA client

The Fathom REST server answers OPA's Data API at `POST /v1/data/<path>`. An
existing OPA caller — a sidecar client, an admission webhook, one of the OPA
SDKs — already speaks it, so a policy moved across with
[`fathom convert rego`](convert-rego.md) can be served without touching the
code that calls it.

## Address a decision

OPA addresses a document as `data.<package>.<rule>`. The same split applies
here: the leading segments name the ruleset directory under
`FATHOM_RULESET_ROOT`, and the last segment names the document.

```shell
curl -sS http://localhost:8000/v1/data/authz/basic/allow \
  -H "Authorization: Bearer $FATHOM_API_TOKEN" \
  -d '{"input": {"user": {"role": "admin"}, "action": "read"}}'
```

```json
{"result": true}
```

A trailing `allow` or `deny` answers with the bare boolean OPA would return.
The `GET` form works too, with `input` as a URL-encoded JSON query parameter —
convenient from a shell, though query strings are logged by intermediaries, so
anything sensitive belongs in the POST body.

## Address a package

Drop the trailing document name and the response carries the whole decision
instead of one boolean:

```shell
curl -sS http://localhost:8000/v1/data/authz/basic \
  -H "Authorization: Bearer $FATHOM_API_TOKEN" \
  -d '{"input": {"user": {"role": "admin"}, "action": "read"}}'
```

```json
{
  "result": {
    "allow": true,
    "deny": false,
    "decision": "allow",
    "reason": "authz.basic.allow (converted from Rego)",
    "rule_trace": ["authz_basic::allow-1"]
  }
}
```

`reason` and `rule_trace` have no place in OPA's boolean answer. This is where
to read them.

## How `input` becomes facts

OPA sends one arbitrary `input` document; Fathom matches typed facts. The
document is asserted as a single fact, flattened the same way the converter
flattens references — `input.user.role` becomes the slot `user_role` — so a
converted policy works with no configuration.

Three consequences worth knowing:

- **Booleans become the symbols `true` / `false`**, because Fathom has no
  boolean slot type. This is the same substitution `fathom convert rego`
  warns about, and the two halves are the same code.
- **Fields no slot declares are dropped**, not rejected. An OPA caller sends
  its whole input document; a field no rule reads must not fail the request.
- **Lists and nulls are dropped**, since Fathom has no slot type for them.

Assert into a different template with `?template=`; an unknown name is a 400
listing the templates the ruleset does declare.

## Where this differs from OPA

| | OPA | Fathom |
|---|---|---|
| Authentication | Open by default | Bearer token, as on every other route |
| Undefined document | `{}` with 200 | Always defined — the engine has a default decision (`deny`) |
| Error envelope | `{"code", "message"}` | Same, on these two routes only |
| `POST /v1/data` (no path) | Whole data document | 400 — name a ruleset |

The authentication difference is deliberate. Serving one unauthenticated
endpoint beside a server whose other routes all require a token is an
authentication hole, not a compatibility feature.

The undefined-document difference matters if your Rego relied on `allow`
being undefined rather than `false`. Fathom's engine always returns a
decision, which is the shape a policy with `default allow := false` produces —
and that default is what the converter tells you to write.

Errors on these two routes use OPA's `{"code", "message"}` envelope rather
than Fathom's `{"error", "detail"}`, so a client that parses OPA's errors
keeps working. The one exception is `401`, which comes from the shared auth
dependency and answers in Fathom's shape.

## What this does not give you

The Data API is a request/response surface: one input document, one decision.
Facts that persist across evaluations, cross-fact joins and the temporal
operators — the reasons to be on Fathom rather than OPA — are reached through
[`POST /v1/evaluate`](../reference/rest/index.md), which takes a list of typed
facts and can hold a session. Migrating the callers is a second step, after
the policy is running.
