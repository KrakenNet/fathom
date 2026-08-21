# Versioning and stability

This document says which parts of Fathom you can build on, what a version
number change means for them, and how long a released version is supported. It
is enforced where it can be: `tests/test_public_surface.py` fails if the symbol
list below stops matching `fathom.__all__`.

Fathom is pre-1.0. Read [Pre-1.0 semantics](#pre-10-semantics) before you pin.

## Covered surfaces

### Python: `fathom.__all__`

These names are importable from the `fathom` package and are the covered
Python surface:

<!-- BEGIN COVERED SYMBOLS -->
- `AssertSpec`
- `AssertedFact`
- `AttestationError`
- `AttestationService`
- `AuditLog`
- `AuditRecord`
- `AuditSink`
- `ChainedAttestationLog`
- `CompilationError`
- `Engine`
- `EvaluationError`
- `EvaluationLimitError`
- `EvaluationResult`
- `FactStore`
- `FathomError`
- `FileSink`
- `FleetConnectionError`
- `FleetEngine`
- `FleetError`
- `InMemoryFactStore`
- `NullSink`
- `ScopeError`
- `ValidationError`
- `__version__`
- `verify_chain`
- `verify_token`
<!-- END COVERED SYMBOLS -->

`AttestationService`, `verify_token`, `ChainedAttestationLog`, and
`verify_chain` are resolved on first attribute access rather than at import,
because they need the optional `attestation` extra. Accessing one without that
extra installed raises `ImportError` naming the extra — it is not an
`AttributeError`, and the name is covered either way.

Each of these submodules also declares its own `__all__`, which is covered on
the same terms when imported directly (`from fathom.models import
RuleDefinition`):

| Module | What it holds |
|---|---|
| `fathom.engine` | `Engine`, and the `fathom-` prefix reserved for built-in CLIPS functions |
| `fathom.models` | The Pydantic models for the YAML authoring surface, the evaluation result, the audit record, and the REST request/response bodies |
| `fathom.errors` | The exception hierarchy, all rooted at `FathomError` |
| `fathom.audit` | The audit sink protocol and the sinks that ship with it |
| `fathom.fleet` | `FleetEngine`, the fact-store protocol, and the in-memory store |
| `fathom.attestation` | Ed25519 signing and token verification |
| `fathom.chained_log` | The hash-chained attestation log and its verifier |

### Other covered surfaces

- **The YAML authoring surface** — every key documented under
  [`docs/reference/yaml/`](docs/reference/yaml/index.md): the fields each
  construct accepts, the condition-expression grammar, and the operator set.
- **The REST API** — the paths, request bodies, and response bodies published
  in [`docs/reference/rest/openapi.json`](docs/reference/rest/openapi.json).
- **The gRPC service** — the messages and RPCs in
  [`protos/fathom.proto`](protos/fathom.proto).
- **The MCP tool surface** — the tool names and argument schemas in
  [`docs/reference/mcp/manifest.json`](docs/reference/mcp/manifest.json).
- **The CLI** — the command names, their documented options, and their exit
  codes. Human-readable output text is not covered; parse the JSON output
  where a command offers it.
- **Environment variables** — every `FATHOM_*` variable documented in the
  configuration reference.

## Not covered

Anything not named above is internal, and may change in any release without
notice or a changelog entry:

- Modules with no `__all__`, and any name a module's `__all__` omits.
- Any name beginning with `_`, at any level.
- **The generated CLIPS text.** Construct layout, and in particular the
  generated variable names (`?s_<index>_<slot>`, `?<alias>-<slot>`), are
  compiler implementation. Use `bind:` to name a variable you need to
  reference.
- Rule firing order beyond what salience and `focus_order` specify.
- Wall-clock timings, including the published performance targets. They are
  measurements of an implementation on one machine, not a contract.
- Policy Studio (`packages/fathom-studio/`). It ships as its own package on
  its own version line, and its routes — including the REST app it mounts
  under `/api` — are not covered here.
- The Go and TypeScript SDKs, which are pre-release and version separately.
- Test helpers, fixtures, and everything under `tests/` and `scripts/`.

## Pre-1.0 semantics

Fathom is in the `0.x` series, and `0.x` is not semver's stable contract. What
this project does within it:

- **A minor bump (`0.9.0` → `0.10.0`) may break a covered surface.** Breaking
  changes are held to minor releases and never appear in a patch. This is
  enforced in `release-please-config.json` by `bump-minor-pre-major`, which
  routes a `BREAKING CHANGE:` commit to a minor rather than to `1.0.0`.
- **A patch bump (`0.9.0` → `0.9.1`) never breaks a covered surface.** Bug
  fixes and additions only.
- **Every break is in the changelog**, under `### Changed` or `### Removed`,
  with what to do instead. `CHANGELOG.md` is hand-written for exactly this
  reason.

Pin accordingly: `fathom-rules>=0.10,<0.11` is the pre-1.0 equivalent of a
caret range. `fathom-rules~=0.10.0` has the same effect.

After 1.0 this becomes ordinary semver: breaking changes only in a major.

## Deprecation

A covered name is never removed without a deprecation period first:

1. The name keeps working and starts emitting `DeprecationWarning`, naming its
   replacement.
2. The changelog entry for that release records the deprecation.
3. Removal comes no earlier than the **second** minor release after the
   warning first shipped — so a name deprecated in `0.10.0` may not be removed
   before `0.12.0`.

A name that never worked (it raised on every call, or was documented but not
implemented) can be removed without this period; the changelog says so.

## Supported versions

The latest released minor is supported. Fixes — including security fixes — are
released as a new patch of that minor, not backported to earlier ones. Pre-1.0
that is the whole support window; upgrading to the current minor is the
supported response to a fix.

See [SECURITY.md](SECURITY.md) for how to report a vulnerability and what
happens after you do.

## Verifying what you installed

Releases are signed. `fathom verify-artifact` checks a downloaded artifact
against the project's minisign key; see
[Release signing](docs/how-to/release-signing.md) for the key and the
verification steps.
