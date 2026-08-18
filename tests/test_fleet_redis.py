"""Integration tests for RedisFactStore against a real Redis server."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from fathom.fleet_redis import RedisFactStore
from tests.test_fleet_integration import (
    REDIS_IMAGE,
    exec_ok,
    requires_docker,
    running_container,
    wait_until,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from fathom.models import FactChangeNotification

pytestmark = [pytest.mark.integration, requires_docker]


@pytest.fixture(scope="module")
def redis_port() -> Iterator[int]:
    """Start a Redis container for this module and yield its host port."""
    with running_container(REDIS_IMAGE, 6379) as (container_id, host_port):
        wait_until(lambda: exec_ok(container_id, "redis-cli", "ping"))
        yield host_port

# Round-trip cases the pre-0.8 asymmetric encoding corrupted: a str that
# parses as JSON came back as int/bool/None/dict.
ROUND_TRIP_DATA: dict[str, Any] = {
    "id": "123",
    "active": "true",
    "note": "null",
    "payload": '{"a": 1}',
    "name": "alice",
    "attempts": 3,
    "score": 1.5,
    "enabled": True,
    "missing": None,
}


async def _fresh_store(port: int, db: int) -> RedisFactStore:
    store = RedisFactStore(host="127.0.0.1", port=port, db=db)
    await store._client.flushdb()
    return store


@pytest_asyncio.fixture
async def store(redis_port: int) -> AsyncIterator[RedisFactStore]:
    """A RedisFactStore pointed at an empty database."""
    s = await _fresh_store(redis_port, db=10)
    try:
        yield s
    finally:
        await s._client.flushdb()
        await s.close()


class TestRedisRoundTrip:
    """query() must return exactly what assert_fact() was given."""

    @pytest.mark.asyncio
    async def test_query_returns_written_values_unchanged(
        self, store: RedisFactStore
    ) -> None:
        fact_id = await store.assert_fact("agent", ROUND_TRIP_DATA)
        results = await store.query("agent")

        assert len(results) == 1
        assert results[0] == {"fact_id": fact_id, **ROUND_TRIP_DATA}
        for key, value in ROUND_TRIP_DATA.items():
            assert type(results[0][key]) is type(value), key

    @pytest.mark.asyncio
    async def test_filter_matches_the_string_that_was_written(
        self, store: RedisFactStore
    ) -> None:
        await store.assert_fact("agent", {"id": "123", "name": "alice"})

        assert await store.count("agent", {"id": "123"}) == 1
        assert await store.count("agent", {"id": 123}) == 0
        matched = await store.query("agent", {"id": "123"})
        assert len(matched) == 1
        assert matched[0]["name"] == "alice"

    @pytest.mark.asyncio
    async def test_legacy_unencoded_string_still_decodes(
        self, store: RedisFactStore
    ) -> None:
        """Hashes written by a pre-0.8 release stored plain strings raw."""
        fact_id = "legacydeadbeef"
        await store._client.hset(  # type: ignore[misc]
            store._fact_key("agent", fact_id), mapping={"name": "alice"}
        )
        await store._client.sadd(store._index_key("agent"), fact_id)  # type: ignore[misc]

        results = await store.query("agent")
        assert results == [{"fact_id": fact_id, "name": "alice"}]


class TestRedisRetract:
    """retract() must remove the facts a caller identifies by value."""

    @pytest.mark.asyncio
    async def test_retract_by_string_id_removes_the_fact(
        self, store: RedisFactStore
    ) -> None:
        await store.assert_fact("agent", {"id": "123", "name": "alice"})
        await store.assert_fact("agent", {"id": "456", "name": "bob"})

        assert await store.retract("agent", {"id": "123"}) == 1

        remaining = await store.query("agent")
        assert len(remaining) == 1
        assert remaining[0]["id"] == "456"

    @pytest.mark.asyncio
    async def test_retract_all_clears_template(self, store: RedisFactStore) -> None:
        await store.assert_fact("agent", {"id": "a1"})
        await store.assert_fact("agent", {"id": "a2"})

        assert await store.retract("agent") == 2
        assert await store.query("agent") == []
        assert await store.count("agent") == 0

    @pytest.mark.asyncio
    async def test_retract_no_match_leaves_facts(self, store: RedisFactStore) -> None:
        await store.assert_fact("agent", {"id": "123"})
        assert await store.retract("agent", {"id": "nope"}) == 0
        assert await store.count("agent") == 1


class TestRedisSubscribe:
    """Change notifications reach subscribers via Redis Streams."""

    @pytest.mark.asyncio
    async def test_subscriber_receives_assert_and_retract(
        self, store: RedisFactStore
    ) -> None:
        received: list[FactChangeNotification] = []

        async def on_change(notification: FactChangeNotification) -> None:
            received.append(notification)

        unsubscribe = await store.subscribe("agent", on_change)
        try:
            # Give the listener task a chance to start reading the stream.
            await asyncio.sleep(0.5)
            await store.assert_fact("agent", {"id": "123"})
            await store.retract("agent", {"id": "123"})

            for _ in range(40):
                if len(received) >= 2:
                    break
                await asyncio.sleep(0.25)
        finally:
            unsubscribe()

        actions = [n.action for n in received]
        assert actions == ["assert", "retract"]
        assert received[0].template == "agent"
        assert received[0].data == {"id": "123"}


class TestRedisTtl:
    """The optional TTL expires fact keys."""

    @pytest.mark.asyncio
    async def test_ttl_applied_to_fact_key(self, redis_port: int) -> None:
        store = RedisFactStore(host="127.0.0.1", port=redis_port, db=11, ttl=60)
        await store._client.flushdb()
        try:
            fact_id = await store.assert_fact("agent", {"id": "a1"})
            ttl = await store._client.ttl(store._fact_key("agent", fact_id))
            assert 0 < ttl <= 60
        finally:
            await store._client.flushdb()
            await store.close()


class TestRedisEncoding:
    """The hash payload itself is JSON on every field."""

    @pytest.mark.asyncio
    async def test_every_field_is_json_encoded_on_disk(
        self, store: RedisFactStore
    ) -> None:
        fact_id = await store.assert_fact("agent", {"id": "123", "attempts": 3})
        raw = await store._client.hgetall(store._fact_key("agent", fact_id))  # type: ignore[misc]
        decoded = {
            (k.decode() if isinstance(k, bytes) else k): (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in raw.items()
        }
        assert decoded == {"id": json.dumps("123"), "attempts": json.dumps(3)}
