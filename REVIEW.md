# Code Review — `fix/phase-2-review`

**Reviewed**: branch `fix/phase-2-review` (71 commits ahead of `master`, subsequently merged as PR #2 → `0ba61b7`).
**Canonical spec**: `specs/rule-assertions/` (accessed via `git show HEAD:...`; directory is intentionally removed from the working tree after merge) plus `specs/phase-2/tasks.md` for REST round-trip.
**Verdict**: **HOLD** — feature work (AssertSpec / bind / register_function / audit capture / auth / path-jailing) is solid and spec-compliant. Two **major** bugs land on top, both introduced by the last commit `28b4286 "Update to stuff."`. Fix the version skew and the proto/go.mod path mismatch before release.

---

## Evidence

- Full pytest: **1361 passed, 1 skipped** at HEAD (`28b4286`); 2 uncommitted-tree failures explained below. Log at `/tmp/fathom-review/pytest.log`.
- Phase-2 REST round-trip + `TestAssertAction`: **8/8 passed**.
- TypeScript vitest: **19/19 passed**.
- Live smoke on `uv run uvicorn fathom.integrations.rest:app`:
  - auth: `401` without / with wrong token; `200` with correct token.
  - path-jail: `200` for `01-hello-allow-deny`; `400` with clear error for `../etc/passwd`, `/absolute/path`, `../../../etc/passwd`.
  - `/v1/compile` with `then.assert` + `bind`: returned the expected CLIPS defrule (`(trigger (id ?sid))` on LHS, `(assert (routing_decision (source_id ?sid) (reason "match")))` on RHS), `errors: []`.
- CLI: `uv run fathom --version` → `fathom 0.3.0`; `validate` and `info` against `examples/01-hello-allow-deny/` succeed.

---

## Spec coverage — rule-assertions (68 tasks, 35 ACs)

| AC | What it requires | Verified by | Status |
|----|------------------|-------------|--------|
| AC-1.1..1.5 | `then.assert` compiles to `(assert ...)` RHS; skips `__fathom_decision` when action absent; ordering guarantee; no-action-no-assert rejected; queryable facts | `tests/test_compiler_rules.py::TestCompileAssertAction` (9 tests); `tests/test_integration.py::TestAssertAction::test_single_rule_single_assert_queryable` | **PASS** |
| AC-2.1..2.5 | `ConditionEntry.bind` emits `?var`; `?`-prefix validator; bind+expression coexistence; LHS bind → RHS assert flow; byte-identical backward compat | `tests/test_models.py::TestConditionEntry`; `tests/test_compiler_rules.py::TestCompileBind`; `TestAssertAction::test_bind_flows_to_assert_slot_value` | **PASS** |
| AC-3.1..3.5 | `Engine.register_function(name, fn)` public; rejects empty / whitespace / `fathom-` prefix; re-registration overwrites; type-hinted signature | `tests/test_sdk.py::TestRegisterFunction`; `TestAssertAction::test_register_function_end_to_end`; impl at `src/fathom/engine.py:653-694` | **PASS** |
| AC-4.1..4.3 | Existing rule-pack + compiler tests pass unchanged | `uv run pytest tests/test_{nist,owasp,hipaa,cmmc}_pack.py tests/test_compiler_rules.py` → all green | **PASS** |
| AC-5.1..5.3 | REST `/v1/compile` round-trips `assert` + `bind`; invalid payload returns `errors` | `tests/phase_2/test_compile_endpoint.py` (3 tests) + live smoke above | **PASS** |
| AC-6.1..6.3 | `from fathom import AssertSpec` works; default slots `{}`; `ThenBlock(asserts=[...])` without action validates | `tests/test_sdk.py::TestPublicSurface`; `src/fathom/__init__.py:5-18` exports `AssertSpec` and `AssertedFact` | **PASS** |
| NFR-1..NFR-8 | Zero edits to pre-spec tests; 0 added Rete work; mypy strict; ruff clean; docstrings | `tests/test_sdk.py::TestPackageMeta`; `uv run mypy src/` clean; VE2 gate record in `specs/rule-assertions/.progress.md:192` | **PASS** |

**All 35 rule-assertions ACs are implemented and verified.** The feature work is well-tested, well-documented, and lands exactly what the spec asked for.

---

## Bugs found

### Major

**M1. Version skew between `pyproject.toml` (0.2.1) and `__init__.py.__version__` (0.2.0).**
`28b4286` bumped `pyproject.toml:3` to `"0.2.1"` but left `src/fathom/__init__.py:7` at `"0.2.0"`. Building a wheel at HEAD produces `fathom_rules-0.2.1-py3-none-any.whl` whose `import fathom; fathom.__version__` returns `"0.2.0"` — a runtime/metadata mismatch that breaks any consumer doing version gating. `tests/test_sdk.py::test_version_format` hardcodes `"0.2.0"` so the asymmetry is invisible to CI. The `specs/rule-assertions/.progress.md:115` "Task 3.12" note explicitly calls out this exact class of mismatch as "pre-existing … resolved — both files agree on 0.2.0"; `28b4286` silently re-introduces it.
- Fix: either revert the pyproject bump, or bump `__init__.py` to `0.2.1` *and* update both test assertions (`tests/test_sdk.py:59`, `:527`). The working tree already has a candidate fix that moves both to 0.3.0 + a new CHANGELOG entry; that fix just needs the two `test_sdk.py` literals updated to ship cleanly.

**M2. `protos/fathom.proto:12` `go_package` points at a different repo than `packages/fathom-go/go.mod:1`.**
Proto declares `go_package = "github.com/KrakenNet/fathom/gen/go/fathom/v1"` (a path inside the main `fathom` repo). The Go module declares `module github.com/KrakenNet/fathom-go` (a standalone `fathom-go` repo). `protoc --go_out=.` generated alongside `packages/fathom-go/` will emit `package gen/go/fathom/v1` imports that don't resolve against `github.com/KrakenNet/fathom-go/...`. This will break the first real attempt to regenerate + build the Go SDK.
- Fix: either change proto `go_package` to `github.com/KrakenNet/fathom-go/proto` (matches the SDK module) or move the Go SDK under the main repo at `fathom/gen/go/fathom/v1`. The `specs/phase-2/design.md` hunk in the same commit (lines around 620) picks the former shape but the proto itself still uses the latter — pick one and make the two files agree.

### Minor

**m3. Silent slot-drop in `ConditionEntry(slot=..., test=...)` (no expression, no bind).**
`src/fathom/compiler.py:213-215` fast-paths test-only conditions with `if not cond.expression and not cond.bind and cond.test is not None: test_ces.append(...); continue`. The `continue` skips slot processing, so `ConditionEntry(slot="id", test="(foo)")` compiles to `(agent) (test (foo))` — the `id` slot constraint is silently discarded. The model validator at `src/fathom/models.py:94-101` only enforces "`slot` required when `expression` or `bind` is set", so the construction validates. No existing test covers this combination.
- Fix (pick one): (a) make the compiler also emit the slot constraint when `slot` is non-empty alongside `test`, (b) tighten the model_validator to reject a non-empty `slot` when only `test` is set, or (c) at minimum add a regression test documenting the current behavior.

**m4. No CHANGELOG entry for version 0.2.1.**
`CHANGELOG.md` jumps from 0.2.0 straight to the (uncommitted) 0.3.0 entry. The shipped 0.2.1 bump in `pyproject.toml` is undocumented.
- Fix: either roll the 0.2.1 bump into the 0.3.0 release (simplest — the uncommitted working tree is already doing this) or backfill a 0.2.1 CHANGELOG entry naming the `ConditionEntry.test` feature.

**m5. `mkdocs.yml` rename is half-done.**
`mkdocs.yml:4` has `repo_url: https://github.com/KrakenNet/fathom` but `mkdocs.yml:5` still has `repo_name: kraken-networks/fathom`. Material renders `repo_name` as the clickable label next to the repo icon, so the site will show the old org name.
- Fix: change line 5 to `repo_name: KrakenNet/fathom`.

**m6. No E2E coverage for `ConditionEntry.test`.**
Unit tests (`tests/test_models.py::TestConditionEntry`, `tests/test_compiler_rules.py::TestCompileBind::test_test_standalone_emits_only_test_ce`, `test_test_combined_with_bind_emits_both`) cover the model and compiler paths, but there is no YAML-loaded-engine integration test equivalent to `TestAssertAction::test_register_function_end_to_end` that exercises `test:` through the full evaluate pipeline. The REST round-trip test suite also doesn't cover it.
- Fix: add one `TestAssertAction::test_test_field_round_trip_through_engine` that loads YAML using `test: "(my-fn)"` + a registered function, evaluates, and confirms rule fires.

### Nit

**n7. Commit message `28b4286 "Update to stuff."`** — 19 files, 1275 insertions, 1759 deletions, zero explanation. Bundles a new feature (`ConditionEntry.test`), a full org rename, a version bump, a frontend toolchain swap (npm → pnpm, React 18 → 19, Vite 5 → 7), and several spec doc tweaks. Any one of these deserves its own commit; grouped, they're nearly impossible to bisect. If this is still rebasable, splitting it would make M1, M2, m3, m5 each a much shorter PR review.

**n8. Scope creep.** `ConditionEntry.test` is explicitly listed in `specs/rule-assertions/requirements.md:160` under **Out of Scope**: "New LHS condition operators beyond the existing `slot`/`expression`/`bind` trio". The feature itself is useful and well-implemented; the process issue is that it rode in under the rule-assertions spec without a design-phase revision or a new mini-spec. Not a blocker; flag so future reviews catch this earlier.

---

## Deferred items — reality check

| Item | Claim | Reality | OK? |
|------|-------|---------|-----|
| Task 5.2 (CI) | `.progress.md:201` marks "no CI configured — n/a" | Confirmed: no `.github/workflows/`, `gh pr checks 2` returns no checks. Every "quality gate passed" claim therefore rests on `uv run pytest` having been run locally — I re-ran it; still green. | **OK** |
| Task 5.3 (Nautilus smoke) | `.progress.md:211` defers with runbook referencing `dist/fathom_rules-0.2.0-py3-none-any.whl` | Wheel exists at that path. Nautilus has no `core-broker/` or `test_core_broker.py` — confirmed via `ls` + `grep`. Deferral is legitimate. Note: if the version-skew fix (M1) lands as 0.3.0, update the runbook to reference the new wheel. | **OK** (with note) |
| `FastAPI(version="0.1.0")` in `src/fathom/integrations/rest.py:132` | n/a — never specced | Self-declared API version string is stale. Low-impact (OpenAPI metadata only), worth fixing when touching M1. | minor |

---

## `28b4286` commit classification

Of 19 files in the commit:

- **Legitimate**: the `ConditionEntry.test` feature implementation (`src/fathom/models.py:55-101`, `src/fathom/compiler.py:213-227`) and its unit tests (`tests/test_models.py`, `tests/test_compiler_rules.py`). Code is clean, validator is sensible, tests exercise 4 of the 6 interaction shapes.
- **Routine**: the `kraken-networks → KrakenNet` rename across `README.md`, `docs/integrations/go-sdk.md`, `pyproject.toml`, `packages/fathom-go/go.mod`, `packages/fathom-ts/package.json`, plus the 4 `specs/phase-2/*.md` URL tweaks.
- **Broken**: M1 (version skew), M2 (proto ↔ go.mod mismatch), m5 (`mkdocs.yml` half-rename).
- **Out-of-spec but defensible**: the React 18 → 19 / Vite 5 → 7 / npm → pnpm swap for `packages/fathom-editor/`. The editor is a stub with no tests and no production dependency yet, so the blast radius is small; still, a "major framework bump" commit shouldn't share a SHA with a feature and a rename.

---

## What was NOT reviewed

- **Go SDK**: no `*_test.go` files on this branch, nothing to run. Acceptance criteria AC-32.x (gRPC Go client) rely on regeneration that was never executed; flagged by M2 above.
- **TypeScript `@hey-api/openapi-ts` generation script** (`packages/fathom-ts/scripts/generate.sh`): not executed. Only the hand-written `FathomClient` + error hierarchy were verified.
- **Prometheus metrics** (`src/fathom/metrics.py`) and the editor React components (`RuleTree`, `ConditionBuilder`, `TestRunner`, etc.): exist but fall entirely outside the `rule-assertions` spec and were not traced against any AC.
- **gRPC runtime smoke**: the test suite covers auth and basic RPCs (`tests/test_grpc_auth.py`, 5 tests passing); I did not start a live gRPC server.

---

## Recommendations

1. Block the release until M1 and M2 are fixed. Both are single-line changes.
2. Land m3 as either a compiler fix or at minimum a regression test before anyone writes `test:` in real YAML.
3. If `28b4286` is still rebasable on `master`, split it: `feat(compiler): ConditionEntry.test raw-CLIPS escape`, `chore: rename GitHub org to KrakenNet`, `chore(editor): upgrade React/Vite and switch to pnpm`. Three review-sized PRs instead of one opaque 1275-line catchall.
4. Add a pre-commit hook or a single test that asserts `fathom.__version__ == re.search(r'^version\s*=\s*"(.+?)"', Path("pyproject.toml").read_text(), re.M).group(1)` so the next skew gets caught immediately.
