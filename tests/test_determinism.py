"""The determinism claim, asserted directly.

``pyproject.toml`` calls this a "Deterministic reasoning runtime" and lists
``deterministic`` among its keywords, but every test in the repo matching
/determinis/ was about documentation generation. Nothing checked that the
engine returns the same answer twice.

Determinism here means three separate things, and each gets its own test:

1. **Repetition** — the same facts evaluated again give the same decision,
   reason, and traces.
2. **Order independence** — the order the caller asserts facts in does not
   reach the result. CLIPS agenda ordering is salience-then-recency, so
   assertion order is exactly the input a rules engine could plausibly leak.
3. **Instance independence** — two engines built from the same rules agree,
   so the answer is a property of the ruleset and not of one engine's history.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from fathom.engine import Engine

if TYPE_CHECKING:
    from pathlib import Path

    from fathom.models import EvaluationResult

# SSVC's CISA tree: four inputs, one published decision. Used as the
# real-pack counterpart to the synthetic fixture, because a pack with 144
# rules across a decision tree is where ordering effects would actually show.
SSVC_FACTS: list[tuple[str, dict[str, Any]]] = [
    ("exploitation", {"value": "active"}),
    ("automatable", {"value": "yes"}),
    ("technical_impact", {"value": "total"}),
    ("mission_wellbeing", {"value": "high"}),
]


def _fingerprint(result: EvaluationResult) -> tuple[Any, ...]:
    """Everything about a result that is supposed to be reproducible.

    ``duration_us`` and ``attestation_token`` are deliberately excluded: the
    first is a measurement and the second binds a timestamp.
    """
    return (
        result.decision,
        result.reason,
        tuple(result.rule_trace),
        tuple(result.module_trace),
        tuple(sorted(result.metadata.items())),
    )


@pytest.fixture
def pack(tmp_path: Path) -> Path:
    """A pack whose rules all match, so the traces are non-trivial.

    Three rules at three saliences across two modules: the decision and both
    traces depend on firing order, which is what makes this fixture able to
    detect non-determinism at all. A single-rule pack would pass by accident.
    """
    root = tmp_path / "pack"
    (root / "templates").mkdir(parents=True)
    (root / "modules").mkdir()
    (root / "rules").mkdir()

    (root / "templates" / "t.yaml").write_text(
        yaml.safe_dump(
            {
                "templates": [
                    {
                        "name": "request",
                        "slots": [
                            {"name": "action", "type": "symbol"},
                            {"name": "user", "type": "symbol"},
                        ],
                    },
                    {
                        "name": "context",
                        "slots": [{"name": "env", "type": "symbol"}],
                    },
                    {
                        "name": "subject",
                        "slots": [{"name": "role", "type": "symbol"}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    (root / "modules" / "modules.yaml").write_text(
        yaml.safe_dump(
            {
                "modules": [
                    {"name": "triage", "description": "Runs first"},
                    {"name": "governance", "description": "Runs second"},
                ],
                "focus_order": ["triage", "governance"],
            }
        ),
        encoding="utf-8",
    )

    (root / "rules" / "triage.yaml").write_text(
        yaml.safe_dump(
            {
                "module": "triage",
                "rules": [
                    {
                        "name": "note-environment",
                        "salience": 30,
                        "when": [
                            {
                                "template": "context",
                                "conditions": [{"slot": "env", "expression": "equals(prod)"}],
                            }
                        ],
                        "then": {"action": "allow", "reason": "production request seen"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    (root / "rules" / "governance.yaml").write_text(
        yaml.safe_dump(
            {
                "module": "governance",
                "rules": [
                    {
                        "name": "operator-may-read",
                        "salience": 20,
                        "when": [
                            {
                                "template": "request",
                                "conditions": [{"slot": "action", "expression": "equals(read)"}],
                            },
                            {
                                "template": "subject",
                                "conditions": [{"slot": "role", "expression": "equals(operator)"}],
                            },
                        ],
                        "then": {"action": "allow", "reason": "operator read"},
                    },
                    {
                        "name": "deny-unreviewed-prod",
                        "salience": 10,
                        "when": [
                            {
                                "template": "context",
                                "conditions": [{"slot": "env", "expression": "equals(prod)"}],
                            },
                            {
                                "template": "request",
                                "conditions": [{"slot": "action", "expression": "equals(read)"}],
                            },
                        ],
                        "then": {"action": "deny", "reason": "unreviewed production read"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


FACTS: list[tuple[str, dict[str, Any]]] = [
    ("request", {"action": "read", "user": "alice"}),
    ("context", {"env": "prod"}),
    ("subject", {"role": "operator"}),
]


def _evaluate(pack: Path, facts: list[tuple[str, dict[str, Any]]]) -> EvaluationResult:
    engine = Engine.from_rules(str(pack))
    for template, data in facts:
        engine.assert_fact(template, data)
    return engine.evaluate()


class TestRepetition:
    def test_evaluate_once_repeats_identically(self, pack: Path) -> None:
        """Five calls, one engine. ``evaluate_once`` is the request-scoped path."""
        engine = Engine.from_rules(str(pack))
        results = [_fingerprint(engine.evaluate_once(FACTS)) for _ in range(5)]
        assert len(set(results)) == 1, f"evaluate_once drifted across calls: {results}"
        # A fixture whose rules never fire would satisfy the line above
        # vacuously.
        assert results[0][2], "no rules fired — the fixture is not exercising anything"

    def test_evaluate_once_repeats_identically_on_a_real_pack(self) -> None:
        engine = Engine()
        engine.load_pack("ssvc")
        results = [_fingerprint(engine.evaluate_once(SSVC_FACTS)) for _ in range(3)]
        assert len(set(results)) == 1, f"ssvc drifted across calls: {results}"
        assert results[0][0] == "route"


class TestOrderIndependence:
    def test_assertion_order_does_not_reach_the_result(self, pack: Path) -> None:
        """All 6 orderings of the 3 facts, each on its own engine.

        CLIPS breaks salience ties by recency, so assertion order is the
        input most likely to leak into a rules engine's output.
        """
        seen = {
            _fingerprint(_evaluate(pack, list(order))) for order in itertools.permutations(FACTS)
        }
        assert len(seen) == 1, f"assertion order changed the result: {seen}"

    def test_assertion_order_does_not_reach_the_result_on_a_real_pack(self) -> None:
        """Forward and reversed, on the SSVC CISA tree.

        Not the full 24 permutations: each one needs its own engine, and a
        144-rule pack compiled two dozen times is a minute of CI for a
        weaker signal than the exhaustive synthetic case above.
        """
        fingerprints = set()
        for order in (SSVC_FACTS, list(reversed(SSVC_FACTS))):
            engine = Engine()
            engine.load_pack("ssvc")
            for template, data in order:
                engine.assert_fact(template, data)
            fingerprints.add(_fingerprint(engine.evaluate()))
        assert len(fingerprints) == 1, f"ssvc depended on assertion order: {fingerprints}"


class TestInstanceIndependence:
    def test_two_engines_from_the_same_pack_agree(self, pack: Path) -> None:
        """The answer must be a property of the ruleset, not of one engine."""
        first = _fingerprint(_evaluate(pack, FACTS))
        second = _fingerprint(_evaluate(pack, FACTS))
        assert first == second

    def test_two_engines_over_a_real_pack_agree(self) -> None:
        fingerprints = set()
        for _ in range(2):
            engine = Engine()
            engine.load_pack("ssvc")
            for template, data in SSVC_FACTS:
                engine.assert_fact(template, data)
            fingerprints.add(_fingerprint(engine.evaluate()))
        assert len(fingerprints) == 1, f"two ssvc engines disagreed: {fingerprints}"
