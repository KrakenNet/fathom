"""PostgreSQL-backed FactStore using asyncpg.

Stores facts in a ``fleet_facts`` table with a JSONB ``data`` column.
Uses PostgreSQL LISTEN/NOTIFY on per-template channels
(``fathom_changes_{template}``) to propagate change notifications to
subscribers.

Requires ``asyncpg``.  Install with::

    pip install fathom-rules[fleet-pg]
"""

from __future__ import annotations

import asyncio
import contextlib
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
from fathom.models import FactChangeNotification

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


class PostgresFactStore:
    """Async fact store backed by PostgreSQL.

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
        self._listener_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create connection pool and set up the schema."""
        try:
            self._pool = await asyncpg.create_pool(dsn=self._dsn)
            await self.ensure_table()
        except OSError as exc:
            raise FleetConnectionError(
                f"Failed to connect to PostgreSQL: {exc}",
                backend="postgres",
            ) from exc
        except asyncpg.PostgresError as exc:
            raise FleetError(
                f"PostgreSQL error during connect: {exc}",
            ) from exc

    async def close(self) -> None:
        """Shut down connections."""
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
        except OSError as exc:
            raise FleetConnectionError(
                f"Failed to close PostgreSQL connections: {exc}",
                backend="postgres",
            ) from exc
        except asyncpg.PostgresError as exc:
            raise FleetError(
                f"PostgreSQL error during close: {exc}",
            ) from exc

    async def ensure_table(self) -> None:
        """Create the ``fleet_facts`` table if it does not exist."""
        assert self._pool is not None, "call connect() first"
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(_CREATE_TABLE_SQL)
        except asyncpg.PostgresError as exc:
            raise FleetError(
                f"Failed to create fleet_facts table: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _channel_for(self, template: str) -> str:
        """Return the LISTEN/NOTIFY channel name for *template*."""
        # Sanitise: replace non-alphanumeric chars with underscores
        safe = "".join(c if c.isalnum() else "_" for c in template)
        return f"fathom_changes_{safe}"

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
            await conn.execute(f'NOTIFY "{channel}", $1', payload)
        except asyncpg.PostgresError as exc:
            raise FleetError(
                f"Failed to send NOTIFY on channel {channel}: {exc}",
            ) from exc

    async def _notify_subscribers(self, notification: FactChangeNotification) -> None:
        """Invoke local subscriber callbacks."""
        for cb in self._subscribers.get(notification.template, []):
            await cb(notification)

    # ------------------------------------------------------------------
    # LISTEN support
    # ------------------------------------------------------------------

    async def _ensure_listen_conn(self) -> asyncpg.Connection[asyncpg.Record]:
        """Return (and lazily create) a dedicated LISTEN connection."""
        if self._listen_conn is None:
            try:
                self._listen_conn = await asyncpg.connect(dsn=self._dsn)
            except OSError as exc:
                raise FleetConnectionError(
                    f"Failed to create LISTEN connection: {exc}",
                    backend="postgres",
                ) from exc
            except asyncpg.PostgresError as exc:
                raise FleetError(
                    f"PostgreSQL error creating LISTEN connection: {exc}",
                ) from exc
        return self._listen_conn

    async def _start_listening(self, template: str) -> None:
        """Subscribe to the PostgreSQL channel for *template*."""
        if template in self._listening_templates:
            return
        conn = await self._ensure_listen_conn()
        channel = self._channel_for(template)

        async def _on_notification(
            conn: asyncpg.Connection[asyncpg.Record],
            pid: int,
            channel: str,
            payload: str,
        ) -> None:
            data = json.loads(payload)
            notif = FactChangeNotification(
                template=data["template"],
                fact_id=data["fact_id"],
                action=data["action"],
                data=data.get("data"),
            )
            await self._notify_subscribers(notif)

        await conn.add_listener(channel, _on_notification)
        self._listening_templates.add(template)

    # ------------------------------------------------------------------
    # FactStore interface
    # ------------------------------------------------------------------

    async def assert_fact(self, template: str, data: dict[str, Any]) -> str:
        """Assert a fact and return its unique fact_id."""
        assert self._pool is not None, "call connect() first"
        fact_id = uuid.uuid4().hex
        fact_uuid = uuid.UUID(fact_id)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(_INSERT_SQL, fact_uuid, template, json.dumps(data))
                notification = FactChangeNotification(
                    template=template, fact_id=fact_id, action="assert", data=data
                )
                await self._notify_pg(conn, template, notification)
        except (FleetError, FleetConnectionError):
            raise
        except OSError as exc:
            raise FleetConnectionError(
                f"Connection failed during assert_fact: {exc}",
                backend="postgres",
            ) from exc
        except asyncpg.PostgresError as exc:
            raise FleetError(
                f"PostgreSQL error during assert_fact: {exc}",
            ) from exc
        await self._notify_subscribers(notification)
        return fact_id

    async def query(
        self, template: str, fact_filter: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Return facts matching the template and optional filter."""
        assert self._pool is not None, "call connect() first"
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(_SELECT_SQL, template)
        except OSError as exc:
            raise FleetConnectionError(
                f"Connection failed during query: {exc}",
                backend="postgres",
            ) from exc
        except asyncpg.PostgresError as exc:
            raise FleetError(
                f"PostgreSQL error during query: {exc}",
            ) from exc
        results: list[dict[str, Any]] = []
        for row in rows:
            raw = row["data"]
            row_data: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else dict(raw)
            if self._matches(row_data, fact_filter):
                results.append({"fact_id": row["id"].hex, **row_data})
        return results

    async def retract(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Retract facts matching the template and optional filter. Return count removed."""
        assert self._pool is not None, "call connect() first"
        try:
            if fact_filter:
                # With a filter we must check each row in Python
                matching = await self.query(template, fact_filter)
                if not matching:
                    return 0
                ids = [uuid.UUID(m["fact_id"]) for m in matching]
                async with self._pool.acquire() as conn:
                    deleted = await conn.execute(
                        "DELETE FROM fleet_facts WHERE id = ANY($1::uuid[])", ids
                    )
                    for m in matching:
                        notif = FactChangeNotification(
                            template=template,
                            fact_id=m["fact_id"],
                            action="retract",
                            data={k: v for k, v in m.items() if k != "fact_id"},
                        )
                        await self._notify_pg(conn, template, notif)
                        await self._notify_subscribers(notif)
                # deleted is e.g. "DELETE 3"
                return int(str(deleted).split()[-1]) if deleted else 0
            else:
                # No filter — delete all for template
                async with self._pool.acquire() as conn:
                    rows = await conn.fetch(_DELETE_SQL, template)
                    count = 0
                    for row in rows:
                        row_data: dict[str, Any] = (
                            json.loads(row["data"])
                            if isinstance(row["data"], str)
                            else dict(row["data"])
                        )
                        notif = FactChangeNotification(
                            template=template,
                            fact_id=row["id"].hex,
                            action="retract",
                            data=row_data,
                        )
                        await self._notify_pg(conn, template, notif)
                        await self._notify_subscribers(notif)
                        count += 1
                return count
        except (FleetError, FleetConnectionError):
            raise
        except OSError as exc:
            raise FleetConnectionError(
                f"Connection failed during retract: {exc}",
                backend="postgres",
            ) from exc
        except asyncpg.PostgresError as exc:
            raise FleetError(
                f"PostgreSQL error during retract: {exc}",
            ) from exc

    async def count(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Count facts matching the template and optional filter."""
        assert self._pool is not None, "call connect() first"
        if fact_filter:
            # Must filter in Python
            matching = await self.query(template, fact_filter)
            return len(matching)
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(_COUNT_SQL, template)
        except OSError as exc:
            raise FleetConnectionError(
                f"Connection failed during count: {exc}",
                backend="postgres",
            ) from exc
        except asyncpg.PostgresError as exc:
            raise FleetError(
                f"PostgreSQL error during count: {exc}",
            ) from exc
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
