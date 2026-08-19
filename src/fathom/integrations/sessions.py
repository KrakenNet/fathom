"""Shared session store for the REST and gRPC transports.

Both transports keep one :class:`~fathom.engine.Engine` per caller-supplied
``session_id`` so working memory can accumulate across requests. The store
lives here — rather than once per transport module — so the two surfaces can
never drift apart on bounds, eviction, or ruleset binding.

Rejections are raised as transport-neutral exceptions; each transport maps
them to its own status code (REST 503/409, gRPC ``RESOURCE_EXHAUSTED`` /
``FAILED_PRECONDITION``).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fathom.metrics import MetricsCollector

if TYPE_CHECKING:
    from fathom.engine import Engine

# A session holds a compiled CLIPS environment (~1.7 MB of RSS each), so
# both bounds are load-bearing: without them a caller who picks a fresh
# session_id per request leaks until the process is OOM-killed.
DEFAULT_TTL_SECONDS = 1800
DEFAULT_MAX_SESSIONS = 1000


class SessionError(Exception):
    """Base class for session-store rejections."""


class SessionLimitError(SessionError):
    """Raised when the store already holds ``max_sessions`` live sessions."""


class SessionNotFoundError(SessionError):
    """Raised when a ruleset-less call names a session that does not exist.

    Sessions are created only by the call that carries a ruleset to bind to
    (``POST /v1/evaluate`` / the ``Evaluate`` RPC). Auto-creating one from a
    ruleset-less call would bind it to the empty ruleset, permanently
    wedging that id against every later ruleset-carrying request.
    """


class SessionRulesetMismatchError(SessionError):
    """Raised when a live session is addressed with a different ruleset.

    A session is bound to the ruleset it was created with. Answering a
    request that names ruleset B out of a session created for ruleset A
    would evaluate the request under the wrong policy, so the store
    refuses instead of silently reusing the bound Engine.
    """


@dataclass
class _Session:
    """One live session: its Engine, the ruleset it is bound to, and its age."""

    engine: Engine
    rules_path: str
    last_access: float


class SessionStore:
    """Bounded, thread-safe map of ``session_id`` to :class:`Engine`.

    Args:
        ttl_seconds: Idle lifetime of a session. Expired sessions are
            reclaimed lazily on the next store access.
        max_sessions: Ceiling on live sessions. Creating one past the
            ceiling raises :class:`SessionLimitError`.

    The lock is held across Engine construction so a burst of concurrent
    requests for the same new ``session_id`` compiles the ruleset once and
    the ceiling is never overshot. gRPC calls this from pool threads.
    """

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        self._sessions: dict[str, _Session] = {}
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._lock = threading.Lock()
        # One shared collector, not one per Engine: ``fathom_sessions_active``
        # describes the store, not any single session. Set (not inc/dec) from
        # the live dict so the gauge cannot drift out of step with reality.
        self._metrics = MetricsCollector()

    def _record_session_count(self) -> None:
        """Publish the live session count. Caller must hold ``self._lock``."""
        self._metrics.set_sessions_active(len(self._sessions))

    def _cleanup_expired(self) -> None:
        """Remove idle-expired sessions. Caller must hold ``self._lock``."""
        now = time.time()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if now - session.last_access > self._ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            self._record_session_count()

    def get_or_create(self, session_id: str, rules_path: str = "") -> Engine:
        """Return the Engine bound to *session_id*, creating it if needed.

        Raises:
            SessionRulesetMismatchError: The session exists but was created for a
                different ruleset.
            SessionLimitError: The store is already at ``max_sessions``.
        """
        from fathom.engine import Engine

        with self._lock:
            self._cleanup_expired()

            session = self._sessions.get(session_id)
            if session is not None:
                if session.rules_path != rules_path:
                    raise SessionRulesetMismatchError(
                        "session is bound to a different ruleset",
                    )
                session.last_access = time.time()
                return session.engine

            if len(self._sessions) >= self._max_sessions:
                raise SessionLimitError("Maximum session limit reached")

            engine = Engine.from_rules(rules_path) if rules_path else Engine()
            self._sessions[session_id] = _Session(engine, rules_path, time.time())
            self._record_session_count()
            return engine

    def get(self, session_id: str) -> Engine | None:
        """Return the Engine for a live session, or ``None``.

        Refreshes the idle timer on a hit so an actively-used session is
        not reclaimed mid-conversation.
        """
        with self._lock:
            self._cleanup_expired()
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.last_access = time.time()
            return session.engine

    def clear(self) -> None:
        """Drop every session (used by tests and process shutdown)."""
        with self._lock:
            self._sessions.clear()
            self._record_session_count()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
