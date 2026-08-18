"""Integration tests for PostgresFactStore against a real PostgreSQL server."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import asyncpg  # type: ignore[import-untyped]
import pytest
import pytest_asyncio

from fathom.errors import FleetError
from fathom.fleet_pg import PostgresFactStore
from tests.test_fleet_integration import (
    POSTGRES_IMAGE,
    POSTGRES_PASSWORD,
    postgres_accepts,
    requires_docker,
    running_container,
    wait_until,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from fathom.models import FactChangeNotification

pytestmark = [pytest.mark.integration, requires_docker]


@pytest.fixture(scope="module")
def postgres_dsn() -> Iterator[str]:
    """Start a PostgreSQL container for this module and yield its DSN."""
    with running_container(
        POSTGRES_IMAGE,
        5432,
        env={"POSTGRES_PASSWORD": POSTGRES_PASSWORD},
    ) as (_container_id, host_port):
        dsn = f"postgresql://postgres:{POSTGRES_PASSWORD}@127.0.0.1:{host_port}/postgres"
        wait_until(lambda: postgres_accepts(dsn), timeout=60.0)
        yield dsn


@pytest_asyncio.fixture
async def store(postgres_dsn: str) -> AsyncIterator[PostgresFactStore]:
    """A connected PostgresFactStore with an empty ``fleet_facts`` table."""
    s = PostgresFactStore(postgres_dsn)
    await s.connect()
    assert s._pool is not None
    async with s._pool.acquire() as conn:
        await conn.execute("TRUNCATE fleet_facts")
    try:
        yield s
    finally:
        await s.close()


class TestPostgresAssertFact:
    """assert_fact must commit the row and announce it on the channel."""

    @pytest.mark.asyncio
    async def test_assert_commits_and_is_queryable(self, store: PostgresFactStore) -> None:
        fact_id = await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})

        results = await store.query("agent")
        assert results == [{"fact_id": fact_id, "id": "a1", "clearance": "secret"}]
        assert await store.count("agent") == 1

    @pytest.mark.asyncio
    async def test_assert_notifies_listeners(self, store: PostgresFactStore) -> None:
        received: list[FactChangeNotification] = []

        async def on_change(notification: FactChangeNotification) -> None:
            received.append(notification)

        await store.subscribe("agent", on_change)
        fact_id = await store.assert_fact("agent", {"id": "a1"})

        # Subscribers are reached twice: once by the direct local dispatch and
        # once by the out-of-band LISTEN delivery of the same pg_notify.
        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.25)

        assert received
        assert {n.action for n in received} == {"assert"}
        assert all(n.fact_id == fact_id for n in received)
        assert all(n.data == {"id": "a1"} for n in received)

    @pytest.mark.asyncio
    async def test_notify_failure_leaves_no_orphan_row(
        self, store: PostgresFactStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failing NOTIFY must roll the INSERT back, not commit it silently."""
        monkeypatch.setattr(PostgresFactStore, "_channel_for", lambda self, template: "")

        with pytest.raises(FleetError):
            await store.assert_fact("agent", {"id": "a1"})

        monkeypatch.undo()
        assert await store.query("agent") == []
        assert await store.count("agent") == 0


class TestPostgresRetract:
    """retract must delete rows and announce each removal."""

    @pytest.mark.asyncio
    async def test_retract_with_filter(self, store: PostgresFactStore) -> None:
        await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        await store.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})

        assert await store.retract("agent", {"clearance": "secret"}) == 1

        remaining = await store.query("agent")
        assert len(remaining) == 1
        assert remaining[0]["id"] == "a2"

    @pytest.mark.asyncio
    async def test_retract_all_for_template(self, store: PostgresFactStore) -> None:
        await store.assert_fact("agent", {"id": "a1"})
        await store.assert_fact("agent", {"id": "a2"})
        await store.assert_fact("request", {"kind": "read"})

        assert await store.retract("agent") == 2
        assert await store.query("agent") == []
        assert await store.count("request") == 1

    @pytest.mark.asyncio
    async def test_retract_no_match(self, store: PostgresFactStore) -> None:
        await store.assert_fact("agent", {"id": "a1"})
        assert await store.retract("agent", {"id": "nope"}) == 0
        assert await store.count("agent") == 1

    @pytest.mark.asyncio
    async def test_retract_notifies_subscribers(self, store: PostgresFactStore) -> None:
        received: list[FactChangeNotification] = []

        async def on_change(notification: FactChangeNotification) -> None:
            received.append(notification)

        await store.subscribe("agent", on_change)
        await store.assert_fact("agent", {"id": "a1"})
        await store.retract("agent")

        # Each change reaches the subscriber twice (local dispatch + LISTEN).
        actions = [n.action for n in received]
        assert set(actions) == {"assert", "retract"}
        assert actions[0] == "assert"
        assert actions[-1] == "retract"


class TestPostgresQueryAndCount:
    """Filtering happens in Python over the JSONB payload."""

    @pytest.mark.asyncio
    async def test_query_with_filter(self, store: PostgresFactStore) -> None:
        await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        await store.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})

        results = await store.query("agent", {"clearance": "secret"})
        assert len(results) == 1
        assert results[0]["id"] == "a1"

    @pytest.mark.asyncio
    async def test_count_with_and_without_filter(self, store: PostgresFactStore) -> None:
        await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        await store.assert_fact("agent", {"id": "a2", "clearance": "secret"})

        assert await store.count("agent") == 2
        assert await store.count("agent", {"id": "a1"}) == 1
        assert await store.count("missing") == 0

    @pytest.mark.asyncio
    async def test_value_types_round_trip(self, store: PostgresFactStore) -> None:
        data = {"id": "123", "attempts": 3, "score": 1.5, "ok": True, "note": None}
        fact_id = await store.assert_fact("agent", data)
        assert await store.query("agent") == [{"fact_id": fact_id, **data}]


class TestPostgresChannelNames:
    """Channel names are sanitised before they reach pg_notify."""

    def test_channel_for_strips_unsafe_characters(self) -> None:
        store = PostgresFactStore("postgresql://unused")
        assert store._channel_for('ag"ent);--') == "fathom_changes_ag_ent____"

    @pytest.mark.asyncio
    async def test_template_with_unsafe_characters_round_trips(
        self, store: PostgresFactStore
    ) -> None:
        template = 'ag"ent);--'
        fact_id = await store.assert_fact(template, {"id": "a1"})
        assert await store.query(template) == [{"fact_id": fact_id, "id": "a1"}]
        assert await store.retract(template) == 1


class TestPostgresNotifyPayload:
    """pg_notify carries the payload as a bind parameter, not a literal."""

    @pytest.mark.asyncio
    async def test_payload_with_quotes_is_delivered_verbatim(
        self, store: PostgresFactStore
    ) -> None:
        received: list[str] = []
        conn = await asyncpg.connect(dsn=store._dsn)
        try:

            async def on_notify(_conn: object, _pid: int, _channel: str, payload: str) -> None:
                received.append(payload)

            await conn.add_listener(store._channel_for("agent"), on_notify)
            await store.assert_fact("agent", {"id": "it's a1"})

            for _ in range(20):
                if received:
                    break
                await asyncio.sleep(0.25)
        finally:
            await conn.close()

        assert len(received) == 1
        assert "it's a1" in received[0]
