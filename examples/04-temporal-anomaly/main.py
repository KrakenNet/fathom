"""Example 04 — Temporal Anomaly Detection.

Detects suspicious access patterns over a sliding window of working memory.
This is the kind of stateful reasoning that policy engines like OPA/Cedar
cannot do — Fathom's working memory persists between evaluations within a
session, so rules can match across many facts and across time.

Demonstrates:
- Templates with ``ttl:`` so old facts auto-retract via cleanup_expired()
- Temporal operators: ``rate_exceeds``, ``distinct_count``
- Multiple evaluations against an evolving fact base
- Using ``escalate`` as a third decision channel (not just allow/deny)

Run:
    uv run python examples/04-temporal-anomaly/main.py
"""

from __future__ import annotations

import time
from pathlib import Path

from fathom import Engine

HERE = Path(__file__).parent


def make_engine() -> Engine:
    engine = Engine()
    engine.load_templates(str(HERE / "templates"))
    engine.load_modules(str(HERE / "modules"))
    engine.load_rules(str(HERE / "rules"))
    return engine


def assert_login(engine: Engine, user: str, ip: str, outcome: str) -> None:
    engine.assert_fact(
        "login_attempt",
        {"user": user, "ip": ip, "outcome": outcome, "ts": time.time()},
    )


def assert_session_action(engine: Engine, user: str, action: str) -> None:
    engine.assert_fact(
        "session",
        {"user": user, "action": action, "ts": time.time()},
    )


def show(label: str, engine: Engine) -> None:
    result = engine.evaluate()
    rules = ", ".join(result.rule_trace) if result.rule_trace else "<none>"
    print(
        f"  [{label:<28}] {result.decision:<8} rules=[{rules}] "
        f"reason={result.reason or '(default)'}"
    )


def scenario_brute_force() -> None:
    print("\nScenario A — Brute-force detection (5 failed logins in <30s):")
    engine = make_engine()
    for i in range(5):
        assert_login(engine, "alice", "10.0.0.1", "failure")
        show(f"after failure #{i + 1}", engine)


def scenario_account_sharing() -> None:
    print("\nScenario B — Account sharing (3 successful logins, 3 IPs):")
    engine = make_engine()
    assert_login(engine, "bob", "10.0.0.10", "success")
    show("login from 10.0.0.10", engine)
    assert_login(engine, "bob", "192.168.1.50", "success")
    show("login from 192.168.1.50", engine)
    assert_login(engine, "bob", "203.0.113.99", "success")
    show("login from 203.0.113.99", engine)


def scenario_export_burst() -> None:
    print("\nScenario C — Session export burst (10 exports in <10s):")
    engine = make_engine()
    for i in range(10):
        assert_session_action(engine, "carol", "export")
        if i in (0, 4, 9):
            show(f"after export #{i + 1}", engine)


def scenario_normal_traffic() -> None:
    print("\nScenario D — Normal traffic (single login, single export):")
    engine = make_engine()
    assert_login(engine, "dave", "10.0.0.5", "success")
    show("single successful login", engine)
    assert_session_action(engine, "dave", "export")
    show("single export action", engine)


def main() -> None:
    print("Fathom — Example 04: Temporal Anomaly Detection")

    scenario_brute_force()
    scenario_account_sharing()
    scenario_export_burst()
    scenario_normal_traffic()

    print("\nNotes:")
    print("  - login_attempt has ttl: 60 — call engine._fact_manager.cleanup_expired()")
    print("    to drop facts older than 60s. In production this would run on a timer.")
    print("  - Working memory is the differentiator: each new fact updates the")
    print("    detection state. Stateless engines (OPA/Cedar) cannot do this.")


if __name__ == "__main__":
    main()
