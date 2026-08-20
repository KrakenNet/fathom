# Changelog

All notable changes to `fathom-rules` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries below are curated. Every release also has generated notes with the full
commit list on its
[GitHub release page](https://github.com/KrakenNet/fathom/releases); the tag/PyPI
gaps between 0.3.1 and 0.5.0 are explained under
[Release history notes](#release-history-notes).

## [0.9.0] - 2026-08-20

### Changed (breaking)
- `focus_order` runs modules in the order it lists. The list was pushed onto
  the CLIPS focus stack reversed, so the last module named ran first. A
  multi-module ruleset that relied on the old behaviour must reverse its
  list; single-module rulesets, and rulesets whose modules do not write
  competing decisions, are unaffected.

### Fixed
- The Docker image builds again — `mkdir -p /rules` ran after the switch to a
  non-root user — and CI now builds it, runs it, and checks the container's
  identity on every pull request.
- The TypeScript SDK no longer sits beside a second, stale API spec. The
  repo-root `openapi.json`, frozen at 0.3.0, and the dead generated client
  that was never imported are both gone;
  `docs/reference/rest/openapi.json` is the only spec.

### Security
- Publishing is gated on green required checks and runs from tag pushes only.
  `workflow_dispatch` is gone from the publish path, which previously let any
  account with write access publish signed artifacts built from any ref, and
  every third-party action in that path is pinned to a commit SHA.
- Dependabot no longer auto-merges `github_actions` bumps: those PRs rewrite
  the workflows that hold the signing key and the PyPI identity.
- Every user-installable requirement carries an upper version bound, so a
  future major release cannot be resolved into an install this release was
  never tested against.

### Changed
- CI enforces the published performance targets (`bench`, with a documented
  1.5x allowance for shared runners), the version numbers printed in prose,
  the dependency diff on each pull request, and a build of
  `packages/fathom-editor`.
- A determinism test asserts the engine's core claim directly: the same facts
  produce the same decision across repeated and re-ordered runs.
- The release-signing guide scopes its guarantee to 0.5.0 and later; the five
  earlier PyPI releases are unsigned.

## [0.8.0] - 2026-08-19

### Removed (breaking)
- `fathom.studio` — the Policy Studio moved to its own `fathom-studio`
  distribution. `import fathom.studio` and `python -m fathom.studio.app` now
  fail; install `fathom-studio` and import `fathom_studio`.
- `Engine.__init__(experimental_backward_chaining=...)` — a permanent no-op
  that emitted a `FutureWarning` and read like a feature. Passing it now
  raises `TypeError`. There is no replacement; backward chaining stays a v2
  item.

### Changed (breaking)
- Agent adapters block every decision that is not `allow`. A ruleset that
  relied on an unmatched tool call proceeding must add an explicit allow rule
  or configure a default decision.
- `AttestationService.sign(...)` raises `AttestationError` when `input_facts`
  is `None`. Callers relying on the implicit empty-list default must pass the
  facts the decision was computed over, or `[]`.
- Ruleset validation is strict: unknown keys, duplicate rule names, duplicate
  pattern aliases and malformed condition expressions no longer compile, and
  rule-level `metadata:` moves under `then:`.
- `POST /v1/reload` returns `ruleset failed to compile` or `unable to read
  ruleset_path` instead of echoing the compiler diagnostic or the OS error in
  `detail`. The diagnostic goes to the server log.

### Fixed
- Attestation tokens are bound to the facts they were computed over, and
  `then.log` reaches the audit sink.
- Transport requests are bounded, and REST and gRPC share one session store.
- Rule-pack salience ordering is correct and pack loading reports what it
  actually loaded.
- Dependency advisories cleared across the Python lock and the Go module.

## [0.7.4] - 2026-07-20

### Changed
- Documentation only: SSVC listed among the shipped rule packs, stale CLI
  comments corrected, and the docs drift gate unstuck from a post-squash SHA.

## [0.7.3] - 2026-06-24

### Fixed
- CI: foreign documentation generators fail loudly instead of silently
  emitting nothing, `protoc-gen-go` is pinned, and the freshness gate ignores
  mechanical dependency bumps.

## [0.7.2] - 2026-06-24

### Changed
- Documentation only: Getting Started and CONTRIBUTING made accurate and
  runnable, plus `last_verified` re-verification across several pages.

## [0.7.1] - 2026-06-24

### Fixed
- Dependabot configuration: `cooldown.default-days` replaces the
  `semver-*-days` keys, which are unsupported for non-semver ecosystems and
  made the whole config invalid.

## [0.7.0] - 2026-06-06

### Added
- Go SDK gRPC client wrapper that handles `SubscribeChanges` reloads.
- Admin token and request-body cap for ruleset reload over REST and gRPC.
- SSVC supplier, deployer and CISA decision trees, built from pinned
  authoritative sources.
- Policy Studio scaffold: panels, seed scenarios and guardrails.

## [0.6.0] - 2026-06-05

### Added
- gRPC `SubscribeChanges` streams are cancelled on ruleset reload, so a client
  never receives events from two different rulesets (ADR-0002, option a).

### Changed
- `experimental_backward_chaining` documented as a reserved no-op rather than
  an in-progress feature.

## [0.5.0] - 2026-06-05

### Added
- Hash-chained JWS attestation log and the `fathom verify-chain` command.

### Changed
- Re-released the 0.4.0 tree under a `v*.*.*` tag, the pattern
  `pypi-publish.yml` matches. 0.4.0 itself never reached PyPI.

## [0.4.0] - 2026-06-05

Tagged `fathom-rules-v0.4.0` and never published to PyPI; its contents reached
users as 0.5.0.

### Added
- `Engine.reload_rules()` atomic swap and the `Engine.ruleset_hash` property.
- REST `GET /v1/status` and `POST /v1/rules/reload`; gRPC `Reload` RPC.
- Ruleset signature verification, with the public key bootstrapped from the
  environment.
- `fathom status` and `fathom verify-artifact` commands, and
  `AttestationService.sign_event` for arbitrary payloads.
- SSVC rule pack — templates, rules and modules — with the CISA source
  archived alongside it.
- minisign release signing: `scripts/sign_release.sh`, the committed public
  key, and a pure-Python verifier.
- Go SDK gRPC stubs committed at `packages/fathom-go/proto/`.

## [0.3.3] - 2026-05-14

Tagged and released on GitHub; never published to PyPI.

### Added
- gRPC `SubscribeChanges` RPC now emits real fact-change events. `Engine`
  exposes `subscribe(callback) -> unsubscribe`; `FactManager` fires listeners
  on every successful assert/retract, and the gRPC servicer pushes
  `FactChange` protos until the client disconnects. The previous
  no-op `iter([])` stub is gone.

### Removed (breaking)
- `FunctionDefinition.type = "temporal"` — vestigial. Temporal operators
  (`changed_within`, `count_exceeds`, `rate_exceeds`, `last_n`,
  `distinct_count`, `sequence_detected`) have always been Engine-registered
  Python externals; the YAML `type: temporal` declaration was a no-op
  emitting `""`. Any rule pack still declaring `type: temporal` will fail
  Pydantic validation with a clear error. Migration: delete the redundant
  `FunctionDefinition` entries — temporal operators continue to work in
  rule conditions without any function declaration.

## [0.3.2] - 2026-04-27

Published to PyPI from an untagged commit; there is no `v0.3.2` tag and no
GitHub release.

### Fixed
- CI and documentation-generation fixes made between 0.3.1 and 0.3.3.

## [0.3.1] - 2026-04-17

### Added
- PyPI publishing workflow.

### Fixed
- Pydantic import failures in the published wheel.

### Changed
- Supported Python baseline moved from 3.14 back to 3.13.

## [0.3.0] - 2026-04-14

### Added
- `ConditionEntry.test` field: raw-CLIPS escape hatch on the LHS. When set,
  the compiler emits `(test <raw>)` verbatim as a test CE. Pairs naturally
  with `Engine.register_function` so user-registered externals can now be
  called from rule conditions, not just from `then.assert` slot values.
  Standalone `test` (no `slot`/`expression`/`bind`) emits a bare
  `(template)` pattern plus the test CE; combined with `bind`/`expression`,
  both the slot pattern and the test CE are emitted.
- `ConditionEntry.slot` is now optional (defaults to `""`) when `test` is
  the only field set. Still required when `expression` or `bind` is set.

## [0.2.0] - 2026-04-14

### Added
- `then.assert` action block in the YAML rule DSL: rules may now emit one or more
  user-defined facts alongside the existing decision action, compiling to
  `(assert (<template> (<slot> <value>) ...))` forms on the rule RHS.
- `ConditionEntry.bind` field: LHS patterns can bind slot values to variables
  (`?var`) that are interpolated into `then.assert` slot values at compile time.
- `Engine.register_function(name, fn)`: public API for registering Python
  callables as CLIPS user functions, wrapping the previously-private
  `self._env.define_function`.

### Changed
- `AuditRecord.asserted_facts` is now populated with the list of user facts
  asserted during evaluation (template + slot values), in addition to the
  existing decision record.

## Release history notes

- **0.3.2** is on PyPI with no matching git tag; it was published from an
  untagged commit.
- **0.3.3** and **0.4.0** are tagged and have GitHub releases but never reached
  PyPI. `pypi-publish.yml` fires on `v*.*.*`, and 0.4.0's tag is
  `fathom-rules-v0.4.0`, which that pattern does not match; 0.3.3 predates the
  workflow being wired up. Both trees shipped to PyPI as 0.5.0.
- Release artifacts are minisign-signed from **0.5.0** onward. The five earlier
  PyPI releases (0.1.0 through 0.3.2) are unsigned, and the GitHub releases for
  0.3.0, 0.3.1, 0.3.3 and 0.4.0 carry no assets at all.
