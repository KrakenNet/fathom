# Security Policy

## Supported versions

The latest released minor is supported. Security fixes ship as a new patch of
that minor and are not backported: pre-1.0, upgrading to the current minor is
the supported response to a fix. See
[VERSIONING.md](VERSIONING.md#supported-versions) for the full policy and what
a version bump means for compatibility.

Check what is current on [PyPI](https://pypi.org/project/fathom-rules/) or in
[CHANGELOG.md](CHANGELOG.md). Every release from 0.5.0 onward is signed; see
[Verifying a signed release](docs/how-to/release-signing.md).

## Reporting a vulnerability

Report privately through GitHub: **Security → Advisories → Report a
vulnerability**, or directly at
<https://github.com/KrakenNet/fathom/security/advisories/new>.

Do not open a public issue, a pull request, or a discussion for a suspected
vulnerability. A public report starts the disclosure clock before there is a
fix to disclose.

Useful in a report: the version, the surface (library, REST, gRPC, MCP,
Studio), what an attacker gains, and the smallest input that reproduces it. A
ruleset or fact set that triggers the behaviour is worth more than a
description of it.

### What happens next

| Step | Target |
|---|---|
| Acknowledgement that the report was received | 2 business days |
| Assessment: in scope or not, and a severity | 7 days |
| Fix released for a critical or high finding | 30 days from assessment |
| Fix released for a moderate or low finding | Next scheduled minor |

If a fix will take longer than 30 days, the advisory thread says so and why,
rather than going quiet.

### Disclosure

Fixes are coordinated: the advisory stays private until a fixed version is
published, then it is published as a GitHub Security Advisory with a CVE
requested through GitHub's CNA. The advisory names the affected versions, the
fixed version, and the reporter — tell us if you would rather not be credited,
or how you want to be named.

The embargo runs until the fixed release is out, or **90 days** from
acknowledgement, whichever comes first. If a report is still unfixed at 90
days, the reporter is free to disclose; we would rather publish an advisory
with a workaround than let a real issue sit unannounced. A vulnerability
already public, or under active exploitation, is not embargoed — it gets an
advisory as soon as it is confirmed, with whatever mitigation exists.

## Scope

### In scope

- **The library** (`fathom` package) — including compiler injection: any
  input to the YAML authoring surface that produces CLIPS constructs the
  author did not write.
- **The REST server** (`fathom.integrations.rest`) — authentication, the
  ruleset path jail, request size limits, and the hot-reload signature check.
- **The gRPC server** (`fathom.integrations.grpc_server`) — the same, plus TLS
  configuration.
- **The MCP tool server** (`fathom.integrations.mcp_server`).
- **Hot reload** (`POST /v1/rules/reload` and the `Reload` RPC) — anything that
  loads an unsigned or attacker-supplied ruleset where the configuration says
  it should not.
- **Attestation and the audit log** — signature forgery, token replay across
  sessions or inputs, and any way to alter a hash-chained log without
  detection.
- **The release path** — the published wheels and their signatures, the
  packaged public keys, and the workflows that produce them.
- **Policy Studio** (`packages/fathom-studio`) — authentication bypass, and
  any path that lets a Studio request reach a file or a ruleset outside its
  configured root.

### Not in scope

- **The `test:` conditional element and `type: raw` functions.** Both emit
  author-written CLIPS verbatim and are documented escape hatches. A ruleset
  author is trusted with the CLIPS environment; if untrusted parties author
  rulesets in your deployment, the boundary you need is the signature check on
  reload, not these.
- **`FATHOM_GRPC_ALLOW_INSECURE=1` and the unsigned-ruleset dev escape.** Both
  require an explicit opt-in and both log what they disabled. Reports that
  they are insecure describe their purpose.
- **Denial of service from a ruleset you deployed yourself.** Evaluation is
  bounded by an activation budget and request bodies are capped; a ruleset
  that is merely slow is a performance issue.
- **Missing hardening with no attack behind it** — a header that could be set,
  a dependency that could be newer. Send a pull request or open an issue.
- **Findings in a dependency** with no Fathom-specific path to reach them.
  Report those upstream; if Fathom's use makes an upstream issue exploitable
  when it otherwise would not be, that is in scope and worth saying.

## Hardening the deployment

Configuration that materially changes the attack surface — token scopes, the
ruleset path jail, request caps, gRPC TLS — is documented in
[Configuration](docs/reference/configuration.md). The reload security model,
including signature verification and key rotation, is in
[Hot-reloading rulesets](docs/how-to/hot-reload.md).
