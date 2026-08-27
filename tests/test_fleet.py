"""Unit tests for InMemoryFactStore and FleetEngine."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest

from fathom.fleet import FleetEngine, InMemoryFactStore
from fathom.models import FactChangeNotification

if TYPE_CHECKING:
    from pathlib import Path

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


# ---------------------------------------------------------------------------
# FactChangeNotification model
# ---------------------------------------------------------------------------


class TestFactChangeNotification:
    """FactChangeNotification model construction and fields."""

    def test_assert_notification(self) -> None:
        n = FactChangeNotification(
            template="agent", fact_id="abc123", action="assert", data={"id": "a1"}
        )
        assert n.template == "agent"
        assert n.fact_id == "abc123"
        assert n.action == "assert"
        assert n.data == {"id": "a1"}

    def test_retract_notification(self) -> None:
        n = FactChangeNotification(template="agent", fact_id="xyz", action="retract", data=None)
        assert n.action == "retract"
        assert n.data is None

    def test_notification_requires_valid_action(self) -> None:
        with pytest.raises(ValueError):
            FactChangeNotification(
                template="agent",
                fact_id="abc",
                action="invalid",  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# InMemoryFactStore
# ---------------------------------------------------------------------------


class TestInMemoryFactStoreAssert:
    """InMemoryFactStore.assert_fact tests."""

    @pytest.mark.asyncio
    async def test_assert_returns_id(self) -> None:
        store = InMemoryFactStore()
        fid = await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        assert isinstance(fid, str)
        assert len(fid) > 0

    @pytest.mark.asyncio
    async def test_assert_multiple_returns_unique_ids(self) -> None:
        store = InMemoryFactStore()
        id1 = await store.assert_fact("agent", {"id": "a1"})
        id2 = await store.assert_fact("agent", {"id": "a2"})
        assert id1 != id2


class TestInMemoryFactStoreQuery:
    """InMemoryFactStore.query tests."""

    @pytest.mark.asyncio
    async def test_query_all(self) -> None:
        store = InMemoryFactStore()
        await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        await store.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        results = await store.query("agent")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_query_with_filter(self) -> None:
        store = InMemoryFactStore()
        await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        await store.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        results = await store.query("agent", {"clearance": "secret"})
        assert len(results) == 1
        assert results[0]["id"] == "a1"

    @pytest.mark.asyncio
    async def test_query_no_match(self) -> None:
        store = InMemoryFactStore()
        await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        results = await store.query("agent", {"clearance": "unclassified"})
        assert results == []

    @pytest.mark.asyncio
    async def test_query_empty_template(self) -> None:
        store = InMemoryFactStore()
        results = await store.query("nonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_query_includes_fact_id(self) -> None:
        store = InMemoryFactStore()
        fid = await store.assert_fact("agent", {"id": "a1"})
        results = await store.query("agent")
        assert len(results) == 1
        assert results[0]["fact_id"] == fid


class TestInMemoryFactStoreRetract:
    """InMemoryFactStore.retract tests."""

    @pytest.mark.asyncio
    async def test_retract_all(self) -> None:
        store = InMemoryFactStore()
        await store.assert_fact("agent", {"id": "a1"})
        await store.assert_fact("agent", {"id": "a2"})
        removed = await store.retract("agent")
        assert removed == 2
        assert await store.query("agent") == []

    @pytest.mark.asyncio
    async def test_retract_with_filter(self) -> None:
        store = InMemoryFactStore()
        await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        await store.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        removed = await store.retract("agent", {"clearance": "secret"})
        assert removed == 1
        remaining = await store.query("agent")
        assert len(remaining) == 1
        assert remaining[0]["id"] == "a2"

    @pytest.mark.asyncio
    async def test_retract_nonexistent(self) -> None:
        store = InMemoryFactStore()
        removed = await store.retract("nonexistent")
        assert removed == 0


class TestInMemoryFactStoreCount:
    """InMemoryFactStore.count tests."""

    @pytest.mark.asyncio
    async def test_count_all(self) -> None:
        store = InMemoryFactStore()
        await store.assert_fact("agent", {"id": "a1"})
        await store.assert_fact("agent", {"id": "a2"})
        assert await store.count("agent") == 2

    @pytest.mark.asyncio
    async def test_count_with_filter(self) -> None:
        store = InMemoryFactStore()
        await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        await store.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        assert await store.count("agent", {"clearance": "secret"}) == 1

    @pytest.mark.asyncio
    async def test_count_empty(self) -> None:
        store = InMemoryFactStore()
        assert await store.count("agent") == 0


class TestInMemoryFactStoreSubscribe:
    """InMemoryFactStore.subscribe tests."""

    @pytest.mark.asyncio
    async def test_subscribe_receives_assert_notification(self) -> None:
        store = InMemoryFactStore()
        notifications: list[FactChangeNotification] = []

        async def on_change(n: FactChangeNotification) -> None:
            notifications.append(n)

        await store.subscribe("agent", on_change)
        await store.assert_fact("agent", {"id": "a1"})

        assert len(notifications) == 1
        assert notifications[0].action == "assert"
        assert notifications[0].template == "agent"
        assert notifications[0].data == {"id": "a1"}

    @pytest.mark.asyncio
    async def test_subscribe_receives_retract_notification(self) -> None:
        store = InMemoryFactStore()
        notifications: list[FactChangeNotification] = []

        async def on_change(n: FactChangeNotification) -> None:
            notifications.append(n)

        await store.subscribe("agent", on_change)
        await store.assert_fact("agent", {"id": "a1"})
        await store.retract("agent", {"id": "a1"})

        assert len(notifications) == 2
        assert notifications[1].action == "retract"

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_notifications(self) -> None:
        store = InMemoryFactStore()
        notifications: list[FactChangeNotification] = []

        async def on_change(n: FactChangeNotification) -> None:
            notifications.append(n)

        unsub = await store.subscribe("agent", on_change)
        await store.assert_fact("agent", {"id": "a1"})
        unsub()
        await store.assert_fact("agent", {"id": "a2"})

        assert len(notifications) == 1  # only the first assert

    @pytest.mark.asyncio
    async def test_subscribe_different_templates_isolated(self) -> None:
        store = InMemoryFactStore()
        agent_notifs: list[FactChangeNotification] = []
        req_notifs: list[FactChangeNotification] = []

        async def on_agent(n: FactChangeNotification) -> None:
            agent_notifs.append(n)

        async def on_req(n: FactChangeNotification) -> None:
            req_notifs.append(n)

        await store.subscribe("agent", on_agent)
        await store.subscribe("request", on_req)
        await store.assert_fact("agent", {"id": "a1"})
        await store.assert_fact("request", {"type": "read"})

        assert len(agent_notifs) == 1
        assert len(req_notifs) == 1


# ---------------------------------------------------------------------------
# FleetEngine
# ---------------------------------------------------------------------------


class TestFleetEngineCreateSession:
    """FleetEngine.create_session tests."""

    def test_create_session_returns_engine(self) -> None:
        store = InMemoryFactStore()
        fleet = FleetEngine(fact_store=store, rules_path=FIXTURES_DIR)
        engine = fleet.create_session("sess-1")

        from fathom.engine import Engine

        assert isinstance(engine, Engine)

    def test_create_session_stored(self) -> None:
        store = InMemoryFactStore()
        fleet = FleetEngine(fact_store=store, rules_path=FIXTURES_DIR)
        engine = fleet.create_session("sess-1")
        assert fleet.sessions["sess-1"] is engine

    def test_multiple_sessions_isolated(self) -> None:
        store = InMemoryFactStore()
        fleet = FleetEngine(fact_store=store, rules_path=FIXTURES_DIR)
        e1 = fleet.create_session("sess-1")
        e2 = fleet.create_session("sess-2")
        assert e1 is not e2
        assert len(fleet.sessions) == 2


class TestFleetEngineSyncAndQuery:
    """FleetEngine fleet-scoped sync and query."""

    @pytest.mark.asyncio
    async def test_query_delegates_to_store(self) -> None:
        store = InMemoryFactStore()
        fleet = FleetEngine(fact_store=store, rules_path=FIXTURES_DIR)
        await store.assert_fact("agent", {"id": "a1"})
        results = await fleet.query("agent")
        assert len(results) == 1
        assert results[0]["id"] == "a1"

    @pytest.mark.asyncio
    async def test_query_with_filter(self) -> None:
        store = InMemoryFactStore()
        fleet = FleetEngine(fact_store=store, rules_path=FIXTURES_DIR)
        await store.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        await store.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        results = await fleet.query("agent", {"clearance": "secret"})
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_sync_fleet_facts_injects_fleet_scoped(self) -> None:
        """sync_fleet_facts pulls fleet-scoped facts into a session."""
        store = InMemoryFactStore()
        fleet = FleetEngine(fact_store=store, rules_path=FIXTURES_DIR)
        session = fleet.create_session("sess-1")

        # Manually register a fleet-scoped template in the session's registry
        from fathom.models import SlotDefinition, TemplateDefinition

        fleet_tmpl = TemplateDefinition(
            name="shared_status",
            slots=[SlotDefinition(name="status", type="string")],
            scope="fleet",
        )
        session._template_registry["shared_status"] = fleet_tmpl

        # Also build the deftemplate in CLIPS so assert_fact works
        session._safe_build(
            "(deftemplate shared_status (slot status (type STRING)))",
            context="test-fleet-tmpl",
        )

        # Put a fact in the store
        await store.assert_fact("shared_status", {"status": "online"})

        # Sync should inject the fact into the session
        await fleet.sync_fleet_facts(session)

        # Verify fact is now in session's working memory
        facts = list(session._env.facts())
        status_facts = [f for f in facts if f.template.name == "shared_status"]
        assert len(status_facts) == 1

    @pytest.mark.asyncio
    async def test_sync_skips_session_scoped(self) -> None:
        """sync_fleet_facts ignores session-scoped templates."""
        store = InMemoryFactStore()
        fleet = FleetEngine(fact_store=store, rules_path=FIXTURES_DIR)
        session = fleet.create_session("sess-1")

        # "agent" template is loaded from fixtures as session-scoped (default)
        await store.assert_fact("agent", {"id": "a1"})
        await fleet.sync_fleet_facts(session)

        # Session-scoped template facts should NOT be synced
        facts = list(session._env.facts())
        agent_facts = [f for f in facts if f.template.name == "agent"]
        assert len(agent_facts) == 0


@pytest.mark.asyncio
async def test_fleet_assert_fact_write_through(tmp_path: Path) -> None:
    """Fact asserted via FleetEngine is visible to other sessions after sync."""
    from fathom.models import SlotDefinition, SlotType, TemplateDefinition

    store = InMemoryFactStore()
    # Empty rules path — we'll seed templates manually.
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    fleet = FleetEngine(fact_store=store, rules_path=str(rules_dir))

    def _seed(engine: Any) -> None:
        tmpl = TemplateDefinition(
            name="user_session",
            scope="fleet",
            slots=[SlotDefinition(name="user", type=SlotType.STRING, required=True)],
        )
        engine._template_registry["user_session"] = tmpl
        engine._safe_build(
            "(deftemplate user_session (slot user (type STRING)))",
            context="user_session",
        )

    eng_a = fleet.create_session("A")
    _seed(eng_a)
    eng_b = fleet.create_session("B")
    _seed(eng_b)

    await fleet.assert_fact("A", "user_session", {"user": "alice"})

    # Session B pulls fleet facts
    await fleet.sync_fleet_facts(eng_b)
    facts = eng_b.query("user_session")
    assert any(f["user"] == "alice" for f in facts)


@pytest.mark.asyncio
async def test_fleet_assert_fact_session_scope_local_only(tmp_path: Path) -> None:
    """Session-scoped facts written through FleetEngine.assert_fact do not hit the store."""
    from fathom.models import SlotDefinition, SlotType, TemplateDefinition

    store = InMemoryFactStore()
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    fleet = FleetEngine(fact_store=store, rules_path=str(rules_dir))

    eng_a = fleet.create_session("A")
    tmpl = TemplateDefinition(
        name="local_note",
        scope="session",
        slots=[SlotDefinition(name="text", type=SlotType.STRING, required=True)],
    )
    eng_a._template_registry["local_note"] = tmpl
    eng_a._safe_build(
        "(deftemplate local_note (slot text (type STRING)))",
        context="local_note",
    )

    await fleet.assert_fact("A", "local_note", {"text": "hi"})
    # Store must not have it (session scope = no write-through).
    assert await store.count("local_note") == 0
    # But the session sees it.
    assert eng_a.query("local_note") == [{"text": "hi"}]


# ---------------------------------------------------------------------------
# Validate-before-write and sync resilience
# ---------------------------------------------------------------------------


def _seed_shared_status(engine: Any) -> None:
    """Register a fleet-scoped ``shared_status`` template with allowed values."""
    from fathom.models import SlotDefinition, SlotType, TemplateDefinition

    engine._template_registry["shared_status"] = TemplateDefinition(
        name="shared_status",
        scope="fleet",
        slots=[
            SlotDefinition(
                name="status",
                type=SlotType.STRING,
                required=True,
                allowed_values=["online", "offline"],
            )
        ],
    )
    engine._safe_build(
        "(deftemplate shared_status (slot status (type STRING)))",
        context="shared_status",
    )


class TestFleetEngineValidateBeforeWrite:
    """FleetEngine.assert_fact must not publish facts the local engine rejects."""

    @pytest.mark.asyncio
    async def test_invalid_fact_never_reaches_store(self, tmp_path: Path) -> None:
        from fathom.errors import ValidationError

        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        store = InMemoryFactStore()
        fleet = FleetEngine(fact_store=store, rules_path=str(rules_dir))
        engine = fleet.create_session("A")
        _seed_shared_status(engine)

        with pytest.raises(ValidationError):
            await fleet.assert_fact("A", "shared_status", {"status": "BOGUS"})

        assert await store.query("shared_status") == []
        assert engine.query("shared_status") == []

    @pytest.mark.asyncio
    async def test_store_failure_rolls_back_local_assert(self, tmp_path: Path) -> None:
        class FailingStore(InMemoryFactStore):
            async def assert_fact(self, template: str, data: dict[str, Any]) -> str:
                raise RuntimeError("store is down")

        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        fleet = FleetEngine(fact_store=FailingStore(), rules_path=str(rules_dir))
        engine = fleet.create_session("A")
        _seed_shared_status(engine)

        with pytest.raises(RuntimeError, match="store is down"):
            await fleet.assert_fact("A", "shared_status", {"status": "online"})

        assert engine.query("shared_status") == []

    @pytest.mark.asyncio
    async def test_rollback_removes_a_coerced_value(self, tmp_path: Path) -> None:
        """A rollback-by-value filter misses what FactManager coerced on the way in.

        ``{"status": 123}`` is coerced to ``"123"`` for a STRING slot, so a
        retract filtered on the RAW caller dict matched nothing, returned 0,
        and was silently ignored — leaving the node holding a fleet fact the
        store had rejected. The rollback now retracts by fact handle.
        """

        class FailingStore(InMemoryFactStore):
            async def assert_fact(self, template: str, data: dict[str, Any]) -> str:
                raise RuntimeError("store is down")

        from fathom.models import SlotDefinition, SlotType, TemplateDefinition

        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        fleet = FleetEngine(fact_store=FailingStore(), rules_path=str(rules_dir))
        engine = fleet.create_session("A")
        # No allowed_values, so 123 passes validation and is COERCED to "123".
        engine._template_registry["shared_status"] = TemplateDefinition(
            name="shared_status",
            scope="fleet",
            slots=[SlotDefinition(name="status", type=SlotType.STRING, required=True)],
        )
        engine._safe_build(
            "(deftemplate shared_status (slot status (type STRING)))",
            context="shared_status",
        )

        with pytest.raises(RuntimeError, match="store is down"):
            await fleet.assert_fact("A", "shared_status", {"status": 123})

        assert engine.query("shared_status") == []

    @pytest.mark.asyncio
    async def test_failed_duplicate_assert_keeps_the_committed_fact(self, tmp_path: Path) -> None:
        """A store blip on a repeated assert must not destroy the good fact.

        CLIPS de-duplicates identical facts, so the second assert creates
        nothing — and a rollback-by-value filter then deleted the ORIGINAL,
        still-committed fact. The node silently diverged from the store.
        """

        class FlakyStore(InMemoryFactStore):
            fail = False

            async def assert_fact(self, template: str, data: dict[str, Any]) -> str:
                if self.fail:
                    raise RuntimeError("store is down")
                return await super().assert_fact(template, data)

        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        store = FlakyStore()
        fleet = FleetEngine(fact_store=store, rules_path=str(rules_dir))
        engine = fleet.create_session("A")
        _seed_shared_status(engine)

        await fleet.assert_fact("A", "shared_status", {"status": "online"})
        assert engine.query("shared_status") == [{"status": "online"}]
        assert len(await store.query("shared_status")) == 1

        store.fail = True
        with pytest.raises(RuntimeError, match="store is down"):
            await fleet.assert_fact("A", "shared_status", {"status": "online"})

        # The fact the store still holds must still be in local working memory.
        assert engine.query("shared_status") == [{"status": "online"}]
        assert len(await store.query("shared_status")) == 1


class TestFleetScopeGuardIsSymmetric:
    """`retract` must refuse a fleet template just as `assert_fact` does."""

    def test_local_retract_of_a_fleet_fact_is_refused(self, tmp_path: Path) -> None:
        from fathom.engine import Engine
        from fathom.errors import ScopeError

        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        engine = Engine()
        _seed_shared_status(engine)
        engine._assert_local("shared_status", {"status": "online"})

        with pytest.raises(ScopeError, match="fleet-scoped"):
            engine.retract("shared_status")

        # Refused, not partially applied.
        assert engine.query("shared_status") == [{"status": "online"}]


class TestSyncFleetFactsResilience:
    """One unsyncable row must not abort the rest of the sync."""

    @pytest.mark.asyncio
    async def test_poison_fact_skipped_valid_facts_land(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        store = InMemoryFactStore()
        fleet = FleetEngine(fact_store=store, rules_path=str(rules_dir))

        # A poisoned row published by some other node, followed by a valid one.
        await store.assert_fact("shared_status", {"status": "BOGUS"})
        await store.assert_fact("shared_status", {"status": "online"})

        peer = fleet.create_session("B")
        _seed_shared_status(peer)

        with caplog.at_level("WARNING", logger="fathom.fleet"):
            await fleet.sync_fleet_facts(peer)

        assert peer.query("shared_status") == [{"status": "online"}]
        assert any("skipping unsyncable fleet fact" in r.message for r in caplog.records)


def test_a_fleet_template_cannot_declare_the_reserved_fact_id_slot() -> None:
    """`fact_id` is the store's own key, and it wins.

    `FactStore.query` returns `{"fact_id": <row id>, **data}` and the fleet
    sync then strips `fact_id` before asserting, so a template that declared
    a slot by that name published a value the peers never received: the
    publisher decided with it and every peer decided without it. Declaring it
    is refused instead, where the author can see it.
    """
    import pytest
    from pydantic import ValidationError as PydanticValidationError

    from fathom.models import SlotDefinition, SlotType, TemplateDefinition

    slots = [
        SlotDefinition(name="fact_id", type=SlotType.STRING, required=True),
        SlotDefinition(name="agent", type=SlotType.STRING, required=True),
    ]

    # Session-scoped templates are unaffected: nothing shares them.
    TemplateDefinition(name="local_note", slots=slots)

    with pytest.raises(PydanticValidationError, match="fact_id"):
        TemplateDefinition(name="fleet_note", slots=slots, scope="fleet")
