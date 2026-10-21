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
    from redis.exceptions import TimeoutError as RedisTimeoutError
except ImportError as _exc:
    raise ImportError(
        "redis is required for Redis fleet store. Install it with: pip install fathom-rules[fleet]"
    ) from _exc

from fathom.errors import FleetConnectionError, FleetError
from fathom.fleet import _dispatch
from fathom.models import FactChangeNotification

# Retry configuration for transient Redis failures
_MAX_RETRIES = 3
_BASE_DELAY = 0.1  # seconds; delays: 0.1, 0.3, 0.9

# ponytail: fixed cap on each change stream; make it a parameter if a
# subscriber ever needs to replay further back than this.
_STREAM_MAXLEN = 10_000

# Each write is one script, so the fact and its change notification land
# together or not at all; Redis runs a script without interleaving other
# clients. The XADD goes first: if it is refused (NOPERM, WRONGTYPE) nothing
# has been written yet.
# KEYS: fact hash, index set, stream. ARGV: fact_id, ttl or "", maxlen,
# template, data JSON, then the hash's field/value pairs.
_ASSERT_LUA = """
local id = redis.call('XADD', KEYS[3], 'MAXLEN', '~', ARGV[3], '*',
    'template', ARGV[4], 'fact_id', ARGV[1], 'action', 'assert', 'data', ARGV[5])
local r = redis.pcall('HSET', KEYS[1], unpack(ARGV, 6))
if type(r) ~= 'table' then r = redis.pcall('SADD', KEYS[2], ARGV[1]) end
if type(r) ~= 'table' and ARGV[2] ~= '' then r = redis.pcall('EXPIRE', KEYS[1], ARGV[2]) end
if type(r) == 'table' then
    redis.pcall('SREM', KEYS[2], ARGV[1])
    redis.call('DEL', KEYS[1])
    redis.call('XDEL', KEYS[3], id)
    return r
end
return 1
"""

# Retracts one fact if it still exists. Returns 1 if this call removed it, so
# concurrent retracts of the same fact count and announce it once.
# KEYS: fact hash, index set, stream. ARGV: fact_id, maxlen, template, data JSON.
_RETRACT_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
redis.call('XADD', KEYS[3], 'MAXLEN', '~', ARGV[2], '*',
    'template', ARGV[3], 'fact_id', ARGV[1], 'action', 'retract', 'data', ARGV[4])
redis.call('DEL', KEYS[1])
redis.pcall('SREM', KEYS[2], ARGV[1])
return 1
"""

# Callback type alias
_SubscriptionCallback = Callable[[FactChangeNotification], Coroutine[Any, Any, None]]


__all__ = ["RedisFactStore"]


class RedisFactStore:
    """Redis-backed implementation of :class:`~fathom.fleet.FactStore`.

    Facts are stored as Redis hashes with keys ``fathom:{template}:{fact_id}``.
    Change notifications are published via Redis Streams at
    ``fathom:changes:{template}``. Install with
    ``pip install fathom-rules[fleet]``.

    The client connects lazily on first use; there is no ``connect()``.
    Call :meth:`close` when done.

    Each write runs as one Lua script, so a fact and its stream entry are
    stored together or not at all. Concurrent retracts of the same fact
    count and announce it once.

    :meth:`subscribe` starts a listener task that reads the stream, so a
    callback runs after the write commits, also in the writing process. A
    subscription sees no history: it delivers every change made after
    :meth:`subscribe` returns, and none from before. Each stream is capped
    at about 10000 entries (``MAXLEN ~``).

    Connection errors and timeouts are retried up to 3 attempts (0.1s, then
    0.3s apart) and then raise :class:`~fathom.errors.FleetConnectionError`.
    Any other Redis error (NOPERM, WRONGTYPE) raises
    :class:`~fathom.errors.FleetError` at once. A retry after a lost reply
    can repeat a write, and with it its notification.

    With *ttl*, each fact hash expires after *ttl* seconds. An expired fact
    drops out of :meth:`query` and :meth:`count` (its index entry is pruned
    on the next read), and expiry sends no ``retract`` notification. The
    stream cap is not tied to the TTL.

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
        self._assert_script = self._client.register_script(_ASSERT_LUA)
        self._retract_script = self._client.register_script(_RETRACT_LUA)

    # ------------------------------------------------------------------
    # Retry helper
    # ------------------------------------------------------------------

    async def _retry(self, operation: str, coro_factory: Callable[[], Any]) -> Any:
        """Execute a Redis operation, retrying connection loss and timeouts.

        Any other Redis error (NOPERM, WRONGTYPE, a script error) cannot
        succeed on retry and raises :class:`FleetError` at once.

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
            except (RedisConnectionError, RedisTimeoutError) as exc:
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
                raise FleetError(f"Redis operation {operation} failed: {exc}") from exc
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

    def _matches(self, data: dict[str, Any], fact_filter: dict[str, Any] | None) -> bool:
        """Return True if *data* satisfies every key/value pair in *fact_filter*."""
        if not fact_filter:
            return True
        return all(data.get(k) == v for k, v in fact_filter.items())

    @staticmethod
    def _encode_fields(data: dict[str, Any]) -> dict[str, str]:
        """JSON-encode every slot value so reads round-trip to the written type."""
        return {k: json.dumps(v) for k, v in data.items()}

    @staticmethod
    def _decode_fields(raw_data: dict[Any, Any]) -> dict[str, Any]:
        """Inverse of :meth:`_encode_fields` for one Redis hash."""
        data: dict[str, Any] = {}
        for rk, rv in raw_data.items():
            field = rk.decode() if isinstance(rk, bytes) else rk
            val_str = rv.decode() if isinstance(rv, bytes) else rv
            try:
                data[field] = json.loads(val_str)
            except (json.JSONDecodeError, TypeError):
                # Written by a pre-0.8 release that stored strings unencoded.
                data[field] = val_str
        return data

    # ------------------------------------------------------------------
    # FactStore interface
    # ------------------------------------------------------------------

    async def assert_fact(self, template: str, data: dict[str, Any]) -> str:
        """Assert a fact, store as Redis hash, and return the fact_id."""
        fact_id = uuid.uuid4().hex
        key = self._fact_key(template, fact_id)
        # Store each field as a hash entry; every value is JSON-encoded so the
        # decode in query()/retract() is symmetric and type-preserving.
        fields = [item for pair in self._encode_fields(data).items() for item in pair]
        keys = [key, self._index_key(template), self._stream_key(template)]
        ttl = "" if self._ttl is None else str(self._ttl)
        args: list[str | int] = [fact_id, ttl, _STREAM_MAXLEN, template, json.dumps(data), *fields]
        await self._retry("assert_fact", lambda: self._assert_script(keys=keys, args=args))
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
                data = self._decode_fields(raw_data)
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
                data = self._decode_fields(raw_data)
                if self._matches(data, fact_filter):
                    removed += await self._retract_script(
                        keys=[key, index_key, self._stream_key(template)],
                        args=[fid, _STREAM_MAXLEN, template, json.dumps(data)],
                    )
            return removed

        result: int = await self._retry("retract", _do_retract)
        return result

    async def count(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Count facts matching the template and optional filter.

        Counts what :meth:`query` would return. The unfiltered path used to
        answer ``SCARD`` on the index set, which outlives the hashes it points
        at: once the TTL expired a fact, ``query`` no longer returned it while
        ``count`` still counted it -- and quota and capacity checks read
        ``count``. Reading through ``query`` also prunes those index entries.
        """
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
        # Read on from the stream's last entry as of now, not from "$": "$"
        # means "after whatever is last when XREAD runs", so a change landing
        # before the listener's first read, or between two idle reads, was lost.
        last: Any = await self._retry(
            "subscribe", lambda: self._client.xrevrange(stream_key, count=1)
        )
        start_id = last[0][0] if last else "0-0"

        async def _listener() -> None:
            last_id = start_id
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
                        await _dispatch([callback], notification)

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
