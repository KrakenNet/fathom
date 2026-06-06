# Changelog

All notable changes to `fathom-rules` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
