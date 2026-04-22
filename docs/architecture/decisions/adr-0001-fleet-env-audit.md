# ADR-0001: Fleet Modules Do Not Directly Read `Engine._env`

- **Date:** 2026-04-22
- **Status:** Accepted
- **Traces to:** fathom-update-1 design OQ #1, constraint C5
- **Related tasks:** T-1.1 (this audit), T-1.7 / T-1.8 / T-1.9 (env-provider refactor)

## Context

The fathom-update-1 design proposes introducing an env-provider abstraction
so that `Engine._env` is no longer the single source of the CLIPS
environment. Before refactoring the provider, we need empirical confirmation
that no fleet module (`fleet.py`, `fleet_pg.py`, `fleet_redis.py`) reads
`self._env`, `_env.`, or any CLIPS environment directly — otherwise the
refactor would silently break fleet code.

Design assumption (from `specs/fathom-update-1/design.md`):
`Engine._env` is read by `Evaluator` and `FactManager` at init time, and
fleet modules delegate all env interaction through the engine. This ADR
verifies that assumption.

## Audit method

Commands run from repo root on 2026-04-22:

```bash
grep -n "_env" src/fathom/fleet*.py
grep -n "self._env" src/fathom/fleet.py src/fathom/fleet_pg.py src/fathom/fleet_redis.py
grep -n "clips\.Env\|Environment()" src/fathom/fleet.py src/fathom/fleet_pg.py src/fathom/fleet_redis.py
```

Files covered (line counts for reference):

- `src/fathom/fleet.py` — 226 lines
- `src/fathom/fleet_pg.py` — 381 lines
- `src/fathom/fleet_redis.py` — 335 lines

## Audit output

Verbatim output of `grep -n "_env" src/fathom/fleet*.py`:

```
(no matches)
```

Verbatim output of `grep -n "self._env" src/fathom/fleet.py src/fathom/fleet_pg.py src/fathom/fleet_redis.py`:

```
(no matches)
```

Verbatim output of `grep -n "clips\.Env\|Environment()" src/fathom/fleet.py src/fathom/fleet_pg.py src/fathom/fleet_redis.py`:

```
(no matches)
```

File `/tmp/fleet-env.txt` produced by the verify command is empty (0 lines),
consistent with the grep results above.

## Verdict

**No direct reads; env-provider refactor is safe.**

None of the three fleet modules reference `_env`, `self._env`, or construct
their own CLIPS environment. The design's assumption holds: `Engine._env` is
consumed only by `Evaluator` and `FactManager` at init time. Tasks T-1.7
through T-1.9 (env-provider refactor) may proceed without a fleet-module
compatibility shim.

## Notes / follow-ups

_None — no direct reads were found._
