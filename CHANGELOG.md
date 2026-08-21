# Changelog

All notable changes to `fathom-rules` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries below are curated. Every release also has generated notes with the full
commit list on its
[GitHub release page](https://github.com/KrakenNet/fathom/releases); the tag/PyPI
gaps between 0.3.1 and 0.5.0 are explained under
[Release history notes](#release-history-notes).

## [Unreleased]

### Added
- `Engine(match_evidence=True)` records which facts, with which slot values,
  fired each rule. `EvaluationResult.match_evidence` and
  `AuditRecord.match_evidence` hold one entry per firing, each naming the
  fact behind every condition element on the rule's left-hand side —
  including for assert-only rules that never produce a decision. clipspy
  exposes no accessor for an activation's basis, so the evidence is compiled
  in: the flag is off by default and the generated CLIPS is byte-identical
  to before while it stays off.

## [0.10.0] - 2026-08-20

### Added
- A declared public surface. `VERSIONING.md` names what this project
  supports — the Python symbols, the YAML authoring keys, the REST, gRPC
  and MCP contracts, the CLI, and the `FATHOM_*` variables — and
  `tests/test_public_surface.py` fails when that list and `fathom.__all__`
  disagree. Before this, `__all__` existed on the top-level package and
  nowhere else, so every other module's contents were public by accident of
  import. `__all__` is now declared on `engine`, `models`, `errors`,
  `audit`, `fleet`, `attestation`, and `chained_log`; the top-level package
  re-exports the audit sinks, the fleet types, the full exception hierarchy
  (`FathomError` was not exported at all, so `except FathomError` needed a
  submodule import), and the attestation and chained-log entry points.
  Those last four resolve through a module `__getattr__` so `import fathom`
  still works without the optional `attestation` extra; touching one
  without it raises `ImportError` naming the extra.
- `docs/reference/configuration.md`: all thirteen `FATHOM_*` variables with
  their defaults, the token scopes for both authenticated surfaces, and the
  gRPC TLS story — the server refuses to start without a key pair unless
  `FATHOM_GRPC_ALLOW_INSECURE=1`, which was true in the code and written
  down nowhere.
- A how-to for Policy Studio: how to run it from a checkout (it is not on
  PyPI), how its token gate works, what its five views drive, and the four
  things it is not — a sandbox, a stable API, a durable audit log, or safe
  to expose.
- `metadata` on the evaluate response, everywhere. A firing rule's
  `then.metadata` was dropped on the floor by `/v1/evaluate` and absent from
  the gRPC response; it now reaches REST, gRPC, and the Go and TypeScript
  clients.

### Fixed
- A pack that declared modules but no `focus_order:` fired nothing at all.
  CLIPS drains only the agenda of the module holding the focus, so with an
  empty focus list every rule scoped to a declared module sat unfired and
  the caller got the default decision back — a wrong answer, not an error,
  from a pack whose rules all matched. `load_modules` now focuses the
  declared modules in declaration order when nothing else has set a focus;
  an explicit `focus_order:` or an earlier `set_focus` still wins.
- `attestation_token` was structurally always null on `/v1/evaluate`. The
  REST app held an attestation service on `app.state` and then built its
  engines without it, so a configured service signed nothing the API
  returned. The service is now threaded into both the stateless engine and
  the session engines.
- gRPC could not tell "no rule decided" from a decision of `""`: proto3
  sends an unset string as empty to every client. `decision` and `reason`
  are now `optional`, and the Go gRPC client reads back the
  `attestation_token` it previously discarded.
- Eight reference pages described validators, YAML forms, and a call
  signature that had not existed since 0.9.0 — one of them taught rule YAML
  that no longer compiles (bare `expression: active`, `alias: req`).
- The release gate could not pass, on any release. It waited for every check
  run on the tagged commit to finish — including the three publish workflows
  the tag itself starts, each of which calls that same gate and queues its
  own build, sign and publish jobs behind it. Every gate sat waiting for its
  siblings and for itself, timed out after 20 minutes, and failed. It now
  ignores the check suites the tag started and judges the commit on the
  checks its branch ran. **0.9.0 was tagged and released on GitHub but never
  reached PyPI because of this**; 0.8.0 is the newest release there until
  this one publishes.
- Merging pull requests back to back cancelled the test matrix on the commits
  left behind: `cancel-in-progress` was keyed on the ref, and on main every
  merge shares one. A cancelled check is not a passing one, so a commit cut
  as a release tag could arrive with no test evidence at all — which is what
  happened to 0.9.0. Pull-request runs still supersede each other; pushes are
  keyed on their own SHA and never cancel.

### Changed
- The audit record carries its own signature. `docs/concepts/audit-attestation.md`
  claimed an exported audit line could not be modified without breaking
  `verify_token`, while the same page said two sections earlier that the JWT
  was deliberately kept off `AuditRecord`. The second statement was the true
  one, so the claim was empty: a line lifted out of the log carried no
  signature at all. `AuditRecord` now has `attestation_token`, and
  `ChainedAttestationLog` satisfies `AuditSink`, so
  `Engine(audit_sink=ChainedAttestationLog(path, service))` writes
  evaluations into a hash-chained log where a deleted or reordered entry
  breaks linkage — which a per-line signature cannot detect.
- The threat model now separates what the token covers (decision,
  rule_trace, session, iat, input_hash) from what it does not (reason,
  metadata, duration, the fact lists).
- The PyPI classifier moves from Alpha to Beta. Not to Production/Stable:
  that is a claim about a 1.0 readiness audit that has not happened.
- The doc-source freshness gate blocks the branch that caused the drift.
  It was advisory everywhere, and a warning nobody reads is not a gate — but
  a whole-repo version fails whoever opens the next pull request rather than
  the author who changed the source. The required `docs` job now runs it
  scoped to the sources the branch itself touched; the whole-repo sweep
  stays advisory.
- The benchmark gate's slack factor is measured rather than guessed. Five
  consecutive runs put the single-rule median at 1.2x to 1.9x of the
  developer machine the published targets come from, and the gate sat at
  1.5x — failing on the hardware instead of on the code. It is 2.0x now, and
  README, the workflow, and the script all state the measurement.
- Release automation: pre-1.0 breaking changes take a minor bump rather than
  a major one, and both commits a release pull request carries are signed
  off, so the DCO check no longer needs a hand-written remediation commit on
  every release.

### Security
- `SECURITY.md` has a policy instead of three lines. It named 0.7.x as the
  supported version after 0.8.0 had shipped, and offered no disclosure
  timeline, no embargo, and no CVE process. The support window now points at
  `VERSIONING.md` instead of a table that goes stale every release,
  disclosure is coordinated through GitHub's CNA with a 90-day backstop, and
  scope is explicit in both directions. The out-of-scope list matters most:
  `test:` conditional elements and `type: raw` functions emit author-written
  CLIPS verbatim by design, and `FATHOM_GRPC_ALLOW_INSECURE` and the
  unsigned-ruleset dev escape each require an explicit opt-in and log what
  they turned off. Unstated, every one of those reads as a finding.

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
