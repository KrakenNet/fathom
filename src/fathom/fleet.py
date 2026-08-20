"""FactStore protocol and in-memory implementation for Fathom fleet coordination.

Known limitation: fleet retraction does not propagate. :class:`FleetEngine`
exposes no ``retract`` method and never calls :meth:`FactStore.subscribe`, and
:meth:`FleetEngine.sync_fleet_facts` only ever asserts. A fact removed from the
shared store (explicitly, or by Redis TTL expiry) therefore stays in the working
memory of every session that already synced it. Callers that need removal to
reach peers must recreate the affected sessions.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any, Protocol, runtime_checkable

from fathom.engine import Engine
from fathom.models import FactChangeNotification

logger = logging.getLogger(__name__)

# Type aliases for fleet protocol types
FactFilter = dict[str, Any]
FactData = dict[str, Any]
FactId = str


__all__ = ["FactStore", "FleetEngine", "InMemoryFactStore"]


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
            # Validate locally FIRST: a fact this engine rejects must never reach
            # the shared store, where it would abort every peer's sync.
            handles = engine._assert_local(template, data)
            try:
                return await self._fact_store.assert_fact(template, data)
            except Exception:
                # The store write failed after the local assert; undo it so this
                # session does not hold a fleet fact the store never accepted.
                #
                # Roll back BY HANDLE, never by value. A retract-by-value
                # filter is wrong twice over: it misses a value FactManager
                # coerced on the way in (int 123 -> "123" for a STRING slot),
                # silently leaving the rejected fact behind; and when CLIPS
                # de-duplicated this assert onto an identical fact that was
                # already committed, it deletes THAT one — silent local data
                # loss on a transient store blip during a repeated heartbeat.
                # `handles` is empty in the de-dup case, which is exactly
                # right: we created nothing, so we withdraw nothing.
                try:
                    engine._retract_local_handles(handles)
                except Exception:
                    logger.warning(
                        "failed to roll back local assert of '%s' after fact store error",
                        template,
                        exc_info=True,
                    )
                raise

        # session scope — local-only, so the public Engine entry point applies
        # (its fleet-scope guard cannot trigger here) and metrics stay accurate.
        engine.assert_fact(template, data)
        return None

    async def sync_fleet_facts(self, session: Engine) -> None:
        """Pull fleet-scoped facts from the :class:`FactStore` into *session*.

        Queries the fact store for every fleet-scoped template and
        asserts matching facts into the session's working memory. A fact the
        session rejects is logged and skipped, so one malformed row in the
        shared store cannot stop the rest of the fleet state from syncing.
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
                try:
                    # Pulled from the authoritative FactStore; bypass the Engine-level
                    # scope guard since this is the legitimate path for fleet facts into
                    # a local engine. Still takes the engine lock and records the metric.
                    session._assert_local(tmpl_name, data)
                except Exception:
                    logger.warning(
                        "skipping unsyncable fleet fact %s of template '%s'",
                        fact.get("fact_id", "<unknown>"),
                        tmpl_name,
                        exc_info=True,
                    )

    async def query(
        self,
        template: str,
        fact_filter: FactFilter | None = None,
    ) -> list[FactData]:
        """Query the shared :class:`FactStore` for facts matching *template*."""
        return await self._fact_store.query(template, fact_filter)
