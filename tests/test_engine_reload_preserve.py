"""Reload that carries working memory — ``preserve_facts=True`` (#243).

A reload compiles onto a fresh :class:`clips.Environment`, which is what
makes it atomic and what makes it lose every fact. That is the right trade
for a policy server, which re-asserts session state per request, and the
wrong one for an engine holding state a caller cannot reconstruct. These
tests pin both halves: the default still discards, and the flag carries the
facts *and* their TTL ages across.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import yaml

from fathom.engine import Engine

if TYPE_CHECKING:
    from pathlib import Path


def _write_pack(tmp_path: Path) -> None:
    (tmp_path / "templates.yaml").write_text(
        "templates:\n"
        "  - name: agent\n"
        "    slots:\n"
        "      - name: id\n"
        "        type: symbol\n"
        "  - name: session\n"
        "    ttl: 60\n"
        "    slots:\n"
        "      - name: id\n"
        "        type: symbol\n"
    )
    (tmp_path / "modules.yaml").write_text(
        "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"
    )


def _ruleset_yaml(rule_name: str, subject: str) -> bytes:
    return yaml.safe_dump(
        {
            "ruleset": f"rs-{rule_name}",
            "module": "gov",
            "rules": [
                {
                    "name": rule_name,
                    "when": [
                        {
                            "template": "agent",
                            "conditions": [{"slot": "id", "expression": f"equals({subject})"}],
                        },
                    ],
                    "then": {"action": "allow", "reason": f"{rule_name} ok"},
                },
            ],
        }
    ).encode("utf-8")


def _engine(tmp_path: Path) -> Engine:
    _write_pack(tmp_path)
    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    engine.load_modules(str(tmp_path / "modules.yaml"))
    # No initial rules: reload_rules is a rule-only swap, and every test here
    # asserts against the ruleset the reload brings in.
    return engine


def test_default_still_discards_working_memory(tmp_path: Path) -> None:
    """The documented default, unchanged."""
    engine = _engine(tmp_path)
    engine.assert_fact("agent", {"id": "a1"})
    engine.reload_rules(_ruleset_yaml("r2", "a1"))
    assert engine.count("agent") == 0


def test_preserve_facts_carries_them_over(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.assert_fact("agent", {"id": "a1"})
    engine.assert_fact("agent", {"id": "a2"})
    engine.reload_rules(_ruleset_yaml("r2", "a1"), preserve_facts=True)
    assert {row["id"] for row in engine.query("agent")} == {"a1", "a2"}


def test_the_new_rules_match_the_carried_facts(tmp_path: Path) -> None:
    """The reason to carry them: the incoming ruleset decides on them."""
    engine = _engine(tmp_path)
    engine.assert_fact("agent", {"id": "a2"})
    engine.reload_rules(_ruleset_yaml("r2", "a2"), preserve_facts=True)
    assert engine.evaluate().decision == "allow"


def test_ttl_age_survives_the_reload(tmp_path: Path) -> None:
    """Without re-keying, a carried fact would silently restart its TTL."""
    engine = _engine(tmp_path)
    engine.assert_fact("session", {"id": "s1"})
    aged = time.time() - 3600
    engine._fact_manager._fact_timestamps = dict.fromkeys(
        engine._fact_manager._fact_timestamps, aged
    )
    engine.reload_rules(_ruleset_yaml("r2", "a1"), preserve_facts=True)
    assert engine.count("session") == 1
    # The TTL is 60s and the fact is an hour old, so the next evaluation
    # expires it. A restored-but-restamped fact would survive here.
    engine.evaluate()
    assert engine.count("session") == 0


def test_a_fresh_fact_is_not_expired_by_the_carry(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.assert_fact("session", {"id": "s1"})
    engine.reload_rules(_ruleset_yaml("r2", "a1"), preserve_facts=True)
    engine.evaluate()
    assert engine.count("session") == 1


def test_carrying_facts_does_not_notify_listeners(tmp_path: Path) -> None:
    """Subscribers already hold these facts; a burst of asserts would be a lie."""
    engine = _engine(tmp_path)
    engine.assert_fact("agent", {"id": "a1"})
    seen: list[tuple[str, str]] = []
    engine.subscribe(lambda template, action, _data: seen.append((template, action)))
    engine.reload_rules(_ruleset_yaml("r2", "a1"), preserve_facts=True)
    assert seen == []


def test_hashes_still_bracket_the_swap(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.assert_fact("agent", {"id": "a1"})
    before, after = engine.reload_rules(_ruleset_yaml("r2", "a1"), preserve_facts=True)
    assert before != after
    assert after == engine.ruleset_hash


def test_decision_facts_are_not_carried(tmp_path: Path) -> None:
    """__fathom_decision is per-evaluation bookkeeping, not working memory."""
    engine = _engine(tmp_path)
    engine.assert_fact("agent", {"id": "a1"})
    engine.evaluate()
    engine.reload_rules(_ruleset_yaml("r2", "a1"), preserve_facts=True)
    facts = engine._env.find_template("__fathom_decision").facts()
    assert list(facts) == []
