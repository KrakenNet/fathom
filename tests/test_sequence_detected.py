"""Tests for fathom_sequence_detected temporal operator (H3)."""

from __future__ import annotations

import json
import time

import pytest

from fathom.engine import Engine


@pytest.fixture
def engine_with_events() -> Engine:
    e = Engine()
    # Two templates with *different* timestamp slot names.
    e._safe_build(
        "(deftemplate login (slot user (type STRING)) (slot occurred_at (type FLOAT)))",
        context="login",
    )
    e._safe_build(
        "(deftemplate admin_action "
        "(slot user (type STRING)) (slot ts (type FLOAT)))",
        context="admin_action",
    )
    return e


def test_sequence_uses_custom_timestamp_slot(engine_with_events: Engine) -> None:
    e = engine_with_events
    now = time.time()
    e._env.assert_string(f'(login (user "alice") (occurred_at {now - 10}))')
    e._env.assert_string(f'(admin_action (user "alice") (ts {now - 5}))')

    events = [
        {"template": "login", "slot": "user", "value": "alice", "slot_ts": "occurred_at"},
        {"template": "admin_action", "slot": "user", "value": "alice", "slot_ts": "ts"},
    ]
    result = e._env.eval(
        f'(fathom-sequence-detected "{json.dumps(events).replace(chr(34), chr(92)+chr(34))}" 60)'
    )
    assert str(result) == "TRUE"


def test_sequence_considers_all_matching_facts(
    engine_with_events: Engine,
) -> None:
    """If the first candidate doesn't yield an ordered sequence, try the next."""
    e = engine_with_events
    now = time.time()
    # First login is *after* admin action — bad. Second login is before — good.
    e._env.assert_string(f'(login (user "alice") (occurred_at {now - 1}))')
    e._env.assert_string(f'(admin_action (user "alice") (ts {now - 5}))')
    e._env.assert_string(f'(login (user "alice") (occurred_at {now - 10}))')

    events = [
        {"template": "login", "slot": "user", "value": "alice", "slot_ts": "occurred_at"},
        {"template": "admin_action", "slot": "user", "value": "alice", "slot_ts": "ts"},
    ]
    payload = json.dumps(events).replace(chr(34), chr(92) + chr(34))
    result = e._env.eval(f'(fathom-sequence-detected "{payload}" 60)')
    assert str(result) == "TRUE"
