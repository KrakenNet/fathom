# ADR-0002: Defer `SubscribeChanges` Mid-Stream Reload Behaviour

- **Date:** 2026-04-22
- **Status:** Resolved (2026-06-05) — option (a) cancel-on-swap
- **Traces to:** fathom-update-1 design OQ #2
- **Related tasks:** T-2.4 (reload_rules atomic-swap, b0de100), issue #14

## Context

`Engine.reload_rules()` performs an atomic pointer swap of `self._env`
under `self._reload_lock` (T-2.4). At the time of writing the gRPC
`SubscribeChanges` RPC was declared in the proto but the server-side
implementation was a stub — no long-lived streams existed. Behaviour of
in-flight streams at the moment of an env swap was therefore unobserved.

*Update 2026-06-05:* `SubscribeChanges` has since shipped
(`src/fathom/integrations/grpc_server.py`) with queue-based
backpressure, listener subscription via `Engine.subscribe()`, and gRPC
cancellation handling — the "stub" premise no longer holds, forcing the
deferred decision below.

## Decision

~~Defer mid-stream reload semantics to the next gRPC iteration. No code
change in this spec.~~

**Resolved 2026-06-05 — option (a): cancel on swap.** A successful
`Engine.reload_rules()` swap terminates every in-flight
`SubscribeChanges` stream with status `ABORTED` and details
`"ruleset_reloaded: re-subscribe to bind to the new ruleset"`. Clients
reconnect and re-`Query` to re-synchronize.

Mechanism: `Engine.subscribe_reload(callback)` is a new listener seam
fired (outside the reload lock) after each successful swap. The
`SubscribeChanges` generator registers a per-stream reload listener
that flags the stream and wakes its event queue; the consumer loop then
aborts the gRPC context. This covers reloads triggered by the `Reload`
RPC, the REST endpoint, and direct in-process `reload_rules()` calls.

## Options evaluated

- **(a) Cancel active `SubscribeChanges` streams on swap; clients
  reconnect.** ✅ Chosen — deterministic, no stale-ruleset window, and
  streams are indefinite so "drain" has no natural endpoint.
- (b) Let active streams drain on the old env; new subs bind to new
  env. Rejected: fact-change listeners live in `FactManager`, which
  survives the swap, so an "old" stream would silently start observing
  new-env events anyway — the old/new distinction is not enforceable
  without holding the retired env alive indefinitely.

## Consequences

Subscribers must treat `ABORTED` / `ruleset_reloaded` as a normal
lifecycle event: re-subscribe, then `Query` to re-synchronize.
Behaviour is exercised by
`tests/integrations/test_grpc_subscribe.py::test_subscribe_cancelled_on_reload`
and the `subscribe_reload` unit tests in `tests/test_engine_reload.py`.
