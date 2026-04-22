---
title: Hot-reloading rulesets in a running server
summary: Sign a ruleset, POST it to /v1/rules/reload, understand the fail-closed default and dev escape, rotate the runtime pubkey, and confirm the live ruleset with `fathom status`.
audience: [operators]
diataxis: how-to
status: stable
last_verified: 2026-04-22
sources:
  - src/fathom/integrations/rest.py
  - src/fathom/engine.py
  - src/fathom/cli.py
  - src/fathom/integrations/ruleset_sig.py
  - src/fathom/attestation.py
---

# Hot-reloading rulesets in a running server

Fathom can swap a running server's ruleset atomically, without a
restart, via `POST /v1/rules/reload`. Each reload:

- Compiles the new YAML in a fresh CLIPS environment and only swaps it
  in on success — a bad ruleset leaves the previous one serving
  traffic (NFR-8).
- Verifies an Ed25519 signature over the raw YAML bytes before
  accepting the payload — unsigned rulesets are **rejected by default**
  (fail-closed, AC-5.5).
- Emits a JWT-attested audit event (`ruleset_reloaded` on success,
  `ruleset_reload_rejected` on failure) carrying the
  `hash_before`/`hash_after` pair.

This how-to covers how to sign a ruleset, wire up the deployment
config, use the dev escape during development, monitor the live
ruleset with `fathom status`, and rotate the runtime pubkey.

## Endpoint shape

```
POST /v1/rules/reload
Authorization: Bearer <operator-token>
Content-Type: application/json
```

Request body — supply **exactly one** of `ruleset_path` or
`ruleset_yaml`; `signature` is required in production (fail-closed
default):

```json
{
  "ruleset_path": "/etc/fathom/rulesets/prod-2026-04-22.yaml",
  "signature":    "<base64 Ed25519 over the raw YAML bytes>"
}
```

Inline form — useful when the operator lacks filesystem write access
on the Fathom host:

```json
{
  "ruleset_yaml": "rules:\n  - id: ...\n",
  "signature":    "<base64 Ed25519 over the ruleset_yaml bytes>"
}
```

Response (200):

```json
{
  "hash_before":       "sha256:aaaa…",
  "hash_after":        "sha256:bbbb…",
  "attestation_token": "<JWT signed by AttestationService>"
}
```

Error codes:

- `400 invalid_request` — both or neither of `ruleset_path` /
  `ruleset_yaml` supplied; `ruleset_path` unreadable; `signature` is
  not valid base64; ruleset failed to compile.
- `400 unsigned_ruleset` — `require_signature=true` (the default) and
  either `signature` is missing or Ed25519 verification failed. Also
  emits `ruleset_reload_rejected` to the audit sink.
- `500 server_misconfigured` — `require_signature=true` but the
  pubkey never loaded (should have failed at boot; treated as
  defence-in-depth).
- `503 not_ready` — engine or attestation service not yet configured
  on `app.state`.

## Signing a ruleset

The runtime pubkey is a **separate concept** from the release-signing
key documented in [release-signing.md](release-signing.md). Per design
decision D2 you can either:

- **Reuse the release-signing keypair.** Simpler key inventory;
  operators who already run `scripts/sign_release.sh` can sign rulesets
  with the same material. Trade-off: a compromise of the release key
  also lets an attacker forge hot-reload payloads.
- **Generate a separate runtime keypair.** Blast-radius reduction: a
  compromised runtime key does not let the attacker forge release
  artifacts, and vice-versa. Recommended for production deployments.

### Generating a runtime keypair

The server expects a **raw Ed25519 PEM public key**, not minisign's
format. Generate with `openssl`:

```shell
openssl genpkey -algorithm ed25519 -out ruleset-signing.key
openssl pkey   -in ruleset-signing.key -pubout -out ruleset-signing.pub
```

Keep `ruleset-signing.key` in the same custody regime as your other
secrets (HSM, sealed secret, offline backup). The public half
(`ruleset-signing.pub`) is what the Fathom server loads at boot.

### Producing a detached signature

Sign the **raw YAML bytes** you intend to POST — not a hash, not a
normalised form. The server re-hashes the payload bytes internally and
uses them both for verification and for `hash_after`. Any pre-signing
transformation (whitespace fix-ups, YAML re-emit) invalidates the
signature.

Python example using `cryptography`:

```python
from base64 import b64encode
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key

yaml_bytes = Path("prod-2026-04-22.yaml").read_bytes()
priv = load_pem_private_key(Path("ruleset-signing.key").read_bytes(), password=None)
signature_b64 = b64encode(priv.sign(yaml_bytes)).decode("ascii")
print(signature_b64)
```

The resulting base64 string goes into the `signature` field of the
reload request. OpenSSL's `pkeyutl -sign` path works too, but keeping
the YAML bytes byte-identical through the shell pipeline is error-
prone; scripted signing is recommended.

## Deployment configuration (fail-closed default)

Two independent controls must both line up for a production deployment:

1. **Config.** In `config.yaml` (or whichever layer feeds your server
   factory):

   ```yaml
   rules:
     hot_reload:
       require_signature: true   # default
   ```

2. **Environment.** Point at the public key PEM file:

   ```shell
   export FATHOM_RULESET_PUBKEY_PATH=/etc/fathom/ruleset-signing.pub
   ```

The server loads the pubkey **at boot** and pins it onto
`app.state.ruleset_pubkey`. If `require_signature=true` and the path
is missing, unset, or unreadable, `build_app()` raises a
`RuntimeError` with the message `ruleset pubkey unreadable or missing;
set FATHOM_RULESET_PUBKEY_PATH or enable dev escape` and the server
never starts. This is deliberate — failing at boot beats failing on
first reload attempt.

## Dev escape (development only)

There is a single supported way to run the server with signature
verification disabled, and it requires **both** of the following, by
design (belt-and-suspenders — a single stray flag is not enough to
lower the security floor):

1. Config: `rules.hot_reload.require_signature: false`.
2. Environment: `FATHOM_ALLOW_UNSIGNED_RULESETS=1`.

Neither alone is sufficient; any other combination keeps the server
fail-closed. When both are set, `build_app()` logs at WARN on startup:

```
ruleset signature verification disabled (require_signature=false +
FATHOM_ALLOW_UNSIGNED_RULESETS=1); hot-reload will accept unsigned
rulesets
```

The WARN line is emitted once per process; scrape for it in your log
aggregator to detect dev escape accidentally turned on in prod. Every
unsigned reload that succeeds under the dev escape still writes a
`ruleset_reloaded` audit record, so there is no silent window.

## Monitoring the live ruleset

`GET /v1/status` (unauthenticated; liveness-shaped) returns:

```json
{
  "ruleset_hash": "sha256:bbbb…",
  "version":      "0.3.1",
  "loaded_at":    "2026-04-22T22:15:07.482+00:00"
}
```

`loaded_at` is the timestamp of the most recent reload, or the
server's boot time if no reload has happened yet. The CLI wraps this
endpoint:

```shell
fathom status --server https://fathom.prod.example.com
```

Output:

```
ruleset_hash: sha256:bbbb…
version:      0.3.1
loaded_at:    2026-04-22T22:15:07.482+00:00
```

Pass `--token` (or set `FATHOM_TOKEN`) if the server fronts `/v1/status`
with auth in your environment. Exit code `0` means the call succeeded
and the ruleset hash was reported; non-zero means the server was
unreachable, returned an HTTP error, or replied with non-JSON.

The `ruleset_hash` you see here should match the `hash_after` value
returned by the most recent `POST /v1/rules/reload`. If it does not,
either a later reload happened between your calls, or the audit log
and live state have diverged — investigate immediately.

## Audit events

Every reload — accepted or rejected — writes one record to the
configured audit sink. Successful reloads emit:

```json
{
  "event_type":         "ruleset_reloaded",
  "ruleset_hash_before": "sha256:aaaa…",
  "ruleset_hash_after":  "sha256:bbbb…",
  "actor":              "bearer-token",
  "timestamp":          "2026-04-22T22:15:07.482+00:00"
}
```

Rejected reloads emit `event_type: ruleset_reload_rejected` with a
`reason` field (`missing_signature`, `verification_failed`,
`unknown_template`, …) and the *unchanged* `ruleset_hash_before`.

The `attestation_token` returned from a successful reload is a JWT
signed by the server's `AttestationService.sign_event()` (C6); you can
verify it offline with the service's pubkey and replay it in your
audit trail as a non-repudiation proof.

## Rotating the runtime pubkey

Rotate on a schedule (annual, matching the release-signing cadence)
or immediately on suspected compromise:

1. Generate a new Ed25519 keypair with `openssl` (see above); store
   the private half in the same custody regime as the old one.
2. Copy the new public key to a fresh path (e.g. `.pub.v2`) on each
   Fathom host so you can roll back instantly if needed.
3. Update the deployment's `FATHOM_RULESET_PUBKEY_PATH` to point at
   the new `.pub.v2` file.
4. Restart the server. `build_app()` reloads the pubkey at boot; there
   is no hot path for pubkey rotation by design (the pubkey is the
   trust anchor for reloads, so rotating it via a reload would be
   circular).
5. Confirm the new pubkey is live by POSTing a reload signed with the
   new private key and watching `fathom status --server …` for a new
   `ruleset_hash` and advanced `loaded_at`.
6. Securely erase the previous private key once you have confirmed
   the next scheduled ruleset push signs cleanly under the new key.

The runtime pubkey and the release-signing pubkey rotate on
independent schedules — if you reuse the same key for both (D2
trade-off), plan one rotation event that covers both surfaces.

## Migration from earlier Fathom builds

This release is the **first** to ship `POST /v1/rules/reload`, so no
operator has ever had a "signatures optional" hot-reload in
production. However, operators who have been experimenting with
pre-release dev builds that accepted unsigned rulesets need to know:

- **The default is fail-closed.** After upgrading, a server started
  without `FATHOM_RULESET_PUBKEY_PATH` will refuse to boot with
  `ruleset pubkey unreadable or missing…`. This is intentional.
- **Before restart, pick one of:**
  1. **Production path (recommended).** Generate a runtime keypair
     (or decide to reuse the release key), publish the pubkey file,
     set `FATHOM_RULESET_PUBKEY_PATH` on every Fathom host, and keep
     `rules.hot_reload.require_signature: true`.
  2. **Dev/CI path.** Set **both** `rules.hot_reload.require_signature:
     false` in config **and** `FATHOM_ALLOW_UNSIGNED_RULESETS=1` in
     the environment. Either alone leaves fail-closed behaviour
     active — deliberately, to stop a partial config from silently
     downgrading security.
- **Audit sink consumers.** Start recognising the two new
  `event_type` values (`ruleset_reloaded`,
  `ruleset_reload_rejected`) alongside the existing eval-shaped
  records. They share the `actor` + `timestamp` envelope but carry
  `ruleset_hash_before` / `ruleset_hash_after` instead of eval fields.
