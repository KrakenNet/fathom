"""Hypothesis property-based tests for working memory."""

from __future__ import annotations

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from fathom.engine import Engine

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

keys = st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L", "N")))
values = st.integers(min_value=0, max_value=1000)
categories = st.sampled_from(["alpha", "beta", "gamma", "delta"])

_TEMPLATE_YAML = """\
templates:
  - name: test_item
    slots:
      - name: key
        type: string
        required: true
      - name: value
        type: integer
        default: 0
      - name: category
        type: symbol
        default: default
"""


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class WorkingMemoryMachine(RuleBasedStateMachine):
    """Property-based state machine for working memory operations."""

    @initialize()
    def setup(self):
        self.engine = Engine()

        # Write template YAML to a temp file and load it.
        import os
        import tempfile  # noqa: E401

        fd, path = tempfile.mkstemp(suffix=".yaml")
        try:
            os.write(fd, _TEMPLATE_YAML.encode())
            os.close(fd)
            self.engine.load_templates(path)
        finally:
            os.unlink(path)

        # Track expected facts as a set of (key, value, category) tuples.
        # CLIPS deduplicates identical facts so we use a set.
        self.expected_facts: set[tuple[str, int, str]] = set()

    @rule(key=keys, value=values, category=categories)
    def assert_random_fact(self, key: str, value: int, category: str):
        """Assert a random valid fact into working memory."""
        self.engine.assert_fact("test_item", {"key": key, "value": value, "category": category})
        self.expected_facts.add((key, value, category))

    @rule()
    def retract_all(self):
        """Retract all test_item facts."""
        self.engine.retract("test_item")
        self.expected_facts.clear()

    @rule()
    def evaluate(self):
        """Run evaluation and verify it returns a result."""
        result = self.engine.evaluate()
        assert result is not None

    @rule()
    def query_all(self):
        """Query all test_item facts and verify they are a subset of expected."""
        facts = self.engine.query("test_item")
        # Every fact returned must correspond to something we asserted.
        for fact in facts:
            key_tuple = (fact["key"], int(fact["value"]), str(fact["category"]))
            assert key_tuple in self.expected_facts

    @invariant()
    def fact_count_matches(self):
        """CLIPS deduplicates identical facts, so count <= expected set size."""
        count = self.engine.count("test_item")
        assert count <= len(self.expected_facts)

    @invariant()
    def fact_count_non_negative(self):
        """Fact count must never be negative."""
        count = self.engine.count("test_item")
        assert count >= 0


# ---------------------------------------------------------------------------
# Persistence across evaluations
# ---------------------------------------------------------------------------


class PersistenceAcrossEvaluations(RuleBasedStateMachine):
    """Facts persist across evaluate() calls unless explicitly retracted."""

    @initialize()
    def setup(self):
        self.engine = Engine()

        import os
        import tempfile  # noqa: E401

        fd, path = tempfile.mkstemp(suffix=".yaml")
        try:
            os.write(fd, _TEMPLATE_YAML.encode())
            os.close(fd)
            self.engine.load_templates(path)
        finally:
            os.unlink(path)

        self.expected_facts: set[tuple[str, int, str]] = set()
        self.eval_count = 0

    @rule(key=keys, value=values, category=categories)
    def assert_fact(self, key: str, value: int, category: str):
        self.engine.assert_fact("test_item", {"key": key, "value": value, "category": category})
        self.expected_facts.add((key, value, category))

    @rule()
    def evaluate_and_check_persistence(self):
        """Evaluate and verify facts survive."""
        self.engine.evaluate()
        self.eval_count += 1
        count_after = self.engine.count("test_item")
        # Facts must still be present after evaluation.
        assert count_after <= len(self.expected_facts)
        # If we asserted anything at all, at least one fact should remain.
        if self.expected_facts:
            assert count_after >= 1

    @invariant()
    def count_within_bounds(self):
        count = self.engine.count("test_item")
        assert 0 <= count <= len(self.expected_facts)


# ---------------------------------------------------------------------------
# Deny overrides allow at same salience
# ---------------------------------------------------------------------------

_DENY_ALLOW_TEMPLATE_YAML = """\
templates:
  - name: request
    slots:
      - name: action
        type: symbol
        required: true
"""

_DENY_ALLOW_MODULES_YAML = """\
modules:
  - name: governance
    description: "Governance rules"
focus_order:
  - governance
"""

_DENY_RULE_YAML = """\
module: governance

rules:
  - name: deny_all
    salience: 10
    when:
      - template: request
        conditions:
          - slot: action
            expression: "equals(access)"
    then:
      action: deny
      reason: "denied by deny_all"
"""

_ALLOW_RULE_YAML = """\
module: governance

rules:
  - name: allow_all
    salience: 100
    when:
      - template: request
        conditions:
          - slot: action
            expression: "equals(access)"
    then:
      action: allow
      reason: "allowed by allow_all"
"""


class DenyOverridesAllow(RuleBasedStateMachine):
    """Deny rules override allow rules via last-write-wins (fail-closed design).

    In CLIPS, higher salience fires first. The evaluator uses last-write-wins
    to pick the winning decision. Deny rules with lower salience fire after
    allow rules, ensuring deny overwrites allow. This verifies the evaluator's
    last-write-wins conflict resolution with the default deny convention.
    """

    @initialize()
    def setup(self):
        self.engine = Engine(default_decision="deny")

        import os
        import tempfile  # noqa: E401

        # Load templates
        fd, path = tempfile.mkstemp(suffix=".yaml")
        try:
            os.write(fd, _DENY_ALLOW_TEMPLATE_YAML.encode())
            os.close(fd)
            self.engine.load_templates(path)
        finally:
            os.unlink(path)

        # Load modules (required before rules)
        fd, path = tempfile.mkstemp(suffix=".yaml")
        try:
            os.write(fd, _DENY_ALLOW_MODULES_YAML.encode())
            os.close(fd)
            self.engine.load_modules(path)
        finally:
            os.unlink(path)

        # Load deny rule first (gets higher priority in CLIPS at same salience)
        fd, path = tempfile.mkstemp(suffix=".yaml")
        try:
            os.write(fd, _DENY_RULE_YAML.encode())
            os.close(fd)
            self.engine.load_rules(path)
        finally:
            os.unlink(path)

        # Load allow rule second
        fd, path = tempfile.mkstemp(suffix=".yaml")
        try:
            os.write(fd, _ALLOW_RULE_YAML.encode())
            os.close(fd)
            self.engine.load_rules(path)
        finally:
            os.unlink(path)

        self.fact_asserted = False

    @rule()
    def assert_access_request(self):
        if not self.fact_asserted:
            self.engine.assert_fact("request", {"action": "access"})
            self.fact_asserted = True

    @rule()
    def evaluate_and_check_deny(self):
        """When deny has lower salience than allow, deny fires last and wins."""
        if self.fact_asserted:
            result = self.engine.evaluate()
            # Allow rule has salience 100 (fires first), deny has 10
            # (fires last).  Evaluator uses last-write-wins, so deny
            # overwrites allow.
            assert result.decision == "deny", (
                f"Expected deny but got: {result.decision} ({result.reason})"
            )
            # Retract request so rules can fire again on next assertion.
            self.engine.retract("request")
            self.fact_asserted = False

    @invariant()
    def default_is_deny(self):
        """Engine default decision is always deny."""
        assert self.engine._default_decision == "deny"


# ---------------------------------------------------------------------------
# Test cases — instantiated from state machines
# ---------------------------------------------------------------------------

TestWorkingMemory = WorkingMemoryMachine.TestCase
TestWorkingMemory.settings = settings(max_examples=50, stateful_step_count=30)

TestPersistence = PersistenceAcrossEvaluations.TestCase
TestPersistence.settings = settings(max_examples=50, stateful_step_count=20)

TestDenyOverrides = DenyOverridesAllow.TestCase
TestDenyOverrides.settings = settings(max_examples=50, stateful_step_count=15)
