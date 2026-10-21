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
### Changed
- **An evaluation during which a rule errors now raises `EvaluationError`.**
  CLIPS reports a runtime error in a condition, a `test:` CE or an action by
  printing it and carrying on, and Fathom used to return whatever decision had
  been written by then — so an allow won over the deny that errored. A caller
  could trigger it on purpose with a slot value over the 4096-character
  `matches` cap. REST answers 500 and gRPC `INTERNAL`; no decision is
  returned. Fix the rule, or bound the input before it reaches the engine.
- **An unknown classification level now stops the evaluation.** A level
  outside the hierarchy (a typo, a different case, a label from another
  ladder) on either side of `below`, `meets_or_exceeds`, `within_scope`,
  `<hier>-below`, `<hier>-meets-or-exceeds`, `<hier>-within-scope` or
  `fathom-dominates` raises `EvaluationError`, so allow and deny rules both
  fail closed. REST, gRPC and MCP return their `evaluation failed` error.
  `fathom.engine.dominates` raises `EvaluationError` for an unknown level or
  hierarchy instead of returning `False`. Such a level used to rank -1 and
  compare, so `secret` met `TOP-SECRET` and `none` met `codeword`. Make every
  classified slot hold a declared level (`allowed_values` rejects a bad label
  at assert time), and handle `EvaluationError`.
- **A classification operator with a `$alias.field` argument is a
  `CompilationError` when more than one hierarchy is loaded.** It used to rank
  through the first hierarchy, so every level of a second one compared true.
  With one hierarchy it compiles to that hierarchy's scoped deffunction.
- **`contains($alias.field)` joins on the referenced value** instead of
  matching the literal text `"$alias.field"`, and an undeclared alias is a
  compile error. `matches($alias.field)` is a `CompilationError`: the pattern
  must be a literal.
- **A temporal operator called wrongly fails to load.** Too many arguments, a
  non-numeric threshold or window, or a malformed `sequence_detected` event
  list is a `CompilationError` at load and in `fathom validate`; it used to
  load and then raise or fail open at evaluation. Temporal operator
  signatures are now documented.
- **`then.scope` is no longer accepted**; it was never emitted. Delete it, and
  use `action: scope` and `then.metadata`.
- **A `matches` pattern that is not a valid Python regex no longer loads.** It
  raises `CompilationError` at load instead of erroring on every fact. Fix
  the pattern.
- **gRPC `AssertFact`, `Query`, `Retract` and `SubscribeChanges` need a
  `session_id`.** An empty one is refused with `INVALID_ARGUMENT`. It used to
  reach the server's default Engine — on a server that mounts one, the served
  policy — so one caller's `AssertFact` or `Retract` changed every later
  caller's decision, and `SubscribeChanges` streamed every caller's facts.
  REST already refused these calls without `X-Session-Id`. Open a session
  with `Evaluate` and pass its id; a server that mounts an Engine refuses
  sessions, so it offers none of these four calls, as on REST.
- **A session id longer than 128 characters is refused** (REST 422 in a body,
  400 in `X-Session-Id`; gRPC `INVALID_ARGUMENT`), and the OpenAPI spec
  declares `maxLength`. Such ids used to be accepted; use a shorter one.
- **REST request bodies refuse keys they do not declare** with 422
  `validation_error` instead of ignoring them, so a misspelled `sesion_id` no
  longer runs stateless. `/v1/data` still ignores unknown keys, as OPA does.
- **REST `build_app()` returns a new app** with its own state and session
  store on every call, not the module-level `app`. Serve the object it
  returns; configuring it no longer changes what `uvicorn
  fathom.integrations.rest:app` serves. The private module attribute
  `session_store` is gone; use `app.state.session_store`.
- **A gRPC `filter_json` of `null` on `Query` and `Retract` is
  `INVALID_ARGUMENT`** instead of matching every fact; `Retract` with `null`
  deleted every fact of the template. Send an empty `filter_json` to match
  every fact.
- **MCP tool input-schema titles are `fathom_<tool>Arguments`** instead of
  `tool_<tool>Arguments`, which froze private function names into the
  manifest.
- **`null` is no longer a value for a required slot.** It is refused as a
  missing slot (REST 422), and `null`, booleans, objects and arrays are
  refused in any string slot (REST 422, gRPC `INVALID_ARGUMENT`). They were
  stored as the string `"None"`, `"True"`/`"False"` or a Python repr, which
  `matches(.+)` accepts, so `"id": null` was allowed. Omit an optional slot
  instead of sending `null`, and send the string you mean, e.g. `"TRUE"` for
  the hipaa pack's `data_transfer.encrypted`.
- **A query, count or retract filter naming an undeclared slot raises
  `ValidationError`** (REST 422, gRPC `INVALID_ARGUMENT`). It used to match
  nothing, or with a `null` value everything: `DELETE /v1/facts` with
  `{"x": null}` emptied the template.
  `FleetEngine.query` applies the same check; an unknown `null`-valued key
  used to match every fleet fact.
- **A rule naming an unregistered template is a `CompilationError` at
  load**, in `load_rules`, `reload_rules` and `fathom validate`: a pattern
  (even with no slot conditions), a `then.assert` (even with no slots) or a
  temporal operator argument; an unregistered slot in a `then.assert` or a
  temporal argument is refused too. CLIPS used to invent the template, and
  the rule never matched or failed at evaluation.
- **Template, module, function and rule files reject unknown top-level
  keys**, in every loader, `reload_rules`, `POST /v1/compile`, `fathom
  compile` and `fathom validate`. A misspelled `focus_order:` fell back
  silently to declaration order.
  `POST /v1/compile` compiles through the same function as `fathom compile`,
  and `fathom validate` refuses a document with no construct, so all three
  and the loaders refuse a file holding only `focus_order:`, only unknown
  keys, `{}` or `functions: []`, and a classification function with no
  `hierarchy_ref`; `POST /v1/compile` now compiles function files.
- **A `focus_order` naming a module the engine does not have raises
  `CompilationError`** from `load_modules`, `load_pack_dir` and `from_rules`,
  not a bare `ValueError`, and a loose pack YAML file that does not parse
  raises `CompilationError` naming the file, not a raw YAML error. Load the
  dependency pack first.
- **A repeated mapping key is invalid YAML.** Every YAML Fathom parses goes
  through `fathom.yaml_utils.safe_load`; a second `expression:` used to
  replace the first and reverse the rule.
- **A `NaN` or infinite value in a `float` or `integer` slot is refused with
  `ValidationError`** on every fact entry path. `NaN` satisfied both
  `less_than` and `greater_than`, so an allow-only rule granted it, including
  over REST with a raw `NaN` body.
- **`Engine.assert_facts` and `Engine.step(facts=)` raise `ScopeError` for a
  fleet-scoped template**, as `assert_fact` and `evaluate_once` did, checking
  the whole batch first. Use `FleetEngine.assert_fact`.
- **A rule whose `then.assert` targets a `scope: fleet` template is a
  `CompilationError`.** The fact used to stay in the session that fired the
  rule. Assert a session-scoped fact and publish it with
  `FleetEngine.assert_fact`.
- **`FleetEngine.assert_fact` stores the validated fact** (defaults applied,
  values coerced) on the in-memory, Redis and Postgres stores, not the raw
  caller dict. Filter on the coerced value, e.g. `"123"` for a string slot.
- **Breaking: `FleetEngine.create_session` raises `FleetError` when the
  session id already exists**, instead of silently replacing the session.
  Call `replace_session(session_id)` to rebuild one.
- **Breaking: `FleetEngine.sync_fleet_facts` takes the session id instead of
  the `Engine`**, like `assert_fact`. Every session-addressing method raises
  `KeyError` for an unknown id.
- **`PostgresFactStore` no longer dispatches a change to subscribers in the
  writing process directly**; they hear it through LISTEN like every peer, so
  each change arrives once and after commit.
- **`RedisFactStore` retries only connection errors and timeouts**; other
  Redis errors raise `FleetError` at once.
- **`Engine.template_registry`, `module_registry` and `rule_registry` return
  read-only mappings whose values are deep copies**, and `Engine.hierarchy()`
  returns a copy. Mutating a returned definition no longer changes
  validation or Rego export. Load or reload rules to change them.
- **Breaking: `Engine(...)` raises `ValueError` for a negative `run_limit`**
  (it used to disable the budget silently) and for a `default_decision` that
  is not `None` or a rule action (it used to be returned verbatim).
  `Engine.load_rules` on a missing path raises `CompilationError`, like the
  other loaders, not `FileNotFoundError`.
- **Breaking: `fathom.rego.convert_file` is renamed to
  `convert_source(source, *, filename="policy.rego", template="input")`.** It
  takes Rego text, as before, and now accepts `template=` like `convert_ast`
  and the CLI. `flatten_input` takes the document as its only positional argument, `export_engine` is typed
  `engine: Engine`, and `OPA_DOWNLOAD_URL` is no longer in
  `fathom.rego.__all__`.
- **`fathom convert rego` and `fathom convert to-rego` exit 3 and write
  nothing when a `deny` rule cannot be translated**; `convert_ast` and
  `export_engine` raise `CompilationError`. A dropped `deny` used to exit 0
  with a policy that allowed what the original denied. That includes a
  `matches` regex OPA's RE2 cannot evaluate (lookaround, backreferences,
  atomic groups, conditionals), which used to export cleanly, error in OPA
  and never fire. `fathom convert to-rego` on a ruleset that does not compile
  exits 1, like every other command that loads a rule pack.
- **A missing CLI dependency exits 3 with a one-line install hint**:
  `fathom mcp` without the `mcp` extra (was 1), and the `fathom` script
  installed without the `cli` extra (was a traceback and 1).
- **Pack-loading CLI commands exit 2 on an empty directory or a file
  argument.** `info`, `bench`, `repl`, `mcp` and `test` exit 2 on a
  directory with no YAML files, like `validate` and `compile`, instead of
  running an empty engine, and every pack-loading command exits 2 on a file
  argument instead of 1.
- **`fathom bench` refuses `-n` below 1 and `-w` below 0** as a usage error
  (exit 2) instead of crashing with "no median for empty data".
- **Breaking: `verify_token` checks the token kind.** Evaluation
  attestations carry `typ: "fathom.evaluation"` and are the default;
  hot-reload and other `sign_event` tokens carry `typ: "fathom.event"` and
  must be verified with `verify_token(token, key, typ="fathom.event")`. A
  chained-log line or event token is no longer accepted as an evaluation
  attestation. Tokens issued before this release have no `typ`; verify them
  with `typ=None`.
- **Breaking: `AttestationService.sign_event` merges `iss`, `iat` and `typ`
  after the payload**, so a payload can no longer override them.
- **Breaking: `verify_chain` refuses a chained-log line that is not the
  writer's canonical JSON** (whitespace, duplicate keys, non-integer
  `seq`/`iat`), and `ChainedAttestationLog.append` refuses records containing
  NaN or Infinity with `AttestationError`. Logs that earlier versions wrote
  with NaN no longer verify.
- **Breaking: `AttestationService(private_key, public_key)` raises
  `AttestationError` when the public key does not match the private key.**
- **Shipped packs refuse the spellings that slipped past their deny rules.**
  The `nist-800-53`, `cmmc` and `hipaa` symbol slots a deny rule matches
  against a fixed set now have `allowed_values`, so `protocol="FTP"`,
  `classification="Secret"` or `action="Admin"` raise `ValidationError` at
  assert instead of being allowed. `hipaa` `data_transfer.encrypted` is a
  string: anything but `true` (any case) denies a PHI transfer, and `phi`
  matches in any case. A blank `justification`, `context`, `subject` or
  `resource` now triggers the `hipaa`, `nist-800-53` and `cmmc` rules that
  require one, and the NIST AC-4/SC-7/AC-17, CMMC AC.L2-3.1.3 and OWASP
  exec-tool matches ignore case. Pack denies also cover every value their
  templates accept: hipaa denies unencrypted `ePHI`/`phi_record`; cmmc
  denies `execute`/`export` without a justification and
  `escalate`/`override` without a subject; nist AU-12 covers `export`. The
  hipaa `transmission-security` rule no longer uses a lookahead, so the
  exported pack denies an unencrypted PHI transfer.
- **The TypeScript SDK versions separately from the engine.** It is its own
  release-please component, tagged `fathom-ts-vX.Y.Z`, and `npm-publish.yml`
  runs only on that tag.
- **VERSIONING.md covers more surfaces:** the rule-pack format (the
  `fathom.packs` entry-point group, directory layout, `PACK_DEPENDENCIES`) and
  the shipped packs' names, templates and slots (a rule fix that changes a
  pack's decision may still ship in a minor); `fathom.compiler.Compiler`;
  `fathom.integrations` and its REST, gRPC, MCP, LangChain, CrewAI, OpenAI
  Agents and Google ADK modules; `fathom.rego`; `fathom.fleet_redis` and
  `fathom.fleet_pg`; and the classification CLIPS built-ins. Each module now
  declares `__all__`, so `from module import *` imports only the covered
  names.

### Fixed
- **`RedisFactStore.subscribe` delivers every change made after it
  returns.** A change written before the listener's first read, or between
  two idle reads, was lost. `subscribe()` now reads the stream's last entry
  id before it returns, so it can raise `FleetConnectionError` or
  `FleetError`.
- **A filtered `PostgresFactStore.retract` announces only the rows it
  deleted.** Two concurrent retracts of one fact each announced it; now each
  fact is counted and announced once, as on the other stores.
- **`PostgresFactStore` splits connection errors from other errors.** A
  connection lost mid-statement raises `FleetConnectionError` (it raised
  `FleetError`), and asyncpg `InterfaceError` is wrapped in `FleetError`
  (it escaped unwrapped), on every operation including `subscribe`.
- **`pip install fathom-rules[cli]` installs a CLI whose every command
  runs.** The `cli` extra now declares `httpx`, `cryptography` and `pyjwt`,
  which the CLI imports; without them every command, `fathom --version`
  included, failed with `ModuleNotFoundError`, and `fathom verify-chain`
  still did after the first two were added. CI runs every command's happy
  path from a `[cli]`-only install.
- **An unsigned `Engine.reload_rules` works on a core-only install.** It
  imported `cryptography` before checking whether a signature was given.
- **Temporal operators give the same decision in any assertion order.**
  `count_exceeds`, `rate_exceeds`, `last_n`, `distinct_count`,
  `sequence_detected`, `schema_frequency_exceeds` and `changed_within` are
  judged over the whole fact set when `evaluate`/`evaluate_once` runs; a
  request asserted before its history was judged against an empty history.
  `Engine.step` keeps its fire-once-per-new-match behaviour.
- **A failed `load_rules` leaves no rule behind.** Rules built before the
  failing one stayed live, so an engine that kept serving ran an allow
  without the deny meant to outrank it.
- **A `bind:` on a cross-referenced slot plus a `not_equals`,
  `greater_than`, `less_than` or classification cross-ref builds.** It
  failed with a raw CLIPS ANALYSIS4.
- **The undocumented `dominates` operator is removed**; it loaded and then
  raised on every evaluation. Call `fathom-dominates` from a `test:`
  condition. `in_compartment` and `has_compartments` are now documented.
- **`CompilationError` from a YAML parse names the rejected field and
  reason in its message**, not only in `.detail`.
- **`FunctionDefinition.params` is optional**; neither function type reads
  it.
- **CLIPS diagnostics no longer reach stderr.** CLIPS error blocks and
  Python tracebacks were printed (and root logging configured) on
  `CompilationError` / `EvaluationError`; a pattern-matching error printed
  the whole fact, so content over the `matches` cap (an SSN in an agent's
  output) reached the process log. CLIPS stderr and warnings now go to the
  `fathom.engine` logger at DEBUG; `EvaluationError` still names the error.
- **An evaluation error no longer echoes the raw CLIPS diagnostic, with its
  fact values, to the caller.** REST, gRPC and MCP (`fathom.evaluate`,
  `fathom.trace`) answer `evaluation failed` and log the detail.
- **gRPC answers `INVALID_ARGUMENT` for a fact, filter or JSON the engine
  refuses**, as REST answers 422, including JSON that parses but is not an
  object in `data_json` or `filter_json` on `Evaluate`, `AssertFact`,
  `Query` and `Retract`. It was `UNKNOWN`.
- **A session-scoped gRPC `Evaluate` that names no ruleset opens the
  session** (bound to the empty ruleset), as REST does, instead of answering
  `NOT_FOUND` "create it with Evaluate first". The session contract is
  documented.
- **MCP `fathom.evaluate` and `fathom.trace` return the deciding rule's
  `metadata`**, like gRPC and REST, and under mcp 2.x a tool refused by the
  engine reports why instead of a bare "Error executing tool".
- **`hierarchies:` in a function file is loaded**, as the reference
  documents, by `Engine.load_functions`, `fathom compile` and `fathom
  validate`.
- **A second `ChainedAttestationLog` writer continues from the real head.**
  One opened while another was still running (a rolling restart) appended
  from a stale head and the log verified as tampered. A writer whose file
  was replaced by another log is refused.
- **`ChainedAttestationLog` refuses to append when its log shrank under it**
  (tail truncated, file emptied, replaced or deleted), whether it reopens
  after `close()` or holds the file open. A deleted log got records with no
  genesis that never verified, and a truncated tail was silently re-chained
  and verified ok.
- **`ChainedAttestationLog.close()` is serialised with appends**, so a
  concurrent close no longer surfaces "write to closed file" or a false
  "already open by another process".
- **`verify_chain`, `records()` and `fathom verify-chain` report a deeply
  nested line as malformed** instead of raising `RecursionError`.
- **`verify_chain` accepts a PEM string as the public key** instead of
  treating it as a path.
- **`verify_token` raises `AttestationError`, not `jwt.InvalidKeyError`**,
  for a key that is not an Ed25519 public key.
- **`chained_log.load_or_create_key` hands every concurrent creator the key
  that ends up on disk.**
- **`fathom verify-artifact` checks the trusted comment's global
  signature** like `minisign -V`, and reports a non-UTF-8 `.minisig` or
  pubkey as malformed (exit 3) instead of exit 1.
- **`RulesetSignatureError` is a `FathomError`**, defined in `fathom.errors`;
  `fathom.integrations.ruleset_sig` still re-exports it.
- **Importing `fathom.attestation`, `fathom.chained_log` or
  `fathom.integrations.rest` without its extra names the extra to
  install.**
- **A misspelled `fathom.<name>` is a type error again** under mypy and
  pyright.
- **`RedisFactStore.assert_fact` writes the fact and its stream entry in one
  script**, so a refused XADD no longer leaves a durable fact that
  `FleetEngine` rolled back locally. Concurrent `RedisFactStore.retract`
  calls count and announce each fact once, and the change stream is capped
  at about 10000 entries per template.
- **A raising subscriber callback is logged and skipped on every fleet
  store.** It no longer makes `assert_fact` raise after commit (in-memory,
  Postgres) or ends the Redis subscription.
- **`PostgresFactStore` accepts fleet template names longer than 48
  characters**; a channel name over 63 bytes uses a SHA-256 digest of the
  template. It raises `FleetError` instead of `AssertionError` when used
  before `connect()`.
- **`FleetEngine` stores CLIPS implicit slot defaults** (`""` for a string
  with no default), so `FleetEngine.query` matches what the local engine
  sees. The `ScopeError` for a local fleet retract points at
  `FleetEngine.replace_session()`, and the retraction limitation is in the
  `FleetEngine` class docstring.
- **The Docker image sets `FATHOM_RULESET_ROOT=/rules`**, so the REST sidecar
  serves its declared volume; every evaluate answered 500. The README REST,
  gRPC and MCP examples now work as written.
- **The OpenAPI spec matches what the server sends.** It declares every
  status `POST /v1/rules/reload` and the `GET /v1/templates`, `/v1/rules` and
  `/v1/modules` routes return, `/v1/evaluate`'s 500 and `/v1/data`'s 413,
  types reload's 200 body, declares `/v1/data`'s 422 as `ErrorResponse`,
  marks `X-Session-Id` required, and declares bearer auth as the
  `HTTPBearer` security scheme on every protected operation instead of an
  optional `authorization` header. An unexpected server error answers the
  `ErrorResponse` envelope instead of plain text.
- **REST reload refusals from the path jail, the body-size cap and a
  malformed body are audited** as `ruleset_reload_rejected`.
- **CLI messages keep bracketed text**; rich dropped the `[fathom.cli]`
  prefix as markup.
- **An unexpected error while loading a pack is a one-line CLI error with
  exit 1**, such as the `ValueError` from a cross-pack `focus_order`, instead
  of a traceback from `convert to-rego`. `fathom status` reports a response
  that is not a JSON object instead of a traceback.
- **The CLI exit codes are documented**: 0 success, 1 check failed
  (including a rule pack that does not compile), 2 not found or unreadable
  (shared with usage errors), 3 malformed input, a refused `deny` in either
  convert command, or a missing dependency. how-to/cli.md covers `status`
  and `verify-artifact`.
- **The README's rule-pack names load.** It listed `fathom-owasp-agentic` and
  so on; `Engine.load_pack` takes the entry-point names (`owasp-agentic`,
  ...). It now also lists the `schema-denoising` and `conflict-detection`
  packs and the `fathom mcp` and `fathom convert` commands.
- **The Python example in "Embed the SDK" runs.** It asserted an `access`
  fact that example 01 does not define and raised `ValidationError`.
- **The TypeScript SDK publish uses one secret.** `npm-publish.yml` checked
  `NPM_RELEASE_TOKEN` but published with `NPM_TOKEN`.
- **The docs say where a missing ruleset pubkey stops startup.**
  `build_app()` raises; the module-level `fathom.integrations.rest:app`
  served by Docker and uvicorn starts without the key and answers reload
  `503 not_ready`.
- **CONTRIBUTING describes the changelog promotion.** Following it alongside
  `promote_changelog.py` produced two `## [1.0.0]` headings; the 1.0
  checklist now also covers `docs/index.md` and `SECURITY.md`.
- **The reference docs match the code.** The REST reference states the
  auth, unknown-key, session-limit (1000 sessions, 30 min idle) and
  `/metrics` contract and is no longer marked draft; configuration.md names
  the right readers for `FATHOM_RULESET_ROOT`, `FATHOM_MAX_RELOAD_BYTES` and
  `FATHOM_METRICS`, and `/v1/status` is documented as unauthenticated;
  hot-reload.md matches the reload contract (root-relative path,
  `invalid_ruleset`, valid inline YAML, full list of audited reasons); the
  nonexistent `boolean` slot type is gone and slot-name validation, numeric
  `allowed_values` enforcement and `ttl` expiry are corrected; the
  owasp-agentic page states the 4096-character `matches` cap;
  load-rule-pack.md warns that a local overlay overrides a pack deny and
  corrects which templates hipaa shares; planned-integrations.md corrects
  what the Agents SDK and ADK do when a callback raises.

### Added
- **`fathom mcp <rules>`** starts the MCP tool server over stdio. The pack is
  compiled first, so a broken one exits 1 before any MCP traffic. The MCP
  reference has a launch section.
- **`fathom status --json`.**
- **`fathom.integrations.grpc_server.serve()` takes `attestation`,
  `audit_sink`, `ruleset_pubkey` and `require_signature`**, so `Reload`
  works through the launcher.
- **gRPC `ChangeType` values `CHANGE_TYPE_ASSERT` / `CHANGE_TYPE_RETRACT`**;
  bare `ASSERT` / `RETRACT` remain as deprecated aliases.
- **`FleetEngine.replace_session(session_id)` and
  `FleetEngine.remove_session(session_id)`.**
- **Fleet docs:** reference pages for `fathom.fleet_redis.RedisFactStore`
  and `fathom.fleet_pg.PostgresFactStore`, and a how-to
  (`docs/how-to/fleet.md`) for running a `FleetEngine` over the in-memory,
  Redis and Postgres stores.
- **`fathom.rego.flatten_input(..., declared=...)`** keeps only the named
  slots.
- **`Engine.hierarchy(name)`** returns a loaded classification hierarchy and
  raises `ValidationError` for an unknown name.
- **`Activation`, `RuleMatches` and `RulesetSignatureError` are exported from
  `fathom`**; `fathom.compiler` declares `__all__ = ["Compiler"]`.
- **`Compiler.parse_function_bundle(path)`** returns a function file's
  functions and hierarchies.
- **How to cut 1.0.0** is in CONTRIBUTING.md, and VERSIONING.md has a "From
  1.0" section: semver, pin `fathom-rules>=1,<2`, deprecated names removed
  only in the next major.

## [0.13.0] - 2026-09-09
### Added
- **`Engine.reload_rules(..., preserve_facts=True)`** carries working memory
  into the new environment instead of discarding it, TTL ages included, so the
  incoming rules re-match the facts already there. Off by default: the carry
  runs with the engine lock held, which turns the swap from a pointer
  assignment into a copy proportional to working memory. Change listeners are
  not fired for carried facts, since subscribers already hold them.
- **`Engine.step(facts)`**, an incremental evaluation primitive for streams.
  It runs the same evaluation as `evaluate()` *without* clearing CLIPS
  refraction, so each rule fires once per new match rather than once per call
  — which is what lets a rule count, accumulate, or watch for a sequence over
  a feed. `evaluate()` is unchanged, and a step is never attested and never
  audited: both bind a decision to the inputs it was computed from, and a
  step's result also depends on what fired in earlier steps.
- **`Engine.agenda()`** returns the activations waiting to fire — rule, module,
  salience, and the facts that matched — so you can ask what *would* run before
  running it. Closes the gap `rule_trace` leaves: it reports firings only after
  the fact.
- **`Engine.rule_matches(rule)`** reports how far a rule got toward firing:
  per-pattern matches, partial matches, and activations. The diagnostic for a
  rule that should have fired and did not.
- **`Engine.trace()`**, a context manager that records each rule firing as CLIPS
  saw it, in order, with the facts each one matched. It claims the CLIPS
  `stdout` router for the duration, so a rule's `printout` is captured rather
  than printed.
- **Three MCP tools**: `fathom.agenda`, `fathom.rule_matches`, and
  `fathom.trace`. The four existing tools consult a policy; these three debug
  one, which is what an agent writing rules needs.


## [0.12.1] - 2026-09-09
### Fixed
- **The MCP server works on `mcp` 2.x as well as 1.x.** The `mcp` extra allows
  `>=1.0`, but the server imported `FastMCP` from `mcp.server.fastmcp`, which 2.x
  replaced with `MCPServer` in `mcp.server.mcpserver`. Any install that resolved
  to 2.x raised `ImportError` on import. The server now resolves whichever class
  the installed SDK provides.

## [0.12.0] - 2026-08-28
### Changed
- **`Engine.evaluate_once` retracts the facts rules asserted during the call**,
  not only the caller's own. Code that relied on a derived fact outliving the
  request must use `Engine.evaluate`.
- **A rule is no longer fire-once per engine.** Every rule starts each
  `evaluate()` un-refracted, so a rule that accumulates -- increments a counter,
  adds to a running total -- advances on every call rather than only the first.
  Rules that derive facts are unaffected: CLIPS suppresses a duplicate assert.
- **Classification deffunctions are emitted under the hierarchy's name** rather
  than the function's, so a `test:` CE calling `<function>-below` must now call
  `<hierarchy>-below`.
- **A classification operator naming a level no loaded hierarchy defines is a
  `CompilationError`** instead of an expression silently true for every value.
  A level that two loaded hierarchies both define is a `CompilationError` for
  ambiguity; rename it in one of them.
- **The owasp-agentic pack's `tool_call` template is renamed `tool_request`**,
  matching every framework adapter and the `Engine.evaluate_once` examples.
- **Sessions are refused rather than silently reinvented.** `POST /v1/evaluate`
  with `session_id` returns 400 `sessions_unavailable` on a server that mounts
  an Engine on `app.state.engine`, and the `Evaluate` RPC aborts
  `FAILED_PRECONDITION` when the servicer was built with `default_engine`. Both
  used to open a session compiled from the caller's own `ruleset`.
- **The CrewAI and OpenAI Agents SDK adapters take the framework's own context
  object** instead of `(tool_name, arguments)`, and block by return value rather
  than by raising. `fathom_tool_guardrail` returns a `ToolInputGuardrail` rather
  than a bare coroutine function, and the `crewai` and `openai-agents` extras
  raise their floors to `>=1.5` and `>=0.4`.
- **`FathomAsyncCallbackHandler.on_tool_start` is no longer a coroutine.** Code
  that awaits it directly must drop the `await`; handlers attached to a
  LangChain tool are unaffected.
- **`fathom convert rego` emits slot defaults and per-rule presence guards**, and
  flattens `_` in a key segment to `__`. Re-run the converter rather than
  hand-merging a pack: one converted by an older version still decides `allow`
  for documents OPA denies. `POST /v1/data/...` now answers a document that does
  not fit the ruleset's templates with the default decision and 200, not 500.

### Fixed
- **Standing denials hold on every entry point**, not just the framework
  adapters, and a denied tool is blocked on every dispatch path a framework can
  take.
- **Every rule that fires is traced**, not only the ones that render a decision.
- **The shipped rule packs work through the surfaces that drive them**, and two
  shipped rules detect what they claim to detect.
- **A hot reload is safe for the request it lands on**, leaves a trace when it is
  refused, and replays the functions it used to drop. The REST server serves the
  mounted Engine so a hot reload reaches the data plane.
- **The chained log refuses a second writer** instead of forging a broken chain,
  and holds its lock on a sidecar file so readers and `fathom verify-chain` keep
  working on Windows. The signing key is kept out of a planted temporary
  directory.
- **`fathom compile` output is loadable**, `fathom info` lists functions, and
  `fathom verify-chain` exits with the right status.
- **An int widens to a float on a float slot**, as the docs already promised.
- **The fleet LISTEN connection is replaced when its backend goes away**, a store
  key no longer shadows a slot, a count no longer outlives its facts, and Studio
  no longer captions a denial as permitted.

## [0.11.0] - 2026-08-26

### Added
- **`fathom convert to-rego` — Fathom to Rego export.** Writes the stateless
  subset of a ruleset out as Rego: rules matching one fact against literals,
  with the action as the document name and the reason as a comment. Literals
  are rendered from the declared slot type, and a `symbol` slot holding
  `true`/`false` goes back to a Rego boolean, so a policy imported with
  `fathom convert rego` exports back to the shape it started in. Rules that
  join across facts, assert facts, or use a temporal or classification
  operator are refused with the reason and left out; repeated reasons are
  grouped rather than printed once per rule. Losses that are not refusals —
  salience, and allow/deny precedence — are reported as notes.
- **OPA-compatible Data API on the REST server.** `POST /v1/data/<path>` (and
  the `GET` form with `input` as a query parameter) answers OPA's decision
  endpoint, so an existing OPA caller works against a converted policy without
  code changes. Leading path segments name the ruleset and the last segment
  names the document: a trailing `allow`/`deny` returns the bare boolean, and
  dropping it returns the whole decision including `reason` and `rule_trace`.
  The `input` document is flattened into slots by the same code the converter
  uses, so the two halves cannot drift. Errors use OPA's `{code, message}`
  envelope. Unlike OPA's, the surface requires the same bearer token as every
  other route.
- **`fathom convert rego` — Rego to Fathom conversion.** Translates the
  stateless subset of an OPA policy (`allow`/`deny` rules comparing `input`
  fields against literals, plus set membership and the string built-ins) into
  a loadable Fathom pack. Parsing is delegated to `opa parse`, not
  reimplemented. Everything outside the subset — negation, `>=`/`<=`,
  reference-against-reference comparisons, `data` lookups, bare truthiness —
  is reported with the rule and the reason instead of approximated, and a rule
  with one unconvertible condition is dropped whole rather than shipped
  matching more broadly than the policy it came from. `--strict` fails the
  command when anything was skipped. `fathom.rego` exposes the same conversion
  as a library (`parse_rego`, `convert_ast`, `convert_file`).
- `Engine(match_evidence=True)` records which facts, with which slot values,
  fired each rule. `EvaluationResult.match_evidence` and
  `AuditRecord.match_evidence` hold one entry per firing, each naming the
  fact behind every condition element on the rule's left-hand side —
  including for assert-only rules that never produce a decision. clipspy
  exposes no accessor for an activation's basis, so the evidence is compiled
  in: the flag is off by default and the generated CLIPS is byte-identical
  to before while it stays off.
- **`schema_frequency_exceeds` temporal operator and the `schema-denoising`
  rule pack.** A relation type extracted from an upstream stream is promoted
  `candidate_schema` -> `stable_schema` only once at least tau facts carry it,
  and only facts under a promoted relation become `aligned_fact`. Downstream
  rules match `aligned_fact`, so one-off extraction noise never reaches them.
  Detection is pure forward chaining — the host asserts and calls `evaluate()`.
  The operator computes the same `count >= threshold` predicate as `last_n`
  and registers under its own CLIPS name so a compiled rule reads back as the
  operator its author wrote.
- **A `$alias.field` value argument on the counting temporal operators**
  (`count_exceeds`, `rate_exceeds`, `last_n`, `schema_frequency_exceeds`).
  The value being counted can now be the one the matched fact carries instead
  of a literal, which is what lets a single promotion rule serve an open set
  of relations rather than one rule per relation. Only a reference to the slot
  the condition already binds is in scope; anything else is refused at compile
  time with the slot named, rather than reaching CLIPS as an unbound variable.
- **`conflict-detection` rule pack.** Reports contradictions between claims as
  `conflict` facts, in three kinds: `mutual_exclusion` (two tails a
  declaration says cannot both hold of one head), `temporal` (two different
  tails for one head and relation, observed inside the same window -- far
  apart the same pair is a legitimate change), and `granularity` (two claims
  that disagree only about how coarse they are). Detection only: no rule
  renders a decision, because what to do about a contradiction is a policy
  question. Each conflict is reported once rather than once per ordering of
  the pair. Detection is forward-chaining and host-evaluated -- a `subscribe`
  listener fires synchronously inside `assert_fact`, which runs no inference,
  so asserting from one would re-enter the fact manager mid-assert.
- **`Engine.load_pack_dir(path)` — load a rule pack from a directory.**
  `RulePackLoader` already had the load ordering and the template-collision
  check, but the only way in was `Engine.load_pack(name)`, which resolves
  through the `fathom.packs` entry-point group; a directory could not reach
  it, so every host holding packs as directories hand-rolled the four
  `load_*` calls in the one order that works, with no warning when the order
  was wrong. Unlike `from_rules`, this loads into an engine that already
  exists, which is what a runtime-uploaded pack needs. Both layouts are
  accepted — the `templates/` `modules/` `functions/` `rules/` convention and
  a flat directory of `*.yaml` keyed by kind. Directory packs now get what
  entry-point packs had: identity by resolved path so a repeat load is a
  no-op, the collision check before anything is built, and an error rather
  than an empty engine when the directory holds nothing recognised.
  `PACK_DEPENDENCIES` stays unsupported for a directory pack — there is no
  module to declare it on.

### Removed

- **The generated Postman collection** (`docs/reference/rest/fathom.postman_collection.json`)
  and the script that produced it. Postman imports OpenAPI natively
  (*Import → OpenAPI*), and `docs/reference/rest/openapi.json` was already
  published beside the collection — the generator existed only to pre-bake
  that import, and most of it was post-processing to beat the converter's
  nondeterminism so the drift gate could pass. The REST docs now point at
  the import instead.
- **The `fathom-editor` scaffold** (`packages/fathom-editor/`). Six React
  component stubs, `private: true`, no tests, no backend wiring, and a CI job
  whose only assertion was that the tree still compiled — while Policy Studio
  shipped a working browser UI over a real engine. Building a visual editor
  remains tracked as
  [#43](https://github.com/KrakenNet/fathom/issues/43); the scaffold is in git
  history if it is ever the right starting point.
- **`MetricsCollector.inc_sessions_active` / `.dec_sessions_active`**, and
  **`fathom.yaml_utils.validate_yaml_file` / `.load_and_validate`** (with
  `YAMLValidationError`, which only they raised). No caller in the package,
  and neither module is a covered surface under
  [VERSIONING.md](VERSIONING.md). `MetricsCollector.set_sessions_active`
  already replaced the inc/dec pair and is what the session store calls.

### Changed

- **`PolicyViolation` is now one class**, defined in `fathom.integrations` and
  re-exported by each adapter. It was declared four times, identically, so
  `except langchain.PolicyViolation` did not catch what the CrewAI adapter
  raised. Every existing import path still works, and importing it no longer
  pulls in any adapter's optional dependency.
  
### Fixed

- **Loading a second rule pack no longer unfocuses the first.**
  `Engine.load_modules` applied each file's declared `focus_order` through
  `Engine.set_focus`, which replaces the focus order rather than extending
  it. CLIPS only drains the agenda of the module holding the focus, so the
  first pack's rules stayed in the registry and silently stopped firing —
  the decision fell through to the engine default with an empty rule trace.
  The same call also skipped its no-`focus_order` fallback whenever any
  focus already existed, leaving a pack that declared modules but no order
  unfocused as soon as it was not the first one loaded. Focus is now
  cumulative across loads; `Engine.set_focus` keeps its documented
  replace-everything semantics.
- **`not_equals`, `in` and `not_in` now quote their literals for a slot
  declared `string`.** Only `equals` did. CLIPS holds a symbol and a string
  to be unequal, so on a string slot `not_equals(admin)` was always true
  and `in([admin, root])` never matched — both without any diagnostic,
  because they compile into `:(...)` predicates CLIPS does not type-check.
  `not_in` emitted an unquoted `~` constraint, which at least failed the
  build with `[CSTRNCHK1]`. No shipped rule pack uses a string slot with
  these operators.
- **Cross-fact references (`equals($alias.field)`) now compile to a real
  join.** The reference emitted `?alias-field` in the pattern that used it,
  but nothing bound that variable on the pattern the alias named — so CLIPS
  bound it there instead, the constraint did nothing, and the rule matched
  the cartesian product of its patterns. Silent: no error, no warning, the
  rule fired on facts the author never joined. The shipped Bell-LaPadula
  example denied a legal read by matching a resource and a subject the
  request never named. A reference to an alias no pattern declares is now a
  `CompilationError` instead of failing open the same way.
- **`bind:` plus a predicate operator now produces a rule CLIPS will load.**
  With `not_equals`, `greater_than`, `less_than`, `contains` or `matches`,
  the bind was chained in front of the generated constraint variable —
  `(level ?lvl&?s_0_level&:(neq ?s_0_level public))` — which CLIPS rejects
  with `[ANALYSIS4] Variable ?s_0_level was referenced in CE #1 slot 'level'
  before being defined`, because only the leading variable of a conjunctive
  slot constraint binds. The bind now takes over the generated variable.

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
