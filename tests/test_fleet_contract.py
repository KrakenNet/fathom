"""One FactStore contract, run against every backend.

In-memory runs everywhere; Redis and Postgres reuse the session containers from
:mod:`tests.test_fleet_integration` and skip without Docker. A behaviour that
holds on one store and not another is a bug in the odd one out, so every
contract test here runs on all three.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from fathom.fleet import FleetEngine, InMemoryFactStore
from tests.test_fleet_integration import (  # noqa: F401 -- session container fixtures
    postgres_dsn,
    redis_port,
    requires_docker,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from fathom.fleet import FactStore
    from fathom.models import FactChangeNotification

# 60 characters: over Postgres' 63-byte identifier limit once prefixed.
LONG_TEMPLATE = "t" * 60


@pytest.fixture(
    params=[
        "memory",
        pytest.param("redis", marks=[pytest.mark.integration, requires_docker]),
        pytest.param("postgres", marks=[pytest.mark.integration, requires_docker]),
    ]
)
def backend(request: pytest.FixtureRequest) -> tuple[str, Any]:
    # Resolve the containers here, outside any event loop: their readiness
    # probes call asyncio.run().
    fixture = {"redis": "redis_port", "postgres": "postgres_dsn"}.get(request.param)
    return request.param, fixture and request.getfixturevalue(fixture)


@pytest_asyncio.fixture
async def store(backend: tuple[str, Any]) -> AsyncIterator[Any]:
    kind, address = backend
    if kind == "memory":
        yield InMemoryFactStore()
        return
    if kind == "redis":
        from fathom.fleet_redis import RedisFactStore

        r = RedisFactStore(host="127.0.0.1", port=address, db=11)
        await r._client.flushdb()
        try:
            yield r
        finally:
            await r._client.flushdb()
            await r.close()
        return
    from fathom.fleet_pg import PostgresFactStore

    p = PostgresFactStore(address)
    await p.connect()
    assert p._pool is not None
    async with p._pool.acquire() as conn:
        await conn.execute("TRUNCATE fleet_facts")
    try:
        yield p
    finally:
        await p.close()


async def _eventually(check: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not check():
        if asyncio.get_running_loop().time() > deadline:
            return
        await asyncio.sleep(0.05)


async def _subscribe(store: FactStore, template: str, cb: Any) -> Callable[[], None]:
    unsubscribe = await store.subscribe(template, cb)
    # The Redis listener reads from "$" once its task first runs.
    await asyncio.sleep(0.2)
    return unsubscribe


@pytest.mark.asyncio
async def test_each_change_is_delivered_exactly_once(store: FactStore) -> None:
    seen: list[tuple[str, str]] = []

    async def on_change(n: FactChangeNotification) -> None:
        seen.append((n.action, n.fact_id))

    await _subscribe(store, "agent", on_change)
    fid = await store.assert_fact("agent", {"id": "a1"})
    assert await store.retract("agent") == 1

    await _eventually(lambda: len(seen) >= 2)
    await asyncio.sleep(0.3)  # room for a duplicate to show up
    assert seen == [("assert", fid), ("retract", fid)]


@pytest.mark.asyncio
async def test_raising_subscriber_neither_fails_the_write_nor_dies(store: FactStore) -> None:
    good: list[str] = []

    async def flaky(n: FactChangeNotification) -> None:
        good.append(n.data["id"] if n.data else "")
        if len(good) == 1:
            raise RuntimeError("subscriber boom")

    await _subscribe(store, "agent", flaky)
    for i in range(3):
        await store.assert_fact("agent", {"id": f"w{i}"})

    await _eventually(lambda: len(good) >= 3)
    assert good == ["w0", "w1", "w2"]
    assert await store.count("agent") == 3


@pytest.mark.asyncio
async def test_long_template_name(store: FactStore) -> None:
    seen: list[str] = []

    async def on_change(n: FactChangeNotification) -> None:
        seen.append(n.template)

    await _subscribe(store, LONG_TEMPLATE, on_change)
    await store.assert_fact(LONG_TEMPLATE, {"id": "a1"})

    await _eventually(lambda: bool(seen))
    assert seen == [LONG_TEMPLATE]
    assert await store.count(LONG_TEMPLATE) == 1


@pytest.mark.asyncio
async def test_concurrent_retracts_count_each_fact_once(store: FactStore) -> None:
    seen: list[str] = []

    async def on_change(n: FactChangeNotification) -> None:
        if n.action == "retract":
            seen.append(n.fact_id)

    await _subscribe(store, "agent", on_change)
    for i in range(20):
        await store.assert_fact("agent", {"id": f"a{i}"})

    counts = await asyncio.gather(*(store.retract("agent") for _ in range(4)))

    assert sum(counts) == 20
    await _eventually(lambda: len(seen) >= 20)
    await asyncio.sleep(0.3)
    assert len(seen) == 20


@pytest.mark.asyncio
async def test_fleet_engine_stores_clips_implicit_defaults(
    store: FactStore, tmp_path: Path
) -> None:
    """A slot with no declared default is stored with the value CLIPS fills in."""
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "templates.yaml").write_text(
        "templates:\n"
        "  - name: beat\n"
        "    scope: fleet\n"
        "    slots:\n"
        "      - {name: agent, type: string, required: true}\n"
        "      - {name: note, type: string}\n"
    )
    fleet = FleetEngine(store, str(rules))
    a = fleet.create_session("a")
    await fleet.assert_fact("a", "beat", {"agent": "a1"})

    assert len(a.query("beat", {"note": ""})) == 1
    assert len(await fleet.query("beat", {"note": ""})) == 1
