"""PostgreSQL-backed FactStore using asyncpg.

Stores facts in a ``fleet_facts`` table with a JSONB ``data`` column.
Uses PostgreSQL LISTEN/NOTIFY on per-template channels
(``fathom_changes_{template}``, or ``fathom_changes_{sha256 prefix}`` when
that name exceeds Postgres' 63-byte limit) to propagate change notifications
to subscribers. A NOTIFY payload is limited to 8000 bytes by Postgres, so a
fact whose JSON is larger fails ``assert_fact`` and nothing is stored.

Requires ``asyncpg``.  Install with::

    pip install fathom-rules[fleet-pg]
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

try:
    import asyncpg  # type: ignore[import-untyped]
except ImportError as _exc:
    raise ImportError(
        "asyncpg is required for Postgres fleet store. "
        "Install it with: pip install fathom-rules[fleet-pg]"
    ) from _exc

from fathom.errors import FleetConnectionError, FleetError
from fathom.fleet import _dispatch
from fathom.models import FactChangeNotification

__all__ = ["PostgresFactStore"]

# Callback type alias (mirrors fleet.py)
_SubscriptionCallback = Callable[[FactChangeNotification], Coroutine[Any, Any, None]]

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS fleet_facts (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template   TEXT NOT NULL,
    data       JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fleet_facts_template
    ON fleet_facts (template);
"""

_INSERT_SQL = """\
INSERT INTO fleet_facts (id, template, data)
VALUES ($1, $2, $3::jsonb)
RETURNING id;
"""

_SELECT_SQL = """\
SELECT id, template, data, created_at
FROM fleet_facts
WHERE template = $1;
"""

_DELETE_SQL = """\
DELETE FROM fleet_facts
WHERE template = $1
RETURNING id, data;
"""

_COUNT_SQL = """\
SELECT COUNT(*) FROM fleet_facts
WHERE template = $1;
"""

#: Everything asyncpg raises that the store reports as a FleetError.
_DRIVER_ERRORS = (OSError, asyncpg.PostgresError, asyncpg.InterfaceError)


def _fleet_error(exc: BaseException, operation: str) -> FleetError:
    """Map a driver error to FleetConnectionError (connection lost or
    unreachable) or FleetError (anything else)."""
    if isinstance(exc, (OSError, asyncpg.PostgresConnectionError)):
        return FleetConnectionError(
            f"PostgreSQL connection failed during {operation}: {exc}", backend="postgres"
        )
    return FleetError(f"PostgreSQL error during {operation}: {exc}")


#: Postgres identifier limit (NAMEDATALEN - 1) for LISTEN/NOTIFY channels.
_MAX_CHANNEL_BYTES = 63

#: Backoff for re-establishing the LISTEN connection after the backend dies.
_RECONNECT_BASE_DELAY = 0.5
_RECONNECT_MAX_DELAY = 30.0


class PostgresFactStore:
    """Async fact store backed by PostgreSQL.

    Call ``await connect()`` before anything else: it creates the
    connection pool and the ``fleet_facts`` table. Before it,
    :meth:`assert_fact`, :meth:`query`, :meth:`retract`, :meth:`count` and
    :meth:`ensure_table` raise :class:`~fathom.errors.FleetError`. Call
    :meth:`close` when done.

    Each write runs in one transaction with its ``pg_notify``, so a fact and
    its notification commit together or not at all. Postgres limits a
    NOTIFY payload to 8000 bytes; a fact whose payload (template, fact_id,
    action and data as JSON) is larger fails :meth:`assert_fact` with
    :class:`~fathom.errors.FleetError` and nothing is stored. A retract
    over the limit rolls back the same way. Concurrent retracts of the same
    fact count and announce it once.

    :meth:`subscribe` LISTENs on the template's channel, so a callback runs
    after the write commits, once, also in the writing process. If the
    LISTEN connection drops, the store reconnects with backoff (0.5s
    doubling to 30s); NOTIFY has no replay, so changes made while it is
    down are lost.

    Channels are named ``fathom_changes_<template>`` with every
    non-alphanumeric character replaced by ``_``. When that is over
    Postgres' 63-byte identifier limit the channel is
    ``fathom_changes_<first 32 hex digits of sha256(template)>``. There is
    no limit on the template name itself.

    Errors are not retried. A server that is unreachable or a connection
    lost mid-statement raises :class:`~fathom.errors.FleetConnectionError`;
    any other driver error raises :class:`~fathom.errors.FleetError`. There is no fact TTL.

    Parameters
    ----------
    dsn:
        PostgreSQL connection string, e.g.
        ``"postgresql://user:pass@localhost:5432/fathom"``.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool[asyncpg.Record] | None = None
        self._listen_conn: asyncpg.Connection[asyncpg.Record] | None = None
        self._subscribers: dict[str, list[_SubscriptionCallback]] = defaultdict(list)
        self._listening_templates: set[str] = set()
        #: Templates whose channel is registered on the *current* LISTEN
        #: connection. Cleared whenever that connection is replaced.
        self._registered: set[str] = set()
        self._listen_lock = asyncio.Lock()
        self._listener_task: asyncio.Task[None] | None = None
        self._closing = False

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create connection pool and set up the schema."""
        try:
            self._pool = await asyncpg.create_pool(dsn=self._dsn)
            await self.ensure_table()
        except _DRIVER_ERRORS as exc:
            raise _fleet_error(exc, "connect") from exc

    async def close(self) -> None:
        """Shut down connections."""
        # Closing the LISTEN connection fires the termination listener like any
        # other backend loss would; say so first, or close() starts a reconnect.
        self._closing = True
        if self._listener_task is not None:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        try:
            if self._listen_conn is not None:
                await self._listen_conn.close()
                self._listen_conn = None
            if self._pool is not None:
                await self._pool.close()
                self._pool = None
        except _DRIVER_ERRORS as exc:
            raise _fleet_error(exc, "close") from exc

    async def ensure_table(self) -> None:
        """Create the ``fleet_facts`` table if it does not exist."""
        pool = self._require_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(_CREATE_TABLE_SQL)
        except _DRIVER_ERRORS as exc:
            raise _fleet_error(exc, "ensure_table") from exc

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _require_pool(self) -> asyncpg.Pool[asyncpg.Record]:
        if self._pool is None:
            raise FleetError("PostgresFactStore is not connected; call connect() first")
        return self._pool

    def _channel_for(self, template: str) -> str:
        """Return the LISTEN/NOTIFY channel name for *template*."""
        # Sanitise: replace non-alphanumeric chars with underscores
        safe = "".join(c if c.isalnum() else "_" for c in template)
        channel = f"fathom_changes_{safe}"
        # Postgres refuses (NOTIFY) or truncates (LISTEN) a channel name over
        # 63 bytes. Past that, name the channel by a digest of the template:
        # every node derives the same name, and names that fit keep theirs.
        if len(channel.encode()) > _MAX_CHANNEL_BYTES:
            digest = hashlib.sha256(template.encode()).hexdigest()[:32]
            channel = f"fathom_changes_{digest}"
        return channel

    @staticmethod
    def _matches(data: dict[str, Any], fact_filter: dict[str, Any] | None) -> bool:
        """Return True if *data* satisfies every key/value pair in *fact_filter*."""
        if not fact_filter:
            return True
        return all(data.get(k) == v for k, v in fact_filter.items())

    async def _notify_pg(
        self,
        conn: asyncpg.Connection[asyncpg.Record],
        template: str,
        notification: FactChangeNotification,
    ) -> None:
        """Send a PostgreSQL NOTIFY on the template channel."""
        channel = self._channel_for(template)
        payload = json.dumps(
            {
                "template": notification.template,
                "fact_id": notification.fact_id,
                "action": notification.action,
                "data": notification.data,
            }
        )
        try:
            # NOTIFY is a utility statement whose payload must be a literal, so
            # it cannot take a bind parameter. pg_notify() is a normal function.
            await conn.execute("SELECT pg_notify($1, $2)", channel, payload)
        except asyncpg.PostgresConnectionError:
            raise  # the caller reports it as a lost connection
        except asyncpg.PostgresError as exc:
            raise FleetError(
                f"Failed to send NOTIFY on channel {channel}: {exc}",
            ) from exc

    async def _notify_subscribers(self, notification: FactChangeNotification) -> None:
        """Invoke local subscriber callbacks."""
        await _dispatch(self._subscribers.get(notification.template, []), notification)

    # ------------------------------------------------------------------
    # LISTEN support
    # ------------------------------------------------------------------

    async def _ensure_listen_conn(self) -> asyncpg.Connection[asyncpg.Record]:
        """Return a live LISTEN connection, replacing one whose backend is gone.

        A terminated backend leaves an ``asyncpg.Connection`` object behind that
        answers ``is_closed()`` and nothing else. Handing it back would register
        listeners that never fire. Caller must hold ``_listen_lock``.
        """
        conn = self._listen_conn
        if conn is not None and not conn.is_closed():
            return conn

        # A new connection carries none of the old one's listeners.
        self._registered.clear()
        try:
            conn = await asyncpg.connect(dsn=self._dsn)
        except _DRIVER_ERRORS as exc:
            raise _fleet_error(exc, "LISTEN connect") from exc

        conn.add_termination_listener(self._on_listen_conn_lost)
        self._listen_conn = conn
        return conn

    async def _on_notification(
        self,
        conn: asyncpg.Connection[asyncpg.Record],
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Turn a PostgreSQL NOTIFY payload into a local subscriber dispatch."""
        data = json.loads(payload)
        await self._notify_subscribers(
            FactChangeNotification(
                template=data["template"],
                fact_id=data["fact_id"],
                action=data["action"],
                data=data.get("data"),
            )
        )

    async def _sync_listeners(self) -> None:
        """Give the current LISTEN connection a listener per subscribed template.

        The single funnel for both a fresh ``subscribe()`` and a reconnect, so a
        template is never registered twice on one connection and never left off
        a replacement.
        """
        async with self._listen_lock:
            conn = await self._ensure_listen_conn()
            for template in sorted(self._listening_templates - self._registered):
                try:
                    await conn.add_listener(self._channel_for(template), self._on_notification)
                except _DRIVER_ERRORS as exc:
                    raise _fleet_error(exc, "subscribe") from exc
                self._registered.add(template)

    def _on_listen_conn_lost(self, _conn: asyncpg.Connection[asyncpg.Record]) -> None:
        """asyncpg calls this when the LISTEN backend goes away."""
        if self._closing or not self._listening_templates:
            return
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._relisten())

    async def _relisten(self) -> None:
        """Reconnect and re-register every template, backing off while the
        server is unreachable.

        NOTIFY has no replay: changes made between the backend dying and this
        succeeding are lost. Reconnecting bounds that window; leaving the dead
        connection in place made it permanent.
        """
        delay = _RECONNECT_BASE_DELAY
        while not self._closing and self._listening_templates:
            try:
                await self._sync_listeners()
            except Exception:  # noqa: BLE001 -- a reconnect loop that dies is the bug
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX_DELAY)
                continue
            return

    async def _start_listening(self, template: str) -> None:
        """Subscribe to the PostgreSQL channel for *template*."""
        if template in self._listening_templates:
            return
        self._listening_templates.add(template)
        try:
            await self._sync_listeners()
        except BaseException:
            self._listening_templates.discard(template)
            raise

    # ------------------------------------------------------------------
    # FactStore interface
    # ------------------------------------------------------------------

    async def assert_fact(self, template: str, data: dict[str, Any]) -> str:
        """Assert a fact and return its unique fact_id."""
        pool = self._require_pool()
        fact_id = uuid.uuid4().hex
        fact_uuid = uuid.UUID(fact_id)
        try:
            async with pool.acquire() as conn, conn.transaction():
                # INSERT and NOTIFY commit together: a notify failure must not
                # leave a durable row that no subscriber was ever told about.
                await conn.execute(_INSERT_SQL, fact_uuid, template, json.dumps(data))
                # Subscribers in this process hear it through the LISTEN
                # connection like every peer does, so each hears it once.
                await self._notify_pg(
                    conn,
                    template,
                    FactChangeNotification(
                        template=template, fact_id=fact_id, action="assert", data=data
                    ),
                )
        except _DRIVER_ERRORS as exc:
            raise _fleet_error(exc, "assert_fact") from exc
        return fact_id

    async def query(
        self, template: str, fact_filter: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Return facts matching the template and optional filter."""
        pool = self._require_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(_SELECT_SQL, template)
        except _DRIVER_ERRORS as exc:
            raise _fleet_error(exc, "query") from exc
        results: list[dict[str, Any]] = []
        for row in rows:
            raw = row["data"]
            row_data: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else dict(raw)
            if self._matches(row_data, fact_filter):
                results.append({"fact_id": row["id"].hex, **row_data})
        return results

    async def retract(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Retract facts matching the template and optional filter. Return count removed."""
        pool = self._require_pool()
        try:
            if fact_filter:
                # With a filter we must check each row in Python
                matching = await self.query(template, fact_filter)
                if not matching:
                    return 0
                sql = "DELETE FROM fleet_facts WHERE id = ANY($1::uuid[]) RETURNING id, data"
                arg: Any = [uuid.UUID(m["fact_id"]) for m in matching]
            else:
                sql, arg = _DELETE_SQL, template
            # DELETE and NOTIFY commit together, as in assert_fact. Announce
            # only the rows this DELETE removed: a concurrent retract may
            # already have taken some of the ones the query matched.
            async with pool.acquire() as conn, conn.transaction():
                rows = await conn.fetch(sql, arg)
                for row in rows:
                    row_data: dict[str, Any] = (
                        json.loads(row["data"])
                        if isinstance(row["data"], str)
                        else dict(row["data"])
                    )
                    await self._notify_pg(
                        conn,
                        template,
                        FactChangeNotification(
                            template=template,
                            fact_id=row["id"].hex,
                            action="retract",
                            data=row_data,
                        ),
                    )
            return len(rows)
        except _DRIVER_ERRORS as exc:
            raise _fleet_error(exc, "retract") from exc

    async def count(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Count facts matching the template and optional filter."""
        pool = self._require_pool()
        if fact_filter:
            # Must filter in Python
            matching = await self.query(template, fact_filter)
            return len(matching)
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_COUNT_SQL, template)
        except _DRIVER_ERRORS as exc:
            raise _fleet_error(exc, "count") from exc
        return int(row["count"]) if row else 0

    async def subscribe(
        self,
        template: str,
        callback: _SubscriptionCallback,
    ) -> Callable[[], None]:
        """Subscribe to changes on a template. Return an unsubscribe callable."""
        self._subscribers[template].append(callback)
        await self._start_listening(template)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._subscribers[template].remove(callback)

        return unsubscribe
