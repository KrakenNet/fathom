"""Request-scoped evaluation boundary — ``Engine.evaluate_once`` (C5).

``evaluate()`` keeps its cumulative semantics: facts survive the call and
CLIPS refraction suppresses activations that already fired, so a deny
followed by an allow on the same engine reports ``allow`` while the
top-secret request is still live in working memory. ``evaluate_once``
is the boundary that makes an independent authorization decision.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fathom.engine import Engine
from fathom.errors import ScopeError

if TYPE_CHECKING:
    from pathlib import Path

RULES = "examples/01-hello-allow-deny"

AGENT = ("agent", {"id": "a1", "clearance": "secret"})
REQ_TOP_SECRET = (
    "data_request",
    {"agent_id": "a1", "classification": "top-secret", "resource": "x"},
)
REQ_SECRET = (
    "data_request",
    {"agent_id": "a1", "classification": "secret", "resource": "x"},
)


def test_evaluate_still_accumulates() -> None:
    """evaluate() is unchanged: facts persist across calls (documented behaviour)."""
    engine = Engine.from_rules(RULES)
    engine.assert_fact(*AGENT)
    engine.assert_fact(*REQ_TOP_SECRET)
    engine.evaluate()
    assert engine.count("data_request") == 1


def test_evaluate_once_leaves_no_facts_behind() -> None:
    engine = Engine.from_rules(RULES)
    engine.evaluate_once([AGENT, REQ_TOP_SECRET])
    assert engine.count("agent") == 0
    assert engine.count("data_request") == 0


def test_evaluate_once_is_history_independent() -> None:
    """The C5 reproduction: deny then allow then deny, on one engine."""
    engine = Engine.from_rules(RULES)
    assert engine.evaluate_once([AGENT, REQ_TOP_SECRET]).decision == "deny"
    assert engine.evaluate_once([AGENT, REQ_SECRET]).decision == "allow"
    assert engine.evaluate_once([AGENT, REQ_TOP_SECRET]).decision == "deny"


def test_evaluate_once_repeats_the_same_rule_trace() -> None:
    """Refraction must not suppress the second identical call."""
    engine = Engine.from_rules(RULES)
    first = engine.evaluate_once([AGENT, REQ_TOP_SECRET])
    second = engine.evaluate_once([AGENT, REQ_TOP_SECRET])
    assert first.rule_trace == second.rule_trace
    assert first.rule_trace == ["governance::deny-top-secret-for-secret"]


def test_evaluate_once_matches_a_fresh_engine() -> None:
    """Same facts, same decision — whatever the engine evaluated before."""
    used = Engine.from_rules(RULES)
    used.evaluate_once([AGENT, REQ_SECRET])
    used.evaluate_once([AGENT, REQ_TOP_SECRET])

    fresh = Engine.from_rules(RULES)
    assert (
        used.evaluate_once([AGENT, REQ_SECRET]).decision
        == fresh.evaluate_once([AGENT, REQ_SECRET]).decision
        == "allow"
    )


def test_evaluate_once_preserves_pre_existing_facts() -> None:
    """Only the facts this call supplied are withdrawn."""
    engine = Engine.from_rules(RULES)
    engine.assert_fact("agent", {"id": "long-lived", "clearance": "top-secret"})
    engine.evaluate_once([REQ_TOP_SECRET])
    assert engine.query("agent") == [{"id": "long-lived", "clearance": "top-secret"}]
    assert engine.count("data_request") == 0


def test_evaluate_once_withdraws_facts_even_when_evaluation_raises(
    tmp_path: Path,
) -> None:
    """A failing evaluation must not leak the request facts into working memory."""
    (tmp_path / "templates.yaml").write_text(
        "templates:\n  - name: t\n    slots:\n      - name: n\n        type: integer\n"
    )
    (tmp_path / "modules.yaml").write_text(
        "modules:\n  - name: m\n    priority: 100\nfocus_order: [m]\n"
    )
    (tmp_path / "rules.yaml").write_text(
        "ruleset: r\nmodule: m\nrules:\n"
        "  - name: loop\n    when:\n      - template: t\n"
        '        conditions:\n          - slot: n\n            bind: "?n"\n'
        "    then:\n      action: allow\n      reason: ok\n"
        '      assert:\n        - template: t\n          slots:\n            n: "(+ ?n 1)"\n'
    )
    engine = Engine.from_rules(str(tmp_path), run_limit=500)
    with pytest.raises(Exception, match="run_limit"):
        engine.evaluate_once([("t", {"n": 0})])
    # The caller-supplied fact is gone; only rule-asserted facts remain.
    assert not any(row == {"n": 0} for row in engine.query("t"))


def test_evaluate_once_rejects_fleet_scoped_templates(tmp_path: Path) -> None:
    (tmp_path / "templates.yaml").write_text(
        "templates:\n  - name: t\n    scope: fleet\n"
        "    slots:\n      - name: n\n        type: integer\n"
    )
    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    with pytest.raises(ScopeError):
        engine.evaluate_once([("t", {"n": 1})])


class TestBudgetExhaustionLeavesNoFactsBehind:
    """A 503'd request must not permanently cost the session ~run_limit facts.

    A ruleset whose rules re-trigger themselves asserts up to `run_limit`
    facts before the budget stops it. Retracting only the caller's own
    handles left every one of those in the session's working memory, so a
    caller who can provoke the error repeatedly grows the server without
    bound. The request produced no decision, so nothing it created is worth
    keeping.
    """

    SELF_TRIGGERING = {
        "templates": ("templates:\n  - name: ctr\n    slots:\n      - {name: n, type: integer}\n"),
        "modules": "modules:\n  - name: gov\n\nfocus_order:\n  - gov\n",
        "rules": (
            "module: gov\n"
            "ruleset: loop\n"
            "rules:\n"
            "  - name: grow\n"
            "    when:\n"
            "      - template: ctr\n"
            "        conditions:\n"
            "          - slot: n\n"
            "            bind: ?n\n"
            "    then:\n"
            "      action: allow\n"
            "      reason: x\n"
            "      asserts:\n"
            "        - template: ctr\n"
            '          slots: {n: "(+ ?n 1)"}\n'
        ),
    }

    def _pack(self, tmp_path: Path) -> Path:
        root = tmp_path / "loop"
        for sub, content in self.SELF_TRIGGERING.items():
            (root / sub).mkdir(parents=True)
            (root / sub / f"{sub}.yaml").write_text(content)
        return root

    def test_working_memory_is_empty_after_the_budget_is_exhausted(self, tmp_path: Path) -> None:
        from fathom.errors import EvaluationLimitError

        engine = Engine.from_rules(str(self._pack(tmp_path)), run_limit=5_000)

        for _ in range(3):
            with pytest.raises(EvaluationLimitError):
                engine.evaluate_once([("ctr", {"n": 0})])
            assert engine.count("ctr") == 0
        assert engine.all_facts() == []

    def test_facts_a_caller_already_held_survive(self, tmp_path: Path) -> None:
        """Only what the failed run created is dropped, not pre-existing state."""
        from fathom.errors import EvaluationLimitError

        engine = Engine.from_rules(str(self._pack(tmp_path)), run_limit=5_000)
        engine.assert_fact("ctr", {"n": -1})

        with pytest.raises(EvaluationLimitError):
            engine.evaluate_once([("ctr", {"n": 0})])

        assert engine.query("ctr") == [{"n": -1}]
