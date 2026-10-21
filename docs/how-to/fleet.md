---
title: Running a fleet over a shared fact store
summary: Share fleet-scoped facts across sessions and processes with FleetEngine over the in-memory, Redis or Postgres store; sessions, assert/query/sync, close, and the retraction limitation.
audience: [app-developers]
diataxis: how-to
status: stable
last_verified: 2026-10-21
sources:
  - src/fathom/fleet.py
  - src/fathom/fleet_redis.py
  - src/fathom/fleet_pg.py
  - src/fathom/errors.py
  - pyproject.toml
---

# Running a fleet over a shared fact store

A `FleetEngine` holds one `Engine` per session, all loaded from the same
rules directory, and a `FactStore` they share. Facts of a template marked
`scope: fleet` are written to the store; every other fact stays in the
session that asserted it. A session pulls the fleet's facts into its own
working memory with `sync_fleet_facts`.

Three stores implement the `FactStore` protocol:

| Store | Import | Install | Shared across processes |
|---|---|---|---|
| `InMemoryFactStore` | `fathom` | included | no |
| `RedisFactStore` | `fathom.fleet_redis` | `pip install fathom-rules[fleet]` | yes |
| `PostgresFactStore` | `fathom.fleet_pg` | `pip install fathom-rules[fleet-pg]` | yes |

## Mark a template fleet-scoped

`scope` is a template field; it defaults to `session`.

```yaml
templates:
  - name: lock
    scope: fleet
    slots:
      - name: resource
        type: string
        required: true
      - name: holder
        type: string
  - name: request
    slots:
      - name: agent
        type: string
```

A fleet-scoped template may not declare a slot named `fact_id` (the store's
row key), and a rule may not `assert` into one: that is a `CompilationError`
at load.

## Run a fleet in memory

`InMemoryFactStore` needs no setup and has no `connect()` or `close()`. It
lives in one process, so it suits tests and single-process fleets. This
example writes the template above to a temporary rules directory:

```python
import asyncio
import pathlib
import tempfile

from fathom import FleetEngine, InMemoryFactStore

rules = pathlib.Path(tempfile.mkdtemp())
(rules / "templates").mkdir()
(rules / "templates" / "fleet.yaml").write_text(
    """
templates:
  - name: lock
    scope: fleet
    slots:
      - name: resource
        type: string
        required: true
      - name: holder
        type: string
  - name: request
    slots:
      - name: agent
        type: string
"""
)


async def main() -> None:
    fleet = FleetEngine(fact_store=InMemoryFactStore(), rules_path=str(rules))
    fleet.create_session("agent-a")
    b = fleet.create_session("agent-b")

    # Fleet scope: written to agent-a and the store; returns the store's fact_id.
    fact_id = await fleet.assert_fact("agent-a", "lock", {"resource": "db"})
    assert fact_id is not None
    # Session scope: stays in agent-a; returns None.
    assert await fleet.assert_fact("agent-a", "request", {"agent": "a"}) is None

    # The store holds the fact as the engine accepted it, defaults applied.
    rows = await fleet.query("lock", {"resource": "db"})
    assert rows == [{"fact_id": fact_id, "resource": "db", "holder": ""}]

    # agent-b sees it only after a sync.
    assert b.query("lock") == []
    await fleet.sync_fleet_facts("agent-b")
    assert b.query("lock") == [{"resource": "db", "holder": ""}]


asyncio.run(main())
```

`FleetEngine(fact_store, rules_path, **engine_kwargs)` passes
`engine_kwargs` to `Engine.from_rules` for every session.

## Run a fleet on Redis

`RedisFactStore` connects lazily on first use, so there is no `connect()`.
Call `close()` when done; it also cancels any subscription listeners.

```python no-verify
import asyncio

from fathom import FleetEngine
from fathom.fleet_redis import RedisFactStore


async def main() -> None:
    store = RedisFactStore(host="localhost", port=6379, ttl=3600)
    try:
        fleet = FleetEngine(fact_store=store, rules_path="rules/")
        fleet.create_session("agent-a")
        await fleet.assert_fact("agent-a", "lock", {"resource": "db"})
        print(await fleet.query("lock"))
    finally:
        await store.close()


asyncio.run(main())
```

The constructor also takes `db`, `password` and `ssl`. With `ttl`, each fact
expires after that many seconds; an expired fact drops out of `query` and
`count` but sends no `retract` notification. Connection errors and timeouts
are retried (3 attempts) before `FleetConnectionError`; other Redis errors
raise `FleetError` at once.

## Run a fleet on Postgres

`PostgresFactStore` must be connected first: `await store.connect()` creates
the connection pool and the `fleet_facts` table. Using the store before
`connect()` raises `FleetError`.

```python no-verify
import asyncio

from fathom import FleetEngine
from fathom.fleet_pg import PostgresFactStore


async def main() -> None:
    store = PostgresFactStore("postgresql://fathom:fathom@localhost:5432/fathom")
    await store.connect()
    try:
        fleet = FleetEngine(fact_store=store, rules_path="rules/")
        fleet.create_session("agent-a")
        await fleet.assert_fact("agent-a", "lock", {"resource": "db"})
        print(await fleet.query("lock"))
    finally:
        await store.close()


asyncio.run(main())
```

Postgres caps a NOTIFY payload at 8000 bytes, and each write sends the fact
as JSON in one. A fact larger than that fails `assert_fact` with
`FleetError` and nothing is stored. Errors are not retried: an unreachable
server or a connection lost mid-statement raises `FleetConnectionError`, any
other driver error `FleetError`.

## Manage sessions

Every method that addresses a session takes its id and raises `KeyError` for
an id with no session.

| Call | Does | Raises |
|---|---|---|
| `create_session(id)` | Loads a new `Engine` and returns it | `FleetError` if `id` already has a session |
| `replace_session(id)` | Discards the session's engine, returns a fresh one with empty working memory | `KeyError` if unknown |
| `remove_session(id)` | Forgets the session | `KeyError` if unknown |
| `sessions` | A copy of the `{id: Engine}` mapping | — |

## Assert, query and sync

- `await fleet.assert_fact(id, template, data)` validates the fact in the
  session first, so a fact the engine rejects never reaches the store. A
  fleet-scoped fact is then written to the store, and its `fact_id` returned.
  If the store write fails, the local assert is rolled back and the error
  re-raised. Asserting into a fleet-scoped template directly on the `Engine`
  raises `ScopeError`; go through `FleetEngine.assert_fact`.
- `await fleet.query(template, fact_filter=None)` reads the store, not a
  session. Each row carries its `fact_id`. A filter naming a slot the
  template does not declare raises `ValidationError`.
- `await fleet.sync_fleet_facts(id)` queries the store for every fleet-scoped
  template and asserts the rows into the session. A row the session rejects
  is logged and skipped.

## Fleet retraction does not propagate

`FleetEngine` has no `retract`, never subscribes to the store, and
`sync_fleet_facts` only ever asserts. A fact removed from the store (with
`store.retract(...)`, or by Redis TTL expiry) stays in every session that
already synced it, and a local `Engine.retract` of a fleet-scoped template
raises `ScopeError`. To drop removed facts from a session, rebuild it and
sync again:

```python
async def drop_retracted() -> None:
    store = InMemoryFactStore()
    fleet = FleetEngine(fact_store=store, rules_path=str(rules))
    s = fleet.create_session("agent-a")
    await fleet.assert_fact("agent-a", "lock", {"resource": "db"})

    assert await store.retract("lock", {"resource": "db"}) == 1
    assert s.query("lock") == [{"resource": "db", "holder": ""}]  # still there

    s = fleet.replace_session("agent-a")
    await fleet.sync_fleet_facts("agent-a")
    assert s.query("lock") == []


asyncio.run(drop_retracted())
```

## Subscribe to store changes

A store's `subscribe(template, callback)` calls `await callback(notification)`
with a `FactChangeNotification` (`template`, `fact_id`, `action` of `assert`
or `retract`, `data`) and returns an unsubscribe callable. `FleetEngine` does
not use it; it is for your own code.

| | In-memory | Redis | Postgres |
|---|---|---|---|
| Delivered | synchronously, inside `assert_fact` / `retract` | after the write, from a listener task reading the stream | after commit, through `LISTEN` |
| History | none | none; every change after `subscribe()` returns | none; every change after `subscribe()` returns |
| Gaps | — | — | changes during a `LISTEN` reconnect are lost |

On all three, a fact and its notification are written together or not at
all, concurrent retracts of one fact count and announce it once, and a callback that raises is logged on the `fathom.fleet` logger and
skipped: it never fails the write, ends the subscription or reaches the
other subscribers.

## Reference

- [`FleetEngine`](../reference/python-sdk/fleetengine.md)
- [`InMemoryFactStore`](../reference/python-sdk/inmemoryfactstore.md)
- [`RedisFactStore`](../reference/python-sdk/redisfactstore.md)
- [`PostgresFactStore`](../reference/python-sdk/postgresfactstore.md)
- [`FleetError`](../reference/python-sdk/fleeterror.md) and its subclass
  [`FleetConnectionError`](../reference/python-sdk/fleetconnectionerror.md)
