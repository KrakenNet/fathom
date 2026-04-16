"""FactStore protocol and in-memory implementation for Fathom fleet coordination."""

from __future__ import annotations

import contextlib
import uuid
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any, Protocol, runtime_checkable

from fathom.engine import Engine
from fathom.models import FactChangeNotification

# Type aliases for fleet protocol types
FactFilter = dict[str, Any]
FactData = dict[str, Any]
FactId = str


@runtime_checkable
class FactStore(Protocol):
    """Protocol defining the async fact-storage interface."""

    async def assert_fact(self, template: str, data: FactData) -> FactId:
        """Assert a fact and return its unique fact_id."""
        ...

    async def query(self, template: str, fact_filter: FactFilter | None = None) -> list[FactData]:
        """Return facts matching the template and optional filter."""
        ...

    async def retract(self, template: str, fact_filter: FactFilter | None = None) -> int:
        """Retract facts matching the template and optional filter. Return count removed."""
        ...

    async def count(self, template: str, fact_filter: FactFilter | None = None) -> int:
        """Count facts matching the template and optional filter."""
        ...

    async def subscribe(
        self,
        template: str,
        callback: Callable[[FactChangeNotification], Coroutine[Any, Any, None]],
    ) -> Callable[[], None]:
        """Subscribe to changes on a template. Return an unsubscribe callable."""
        ...


# Callback type alias for readability
_SubscriptionCallback = Callable[[FactChangeNotification], Coroutine[Any, Any, None]]


class InMemoryFactStore:
    """Default in-memory implementation of :class:`FactStore`."""

    def __init__(self) -> None:
        # template -> {fact_id -> data}
        self._facts: dict[str, dict[FactId, FactData]] = defaultdict(dict)
        # template -> [callback, ...]
        self._subscribers: dict[str, list[_SubscriptionCallback]] = defaultdict(list)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _matches(self, data: FactData, fact_filter: FactFilter | None) -> bool:
        """Return True if *data* satisfies every key/value pair in *fact_filter*."""
        if not fact_filter:
            return True
        return all(data.get(k) == v for k, v in fact_filter.items())

    async def _notify(self, notification: FactChangeNotification) -> None:
        for cb in self._subscribers.get(notification.template, []):
            await cb(notification)

    # ------------------------------------------------------------------
    # FactStore interface
    # ------------------------------------------------------------------

    async def assert_fact(self, template: str, data: FactData) -> FactId:
        fact_id = uuid.uuid4().hex
        self._facts[template][fact_id] = data
        await self._notify(
            FactChangeNotification(template=template, fact_id=fact_id, action="assert", data=data)
        )
        return fact_id

    async def query(self, template: str, fact_filter: FactFilter | None = None) -> list[FactData]:
        return [
            {"fact_id": fid, **data}
            for fid, data in self._facts.get(template, {}).items()
            if self._matches(data, fact_filter)
        ]

    async def retract(self, template: str, fact_filter: FactFilter | None = None) -> int:
        to_remove = [
            fid
            for fid, data in self._facts.get(template, {}).items()
            if self._matches(data, fact_filter)
        ]
        for fid in to_remove:
            data = self._facts[template].pop(fid)
            await self._notify(
                FactChangeNotification(template=template, fact_id=fid, action="retract", data=data)
            )
        return len(to_remove)

    async def count(self, template: str, fact_filter: FactFilter | None = None) -> int:
        return sum(
            1
            for data in self._facts.get(template, {}).values()
            if self._matches(data, fact_filter)
        )

    async def subscribe(
        self,
        template: str,
        callback: _SubscriptionCallback,
    ) -> Callable[[], None]:
        self._subscribers[template].append(callback)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._subscribers[template].remove(callback)

        return unsubscribe


class FleetEngine:
    """Manages multiple session-scoped Engines backed by a shared :class:`FactStore`.

    Fleet-scoped facts (those whose template has ``scope="fleet"``) are
    visible across all sessions via :meth:`sync_fleet_facts`.
    """

    def __init__(
        self,
        fact_store: FactStore,
        rules_path: str,
        **engine_kwargs: Any,
    ) -> None:
        self._fact_store = fact_store
        self._rules_path = rules_path
        self._engine_kwargs = engine_kwargs
        self._sessions: dict[str, Engine] = {}

    @property
    def sessions(self) -> dict[str, Engine]:
        """Return the mapping of session IDs to Engine instances."""
        return dict(self._sessions)

    def create_session(self, session_id: str) -> Engine:
        """Create and return an isolated :class:`Engine` for *session_id*.

        The engine is loaded from the configured rules path and stored
        internally so it can be retrieved later.
        """
        engine = Engine.from_rules(self._rules_path, **self._engine_kwargs)
        self._sessions[session_id] = engine
        return engine

    async def assert_fact(
        self,
        session_id: str,
        template: str,
        data: FactData,
    ) -> FactId | None:
        """Assert a fact into *session_id*, routing fleet-scoped facts to the store.

        Returns the assigned ``fact_id`` for fleet-scoped templates, or ``None``
        for session-scoped templates.

        Raises:
            KeyError: if *session_id* has no associated Engine.
            ValidationError: if the template is not registered on that Engine.
        """
        if session_id not in self._sessions:
            raise KeyError(f"unknown session '{session_id}'")
        engine = self._sessions[session_id]

        tmpl_def = engine.template_registry.get(template)
        if tmpl_def is None:
            from fathom.errors import ValidationError
            raise ValidationError(
                f"Unknown template '{template}'",
                template=template,
            )

        if tmpl_def.scope == "fleet":
            # Write-through: store first (authoritative), then local assert.
            fact_id = await self._fact_store.assert_fact(template, data)
            engine._fact_manager.assert_fact(template, data)
            return fact_id

        # session scope — local-only. Bypass Engine.assert_fact (which now
        # raises on fleet templates) and go straight through the fact manager.
        engine._fact_manager.assert_fact(template, data)
        return None

    async def sync_fleet_facts(self, session: Engine) -> None:
        """Pull fleet-scoped facts from the :class:`FactStore` into *session*.

        Queries the fact store for every fleet-scoped template and
        asserts matching facts into the session's working memory.
        """
        # Discover fleet-scoped templates from the session's loaded templates
        for tmpl_name, tmpl_def in session.template_registry.items():
            scope = tmpl_def.scope
            if scope != "fleet":
                continue
            facts = await self._fact_store.query(tmpl_name)
            for fact in facts:
                # Remove fact_id metadata before asserting into CLIPS
                data = {k: v for k, v in fact.items() if k != "fact_id"}
                # Pulled from the authoritative FactStore; bypass the Engine-level
                # scope guard since this is the legitimate path for fleet facts into
                # a local engine.
                session._fact_manager.assert_fact(tmpl_name, data)

    async def query(
        self,
        template: str,
        fact_filter: FactFilter | None = None,
    ) -> list[FactData]:
        """Query the shared :class:`FactStore` for facts matching *template*."""
        return await self._fact_store.query(template, fact_filter)
