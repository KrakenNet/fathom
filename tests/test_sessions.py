"""Unit tests for the shared REST/gRPC session store."""

from __future__ import annotations

import os
import threading
import time

import pytest

from fathom.integrations.sessions import (
    SessionLimitError,
    SessionRulesetMismatchError,
    SessionStore,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
EXAMPLE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "examples",
    "01-hello-allow-deny",
)


class TestRulesetBinding:
    """A session is bound to the ruleset it was created with."""

    def test_same_ruleset_reuses_engine(self) -> None:
        store = SessionStore()
        first = store.get_or_create("s1", FIXTURES_DIR)
        second = store.get_or_create("s1", FIXTURES_DIR)
        assert first is second

    def test_different_ruleset_is_rejected(self) -> None:
        """The S2 confusion: a second ruleset under a live session id."""
        store = SessionStore()
        store.get_or_create("s1", FIXTURES_DIR)
        with pytest.raises(SessionRulesetMismatchError):
            store.get_or_create("s1", EXAMPLE_DIR)

    def test_rejected_mismatch_leaves_session_intact(self) -> None:
        store = SessionStore()
        engine = store.get_or_create("s1", FIXTURES_DIR)
        with pytest.raises(SessionRulesetMismatchError):
            store.get_or_create("s1", EXAMPLE_DIR)
        assert store.get_or_create("s1", FIXTURES_DIR) is engine


class TestBounds:
    """TTL eviction and the max_sessions ceiling."""

    def test_expired_session_is_evicted(self) -> None:
        store = SessionStore(ttl_seconds=0)
        first = store.get_or_create("s1", FIXTURES_DIR)
        time.sleep(0.01)
        assert store.get_or_create("s1", FIXTURES_DIR) is not first

    def test_expired_session_is_gone_from_get(self) -> None:
        store = SessionStore(ttl_seconds=0)
        store.get_or_create("s1", FIXTURES_DIR)
        time.sleep(0.01)
        assert store.get("s1") is None
        assert len(store) == 0

    def test_ceiling_rejects_new_sessions(self) -> None:
        store = SessionStore(max_sessions=2)
        store.get_or_create("s1", FIXTURES_DIR)
        store.get_or_create("s2", FIXTURES_DIR)
        with pytest.raises(SessionLimitError):
            store.get_or_create("s3", FIXTURES_DIR)

    def test_ceiling_still_serves_live_sessions(self) -> None:
        store = SessionStore(max_sessions=1)
        engine = store.get_or_create("s1", FIXTURES_DIR)
        assert store.get_or_create("s1", FIXTURES_DIR) is engine

    def test_expiry_frees_ceiling_slots(self) -> None:
        store = SessionStore(ttl_seconds=0, max_sessions=1)
        store.get_or_create("s1", FIXTURES_DIR)
        time.sleep(0.01)
        assert store.get_or_create("s2", FIXTURES_DIR) is not None


class TestThreadSafety:
    """gRPC calls the store from pool threads; REST from the threadpool."""

    def test_concurrent_get_or_create_returns_one_engine(self) -> None:
        store = SessionStore()
        engines: list[object] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def worker() -> None:
            try:
                barrier.wait()
                engines.append(store.get_or_create("shared", FIXTURES_DIR))
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(engines) == 8
        assert len({id(e) for e in engines}) == 1
        assert len(store) == 1

    def test_concurrent_creates_never_overshoot_the_ceiling(self) -> None:
        store = SessionStore(max_sessions=3)
        rejected: list[BaseException] = []
        barrier = threading.Barrier(10)

        def worker(index: int) -> None:
            barrier.wait()
            try:
                store.get_or_create(f"s{index}", FIXTURES_DIR)
            except SessionLimitError as exc:
                rejected.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(store) == 3
        assert len(rejected) == 7
