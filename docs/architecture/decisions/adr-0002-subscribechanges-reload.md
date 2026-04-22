# ADR-0002: Defer `SubscribeChanges` Mid-Stream Reload Behaviour

- **Date:** 2026-04-22
- **Status:** Accepted
- **Traces to:** fathom-update-1 design OQ #2
- **Related tasks:** T-2.4 (reload_rules atomic-swap, b0de100)

## Context

`Engine.reload_rules()` performs an atomic pointer swap of `self._env`
under `self._reload_lock` (T-2.4). The gRPC `SubscribeChanges` RPC is
declared in the proto but the server-side implementation is currently a
stub — no long-lived streams exist today. Behaviour of in-flight streams
at the moment of an env swap is therefore unobserved.

## Decision

Defer mid-stream reload semantics to the next gRPC iteration. No code
change in this spec.

## Options to evaluate when implemented

- (a) Cancel active `SubscribeChanges` streams on swap; clients reconnect.
- (b) Let active streams drain on the old env; new subs bind to new env.

## Consequences

No behaviour change in fathom-update-1. Picker must confirm reload
semantics before `SubscribeChanges` leaves stub status.
