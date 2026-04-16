"""RedisFactStore — Redis-backed implementation of the FactStore protocol."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

try:
    import redis.asyncio as aioredis
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import RedisError
except ImportError as _exc:
    raise ImportError(
        "redis is required for Redis fleet store. Install it with: pip install fathom-rules[fleet]"
    ) from _exc

from fathom.errors import FleetConnectionError, FleetError
from fathom.models import FactChangeNotification

# Retry configuration for transient Redis failures
_MAX_RETRIES = 3
_BASE_DELAY = 0.1  # seconds; delays: 0.1, 0.3, 0.9

# Callback type alias
_SubscriptionCallback = Callable[[FactChangeNotification], Coroutine[Any, Any, None]]


class RedisFactStore:
    """Redis-backed implementation of :class:`~fathom.fleet.FactStore`.

    Facts are stored as Redis hashes with keys ``fathom:{template}:{fact_id}``.
    Change notifications are published via Redis Streams at
    ``fathom:changes:{template}``.

    Parameters
    ----------
    host:
        Redis server hostname.
    port:
        Redis server port.
    db:
        Redis database index.
    password:
        Optional authentication password.
    ssl:
        Whether to use TLS for the connection.
    ttl:
        Optional default TTL in seconds applied to every fact key via EXPIRE.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        ssl: bool = False,
        ttl: int | None = None,
    ) -> None:
        self._client = aioredis.Redis(host=host, port=port, db=db, password=password, ssl=ssl)
        self._ttl = ttl
        self._subscriber_tasks: list[asyncio.Task[None]] = []

    # ------------------------------------------------------------------
    # Retry helper
    # ------------------------------------------------------------------

    async def _retry(self, operation: str, coro_factory: Callable[[], Any]) -> Any:
        """Execute a Redis operation with exponential backoff retry.

        Parameters
        ----------
        operation:
            Human-readable label for error messages (e.g. ``"assert_fact"``).
        coro_factory:
            A zero-arg callable that returns an awaitable Redis operation.
            Called fresh on each attempt so the coroutine is not reused.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await coro_factory()
            except RedisConnectionError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (3**attempt)
                    await asyncio.sleep(delay)
                    continue
                raise FleetConnectionError(
                    f"Redis connection failed during {operation} after "
                    f"{_MAX_RETRIES} attempts: {exc}",
                    backend="redis",
                ) from exc
            except RedisError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (3**attempt)
                    await asyncio.sleep(delay)
                    continue
                raise FleetError(
                    f"Redis operation {operation} failed after {_MAX_RETRIES} attempts: {exc}",
                ) from exc
        # Should not reach here, but satisfy type checker
        raise FleetError(  # pragma: no cover
            f"Redis operation {operation} failed: {last_exc}"
        )

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fact_key(template: str, fact_id: str) -> str:
        return f"fathom:{template}:{fact_id}"

    @staticmethod
    def _stream_key(template: str) -> str:
        return f"fathom:changes:{template}"

    @staticmethod
    def _index_key(template: str) -> str:
        """Set key that tracks all fact_ids for a given template."""
        return f"fathom:index:{template}"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _publish_change(
        self, template: str, fact_id: str, action: str, data: dict[str, Any] | None
    ) -> None:
        """Publish a change notification to the Redis Stream."""
        payload: dict[str, str] = {
            "template": template,
            "fact_id": fact_id,
            "action": action,
        }
        if data is not None:
            payload["data"] = json.dumps(data)
        await self._retry(
            "publish_change",
            lambda: self._client.xadd(self._stream_key(template), payload),  # type: ignore[arg-type]
        )

    def _matches(self, data: dict[str, Any], fact_filter: dict[str, Any] | None) -> bool:
        """Return True if *data* satisfies every key/value pair in *fact_filter*."""
        if not fact_filter:
            return True
        return all(data.get(k) == v for k, v in fact_filter.items())

    # ------------------------------------------------------------------
    # FactStore interface
    # ------------------------------------------------------------------

    async def assert_fact(self, template: str, data: dict[str, Any]) -> str:
        """Assert a fact, store as Redis hash, and return the fact_id."""
        fact_id = uuid.uuid4().hex
        key = self._fact_key(template, fact_id)
        # Store each field as a hash entry; complex values are JSON-encoded
        mapping: dict[str, str] = {}
        for k, v in data.items():
            mapping[k] = json.dumps(v) if not isinstance(v, str) else v

        async def _do_assert() -> None:
            await self._client.hset(key, mapping=mapping)  # type: ignore[misc]
            await self._client.sadd(self._index_key(template), fact_id)  # type: ignore[misc]
            if self._ttl is not None:
                await self._client.expire(key, self._ttl)

        await self._retry("assert_fact", _do_assert)
        # Publish change notification
        await self._publish_change(template, fact_id, "assert", data)
        return fact_id

    async def query(
        self, template: str, fact_filter: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Return facts matching the template and optional filter."""
        index_key = self._index_key(template)

        async def _do_query() -> list[dict[str, Any]]:
            fact_ids = await self._client.smembers(index_key)  # type: ignore[misc]
            results: list[dict[str, Any]] = []
            for raw_fid in fact_ids:
                fid = raw_fid.decode() if isinstance(raw_fid, bytes) else raw_fid
                key = self._fact_key(template, fid)
                raw_data = await self._client.hgetall(key)  # type: ignore[misc]
                if not raw_data:
                    # Key expired or was deleted; clean up index
                    await self._client.srem(index_key, fid)  # type: ignore[misc]
                    continue
                data: dict[str, Any] = {}
                for rk, rv in raw_data.items():
                    field = rk.decode() if isinstance(rk, bytes) else rk
                    val_str = rv.decode() if isinstance(rv, bytes) else rv
                    try:
                        data[field] = json.loads(val_str)
                    except (json.JSONDecodeError, TypeError):
                        data[field] = val_str
                if self._matches(data, fact_filter):
                    results.append({"fact_id": fid, **data})
            return results

        result: list[dict[str, Any]] = await self._retry("query", _do_query)
        return result

    async def retract(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Retract facts matching the template and optional filter. Return count removed."""
        index_key = self._index_key(template)

        async def _do_retract() -> int:
            fact_ids = await self._client.smembers(index_key)  # type: ignore[misc]
            removed = 0
            for raw_fid in fact_ids:
                fid = raw_fid.decode() if isinstance(raw_fid, bytes) else raw_fid
                key = self._fact_key(template, fid)
                raw_data = await self._client.hgetall(key)  # type: ignore[misc]
                if not raw_data:
                    await self._client.srem(index_key, fid)  # type: ignore[misc]
                    continue
                data: dict[str, Any] = {}
                for rk, rv in raw_data.items():
                    field = rk.decode() if isinstance(rk, bytes) else rk
                    val_str = rv.decode() if isinstance(rv, bytes) else rv
                    try:
                        data[field] = json.loads(val_str)
                    except (json.JSONDecodeError, TypeError):
                        data[field] = val_str
                if self._matches(data, fact_filter):
                    await self._client.delete(key)
                    await self._client.srem(index_key, fid)  # type: ignore[misc]
                    await self._publish_change(template, fid, "retract", data)
                    removed += 1
            return removed

        result: int = await self._retry("retract", _do_retract)
        return result

    async def count(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Count facts matching the template and optional filter."""
        if not fact_filter:
            count_result: int = await self._retry(
                "count",
                lambda: self._client.scard(self._index_key(template)),
            )
            return count_result
        # With a filter we must inspect each fact
        facts = await self.query(template, fact_filter)
        return len(facts)

    async def subscribe(
        self,
        template: str,
        callback: _SubscriptionCallback,
    ) -> Callable[[], None]:
        """Subscribe to changes on a template via Redis Streams.

        Returns an unsubscribe callable that cancels the listener task.
        """
        stream_key = self._stream_key(template)
        stop_event = asyncio.Event()

        async def _listener() -> None:
            last_id = "$"
            while not stop_event.is_set():
                try:
                    entries: Any = await self._client.xread(
                        {stream_key: last_id}, count=10, block=1000
                    )
                except Exception:  # noqa: BLE001
                    if stop_event.is_set():
                        break
                    await asyncio.sleep(0.5)
                    continue
                if not entries:
                    continue
                for _stream_name, messages in entries:
                    for msg_id, fields in messages:
                        mid = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                        last_id = mid
                        tmpl = fields.get(b"template", fields.get("template", b""))
                        if isinstance(tmpl, bytes):
                            tmpl = tmpl.decode()
                        fid = fields.get(b"fact_id", fields.get("fact_id", b""))
                        if isinstance(fid, bytes):
                            fid = fid.decode()
                        action = fields.get(b"action", fields.get("action", b""))
                        if isinstance(action, bytes):
                            action = action.decode()
                        raw_data = fields.get(b"data", fields.get("data"))
                        parsed_data: dict[str, Any] | None = None
                        if raw_data is not None:
                            raw_str = (
                                raw_data.decode() if isinstance(raw_data, bytes) else raw_data
                            )
                            try:
                                parsed_data = json.loads(raw_str)
                            except (json.JSONDecodeError, TypeError):
                                parsed_data = None
                        notification = FactChangeNotification(
                            template=tmpl,
                            fact_id=fid,
                            action=action,
                            data=parsed_data,
                        )
                        await callback(notification)

        task = asyncio.create_task(_listener())
        self._subscriber_tasks.append(task)

        def unsubscribe() -> None:
            stop_event.set()
            task.cancel()

        return unsubscribe

    async def close(self) -> None:
        """Close the Redis connection and cancel subscriber tasks."""
        for task in self._subscriber_tasks:
            task.cancel()
        self._subscriber_tasks.clear()
        try:
            await self._client.aclose()
        except RedisConnectionError as exc:
            raise FleetConnectionError(
                f"Failed to close Redis connection: {exc}",
                backend="redis",
            ) from exc
        except RedisError as exc:
            raise FleetError(
                f"Error closing Redis connection: {exc}",
            ) from exc
