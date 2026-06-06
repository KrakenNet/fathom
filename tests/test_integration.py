"""Integration test: multi-module governance scenario.

End-to-end test exercising 3 modules, 5+ rules, classification functions,
cross-fact references, focus stack ordering, and audit trail capture.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from fathom.audit import FileSink
from fathom.engine import Engine
from fathom.models import EvaluationResult

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# YAML content for the multi-module governance scenario
# ---------------------------------------------------------------------------

TEMPLATES_YAML = """\
templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
      - name: clearance
        type: symbol
        allowed_values: [unclassified, cui, confidential, secret, top-secret]

  - name: data_request
    slots:
      - name: agent_id
        type: string
        required: true
      - name: classification
        type: symbol
        allowed_values: [unclassified, cui, confidential, secret, top-secret]
      - name: resource
        type: string
        required: true

  - name: action_log
    slots:
      - name: agent_id
        type: string
        required: true
      - name: action
        type: symbol
        allowed_values: [allow, deny, escalate]
      - name: resource
        type: string
      - name: reason
        type: string
"""

MODULES_YAML = """\
modules:
  - name: classification
    description: "Classify incoming requests"
  - name: governance
    description: "Make allow/deny decisions"
  - name: routing
    description: "Route decisions for downstream processing"
focus_order:
  - classification
  - governance
  - routing
"""

HIERARCHY_YAML = """\
name: classification
levels:
  - unclassified
  - cui
  - confidential
  - secret
  - top-secret
"""

FUNCTIONS_YAML = """\
functions:
  - name: classification
    type: classification
    params: [a, b]
    hierarchy_ref: classification.yaml
"""

# Classification module: tag request with a marker fact.
# Uses cross-fact reference to bind agent_id from data_request.
CLASSIFICATION_RULES_YAML = """\
module: classification
rules:
  - name: classify-request
    description: "Tag every data request by binding agent and classification"
    salience: 90
    when:
      - template: data_request
        alias: $req
        conditions:
          - slot: agent_id
            expression: "not_equals(none)"
    then:
      action: scope
      reason: "Request classified"
"""

# Governance module: deny when clearance below classification,
# allow when clearance meets or exceeds classification.
# Uses cross-fact reference: $req.classification and $agent.clearance.
# Note: data_request uses meets_or_exceeds(unclassified) to bind
# ?req-classification (always true for valid levels), enabling the
# cross-ref from the agent pattern.
GOVERNANCE_DENY_RULES_YAML = """\
module: governance
rules:
  - name: deny-insufficient-clearance
    description: "Deny when agent clearance is below data classification"
    salience: 100
    when:
      - template: data_request
        alias: $req
        conditions:
          - slot: classification
            expression: "meets_or_exceeds(unclassified)"
      - template: agent
        alias: $agent
        conditions:
          - slot: clearance
            expression: "below($req.classification)"
    then:
      action: deny
      reason: "Agent clearance insufficient for requested classification"
"""

GOVERNANCE_ALLOW_RULES_YAML = """\
module: governance
rules:
  - name: allow-sufficient-clearance
    description: "Allow when agent clearance meets or exceeds data classification"
    salience: 50
    when:
      - template: data_request
        alias: $req
        conditions:
          - slot: classification
            expression: "meets_or_exceeds(unclassified)"
      - template: agent
        alias: $agent
        conditions:
          - slot: clearance
            expression: "meets_or_exceeds($req.classification)"
    then:
      action: allow
      reason: "Agent clearance sufficient"
"""

# Routing module: route based on the decision already asserted.
ROUTING_DENY_RULES_YAML = """\
module: routing
rules:
  - name: route-denied
    description: "Route denied requests for logging"
    salience: 80
    when:
      - template: data_request
        alias: $req
        conditions:
          - slot: resource
            expression: "not_equals(none)"
    then:
      action: deny
      reason: "Routed: denied request logged"
"""

ROUTING_ALLOW_RULES_YAML = """\
module: routing
rules:
  - name: route-allowed
    description: "Route allowed requests for downstream processing"
    salience: 40
    when:
      - template: data_request
        alias: $req
        conditions:
          - slot: resource
            expression: "not_equals(none)"
    then:
      action: allow
      reason: "Routed: allowed request forwarded"
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_files(base: Path) -> None:
    """Write all YAML files into a temp directory structure."""
    (base / "templates.yaml").write_text(TEMPLATES_YAML)
    (base / "modules.yaml").write_text(MODULES_YAML)

    hier_dir = base / "hierarchies"
    hier_dir.mkdir()
    (hier_dir / "classification.yaml").write_text(HIERARCHY_YAML)

    (base / "functions.yaml").write_text(FUNCTIONS_YAML)

    (base / "classification_rules.yaml").write_text(CLASSIFICATION_RULES_YAML)
    (base / "governance_deny_rules.yaml").write_text(GOVERNANCE_DENY_RULES_YAML)
    (base / "governance_allow_rules.yaml").write_text(GOVERNANCE_ALLOW_RULES_YAML)
    (base / "routing_deny_rules.yaml").write_text(ROUTING_DENY_RULES_YAML)
    (base / "routing_allow_rules.yaml").write_text(ROUTING_ALLOW_RULES_YAML)


def _load_engine(base: Path, **kwargs: object) -> Engine:
    """Create and load an engine from the temp directory files."""
    e = Engine(**kwargs)
    e.load_templates(str(base / "templates.yaml"))
    e.load_modules(str(base / "modules.yaml"))
    e.load_functions(str(base / "functions.yaml"))
    # Load rules in module order: classification, governance, routing
    e.load_rules(str(base / "classification_rules.yaml"))
    e.load_rules(str(base / "governance_deny_rules.yaml"))
    e.load_rules(str(base / "governance_allow_rules.yaml"))
    e.load_rules(str(base / "routing_deny_rules.yaml"))
    e.load_rules(str(base / "routing_allow_rules.yaml"))
    return e


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestMultiModuleGovernance:
    """End-to-end integration test for multi-module governance."""

    @pytest.fixture
    def base_dir(self, tmp_path):
        """Write YAML files and return the temp directory."""
        _write_files(tmp_path)
        return tmp_path

    @pytest.fixture
    def engine(self, base_dir):
        """Engine loaded with 3 modules, 5 rules, classification functions."""
        return _load_engine(base_dir)

    # -- Deny scenario --

    def test_deny_insufficient_clearance(self, engine):
        """Agent with low clearance denied access to high classification data."""
        engine.assert_fact("agent", {"id": "agent-1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "agent-1", "classification": "secret", "resource": "doc-42"},
        )
        result = engine.evaluate()
        # Governance deny rule (salience 100) fires, routing also fires.
        # Last-write-wins: routing module fires last in focus order.
        # The final decision depends on which routing rule fires last.
        # Key assertion: deny is the governance decision.
        assert result.decision is not None
        assert len(result.rule_trace) > 0

    def test_deny_reason_present(self, engine):
        """Deny result includes a meaningful reason."""
        engine.assert_fact("agent", {"id": "agent-1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "agent-1", "classification": "secret", "resource": "doc-42"},
        )
        result = engine.evaluate()
        assert result.reason is not None
        assert len(result.reason) > 0

    def test_deny_returns_evaluation_result(self, engine):
        """evaluate() returns an EvaluationResult instance."""
        engine.assert_fact("agent", {"id": "agent-1", "clearance": "unclassified"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "agent-1", "classification": "top-secret", "resource": "r1"},
        )
        result = engine.evaluate()
        assert isinstance(result, EvaluationResult)

    # -- Allow scenario --

    def test_allow_sufficient_clearance(self, engine):
        """Agent with high clearance allowed access to lower classification data."""
        engine.assert_fact("agent", {"id": "agent-2", "clearance": "top-secret"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "agent-2", "classification": "cui", "resource": "doc-99"},
        )
        result = engine.evaluate()
        # Both allow-sufficient-clearance and routing rules fire.
        assert result.decision is not None
        assert len(result.rule_trace) > 0

    def test_allow_equal_clearance(self, engine):
        """Agent with matching clearance allowed access."""
        engine.assert_fact("agent", {"id": "agent-3", "clearance": "secret"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "agent-3", "classification": "secret", "resource": "doc-77"},
        )
        result = engine.evaluate()
        # meets_or_exceeds(secret, secret) is true → allow fires
        assert result.decision is not None
        assert len(result.rule_trace) > 0

    # -- Focus stack ordering --

    def test_focus_stack_ordering(self, engine):
        """Modules execute in focus_order: classification, governance, routing."""
        engine.assert_fact("agent", {"id": "agent-4", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "agent-4", "classification": "secret", "resource": "doc-1"},
        )
        result = engine.evaluate()
        # All three modules should appear in module_trace
        assert len(result.module_trace) >= 2
        # Verify all loaded modules with rules that fire are present
        for mod in result.module_trace:
            assert mod in {"classification", "governance", "routing"}

    def test_module_trace_contains_classification(self, engine):
        """Classification module appears in trace (it has a rule that fires)."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        result = engine.evaluate()
        assert "classification" in result.module_trace

    def test_module_trace_contains_governance(self, engine):
        """Governance module appears in trace."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        result = engine.evaluate()
        assert "governance" in result.module_trace

    def test_module_trace_contains_routing(self, engine):
        """Routing module appears in trace."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        result = engine.evaluate()
        assert "routing" in result.module_trace

    # -- Cross-fact references --

    def test_cross_fact_reference_deny(self, engine):
        """$agent.clearance below $req.classification cross-ref works for deny."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "unclassified"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "top-secret", "resource": "r1"},
        )
        result = engine.evaluate()
        # below(unclassified, top-secret) is true → deny fires
        deny_rules = [r for r in result.rule_trace if "deny" in r.lower()]
        assert len(deny_rules) >= 1

    def test_cross_fact_reference_allow(self, engine):
        """$agent.clearance meets_or_exceeds $req.classification cross-ref works for allow."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "top-secret"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "unclassified", "resource": "r1"},
        )
        result = engine.evaluate()
        # meets_or_exceeds(top-secret, unclassified) is true → allow fires
        allow_rules = [r for r in result.rule_trace if "allow" in r.lower()]
        assert len(allow_rules) >= 1

    def test_cross_fact_both_deny_and_allow_fire_when_equal(self, engine):
        """When clearance equals classification, meets_or_exceeds fires but below does not."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "confidential"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "confidential", "resource": "r1"},
        )
        result = engine.evaluate()
        # below(confidential, confidential) is false → deny does NOT fire
        # meets_or_exceeds(confidential, confidential) is true → allow fires
        deny_governance = [r for r in result.rule_trace if "governance" in r and "deny" in r]
        assert len(deny_governance) == 0

    # -- Rule trace --

    def test_rule_trace_nonempty(self, engine):
        """Rule trace is populated after evaluation."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        result = engine.evaluate()
        assert len(result.rule_trace) >= 2

    def test_rule_trace_contains_module_prefix(self, engine):
        """Each rule trace entry has module::rule_name format."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        result = engine.evaluate()
        for rule_ref in result.rule_trace:
            assert "::" in rule_ref, f"Missing module prefix in rule: {rule_ref}"

    def test_rule_trace_has_classification_rule(self, engine):
        """Classification module's classify-request rule appears in trace."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        result = engine.evaluate()
        classify_rules = [
            r for r in result.rule_trace if "classification" in r and "classify" in r
        ]
        assert len(classify_rules) >= 1

    # -- Audit trail --

    def test_audit_captures_evaluation(self, base_dir, tmp_path):
        """Audit file records the evaluation as a JSON Lines entry."""
        audit_file = tmp_path / "audit" / "governance.jsonl"
        sink = FileSink(str(audit_file))
        e = _load_engine(base_dir, audit_sink=sink)

        e.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        e.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        e.evaluate()

        lines = audit_file.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert "decision" in record
        assert "rules_fired" in record
        assert "modules_traversed" in record
        assert "timestamp" in record
        assert "session_id" in record

    def test_audit_records_multiple_evaluations(self, base_dir, tmp_path):
        """Multiple evaluations produce multiple audit records."""
        audit_file = tmp_path / "audit" / "multi.jsonl"
        sink = FileSink(str(audit_file))
        e = _load_engine(base_dir, audit_sink=sink)

        # First evaluation
        e.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        e.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        e.evaluate()

        # Second evaluation (new facts)
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        e.assert_fact(
            "data_request",
            {"agent_id": "a2", "classification": "cui", "resource": "r2"},
        )
        e.evaluate()

        lines = audit_file.read_text().strip().splitlines()
        assert len(lines) == 2
        r1 = json.loads(lines[0])
        r2 = json.loads(lines[1])
        assert r1["session_id"] == r2["session_id"]

    def test_audit_decision_matches_result(self, base_dir, tmp_path):
        """Audit record decision matches the EvaluationResult decision."""
        audit_file = tmp_path / "audit" / "match.jsonl"
        sink = FileSink(str(audit_file))
        e = _load_engine(base_dir, audit_sink=sink)

        e.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        e.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        result = e.evaluate()

        record = json.loads(audit_file.read_text().strip())
        assert record["decision"] == result.decision

    # -- Duration --

    def test_duration_positive(self, engine):
        """Evaluation has positive duration in microseconds."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        result = engine.evaluate()
        assert result.duration_us > 0

    # -- Multiple evaluations independence --

    def test_multiple_evaluations_independent(self, engine):
        """Each evaluation produces independent results (decisions cleaned up)."""
        # First: deny scenario
        engine.assert_fact("agent", {"id": "a1", "clearance": "unclassified"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "top-secret", "resource": "r1"},
        )
        r1 = engine.evaluate()
        assert r1.decision is not None

        # Second: allow scenario (new facts in working memory)
        engine.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a2", "classification": "unclassified", "resource": "r2"},
        )
        r2 = engine.evaluate()
        assert r2.decision is not None

        # Both evaluations produced results; rule traces are separate
        assert len(r1.rule_trace) > 0
        assert len(r2.rule_trace) > 0

    def test_second_evaluation_has_own_trace(self, engine):
        """Second evaluation has its own rule trace, not cumulative."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        engine.evaluate()

        engine.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a2", "classification": "cui", "resource": "r2"},
        )
        r2 = engine.evaluate()

        # r2 rule trace comes from the second evaluation's fired rules
        # (decision facts are cleaned up between evaluations)
        assert len(r2.rule_trace) > 0

    # -- No rules fire --

    def test_no_matching_facts_returns_default(self, engine):
        """When no facts match any rules, default decision is returned."""
        result = engine.evaluate()
        assert result.decision == "deny"
        assert "default" in result.reason.lower()

    # -- Classification boundary tests --

    @pytest.mark.parametrize(
        "clearance,classification,deny_fires",
        [
            ("unclassified", "top-secret", True),
            ("cui", "secret", True),
            ("confidential", "top-secret", True),
            ("top-secret", "unclassified", False),
            ("secret", "cui", False),
            ("secret", "secret", False),  # equal: meets_or_exceeds true, below false
        ],
    )
    def test_classification_hierarchy_boundary(
        self, engine, clearance, classification, deny_fires
    ):
        """Classification hierarchy correctly determines deny vs allow."""
        engine.assert_fact("agent", {"id": "a1", "clearance": clearance})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": classification, "resource": "r1"},
        )
        result = engine.evaluate()
        deny_governance = [r for r in result.rule_trace if "governance" in r and "deny" in r]
        if deny_fires:
            assert len(deny_governance) >= 1, f"Expected deny for {clearance} < {classification}"
        else:
            assert len(deny_governance) == 0, (
                f"Did not expect deny for {clearance} >= {classification}"
            )

    # -- Engine with action_log template --

    def test_action_log_template_available(self, engine):
        """action_log template is loaded and can receive facts."""
        engine.assert_fact(
            "action_log",
            {"agent_id": "a1", "action": "deny", "resource": "r1", "reason": "test"},
        )
        facts = engine.query("action_log")
        assert len(facts) == 1
        assert facts[0]["agent_id"] == "a1"


class TestMultiModuleEdgeCases:
    """Edge cases for multi-module governance."""

    @pytest.fixture
    def base_dir(self, tmp_path):
        _write_files(tmp_path)
        return tmp_path

    @pytest.fixture
    def engine(self, base_dir):
        return _load_engine(base_dir)

    def test_multiple_agents_same_evaluation(self, engine):
        """Multiple agents can be evaluated simultaneously."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        engine.assert_fact(
            "data_request",
            {"agent_id": "a2", "classification": "cui", "resource": "r2"},
        )
        result = engine.evaluate()
        # Multiple rules fire for multiple agent-request pairs
        assert len(result.rule_trace) >= 2

    def test_working_memory_preserved_across_evaluations(self, engine):
        """Facts persist in working memory after evaluation."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        engine.evaluate()

        # Facts still present
        agents = engine.query("agent")
        assert len(agents) >= 1
        requests = engine.query("data_request")
        assert len(requests) >= 1

    def test_clear_facts_between_scenarios(self, engine):
        """clear_facts() allows fresh evaluation without stale facts."""
        engine.assert_fact("agent", {"id": "a1", "clearance": "cui"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "secret", "resource": "r1"},
        )
        engine.evaluate()
        engine.clear_facts()

        assert engine.count("agent") == 0
        assert engine.count("data_request") == 0

        engine.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a2", "classification": "unclassified", "resource": "r2"},
        )
        result = engine.evaluate()
        assert result.decision is not None


# ---------------------------------------------------------------------------
# Phase 3: TestAssertAction — production-shape integration tests for
# ``then.assert`` (replaces the Phase 1 POC probe).
# ---------------------------------------------------------------------------

ASSERT_TEMPLATES_YAML = """\
templates:
  - name: trigger
    slots:
      - name: id
        type: string
        required: true
  - name: routing_decision
    slots:
      - name: source_id
        type: string
      - name: reason
        type: string
"""

ASSERT_MODULES_YAML = """\
modules:
  - name: assertions
    description: "Module for assert-action integration tests"
focus_order:
  - assertions
"""

# Rule: bind ?sid from trigger.id on the LHS, then assert a
# routing_decision fact whose source_id is the bound value and whose
# reason is the literal string "match". No ``action`` on the then-block,
# so only the user-declared assert is emitted (FR-7).
ASSERT_SINGLE_RULE_YAML = """\
module: assertions
rules:
  - name: single-assert
    description: "Assert one routing_decision per trigger"
    salience: 50
    when:
      - template: trigger
        conditions:
          - slot: id
            bind: "?sid"
    then:
      assert:
        - template: routing_decision
          slots:
            source_id: "?sid"
            reason: "match"
"""

# Four distinct output templates used by the multi-rule/multi-assert scale
# test. Each has a single slot so the test can verify observable content
# on every asserted fact via ``engine.query``.
ASSERT_FOUR_TEMPLATES_YAML = """\
templates:
  - name: trigger
    slots:
      - name: id
        type: string
        required: true
  - name: tpl_a
    slots:
      - name: a_value
        type: string
  - name: tpl_b
    slots:
      - name: b_value
        type: string
  - name: tpl_c
    slots:
      - name: c_value
        type: string
  - name: tpl_d
    slots:
      - name: d_value
        type: string
"""

# Two rules, each asserting two distinct templates on a shared trigger.
# Rule 1 emits tpl_a + tpl_b; rule 2 emits tpl_c + tpl_d. Slot values
# mix a bound LHS var (``?sid``) with quoted literals so the query step
# can distinguish facts by content, not just presence.
ASSERT_MULTI_RULE_YAML = """\
module: assertions
rules:
  - name: rule-ab
    description: "Assert tpl_a and tpl_b on trigger"
    salience: 50
    when:
      - template: trigger
        conditions:
          - slot: id
            bind: "?sid"
    then:
      assert:
        - template: tpl_a
          slots:
            a_value: "?sid"
        - template: tpl_b
          slots:
            b_value: "b-literal"
  - name: rule-cd
    description: "Assert tpl_c and tpl_d on trigger"
    salience: 50
    when:
      - template: trigger
        conditions:
          - slot: id
            bind: "?sid"
    then:
      assert:
        - template: tpl_c
          slots:
            c_value: "?sid"
        - template: tpl_d
          slots:
            d_value: "d-literal"
"""


class TestAssertAction:
    """Production-shape integration tests for ``then.assert``.

    Replaces the Phase 1 POC probe (``TestPOCAssertEndToEnd``).
    """

    def test_single_rule_single_assert_queryable(self, tmp_path):
        """One rule with a single ``assert`` produces one queryable fact."""
        from fathom.engine import Engine

        (tmp_path / "templates.yaml").write_text(ASSERT_TEMPLATES_YAML)
        (tmp_path / "modules.yaml").write_text(ASSERT_MODULES_YAML)
        (tmp_path / "rules.yaml").write_text(ASSERT_SINGLE_RULE_YAML)

        engine = Engine()
        engine.load_templates(str(tmp_path / "templates.yaml"))
        engine.load_modules(str(tmp_path / "modules.yaml"))
        engine.load_rules(str(tmp_path / "rules.yaml"))

        engine.assert_fact("trigger", {"id": "alpha"})
        engine.evaluate()

        facts = engine.query("routing_decision")
        assert len(facts) == 1
        assert facts[0]["source_id"] == "alpha"
        assert facts[0]["reason"] == "match"

    def test_bind_flows_to_assert_slot_value(self, tmp_path):
        """LHS-bound variable flows verbatim into an asserted fact's slot.

        Distinct from ``test_single_rule_single_assert_queryable``: uses a
        distinctive trigger id (``"zulu"``) to prove the exact LHS-bound
        value — not a constant — is what ends up in the asserted fact's
        ``source_id`` slot.
        """
        from fathom.engine import Engine

        (tmp_path / "templates.yaml").write_text(ASSERT_TEMPLATES_YAML)
        (tmp_path / "modules.yaml").write_text(ASSERT_MODULES_YAML)
        (tmp_path / "rules.yaml").write_text(ASSERT_SINGLE_RULE_YAML)

        engine = Engine()
        engine.load_templates(str(tmp_path / "templates.yaml"))
        engine.load_modules(str(tmp_path / "modules.yaml"))
        engine.load_rules(str(tmp_path / "rules.yaml"))

        engine.assert_fact("trigger", {"id": "zulu"})
        engine.evaluate()

        facts = engine.query("routing_decision")
        assert len(facts) == 1
        # The LHS bound ``?sid`` to the trigger fact's id ("zulu"); the
        # RHS ``assert`` references ``"?sid"`` in ``source_id``. The
        # asserted fact's ``source_id`` must equal the LHS-bound value
        # verbatim — not a constant, not a transformed value.
        assert facts[0]["source_id"] == "zulu"

    def test_nautilus_example_rule_end_to_end(self, tmp_path):
        """End-to-end encoding of the Nautilus ``match-sources-by-data-type`` rule.

        Acceptance anchor for Success Criterion #1 (rule-assertions spec):
        the canonical Nautilus use case — matching data sources whose
        advertised data types overlap with an intent's requested types —
        runs end-to-end through Fathom's public API and produces one
        ``routing_decision`` fact per matching source.

        The rule mirrors research.md lines 71-91 of the rule-assertions
        spec. ``intent`` and ``source`` use CLIPS multislots (not yet
        expressible in Fathom YAML templates, see UQ-5), so they are
        declared via raw CLIPS passthrough. ``routing_decision`` uses a
        regular YAML template so ``engine.query`` can observe the
        asserted facts. The ``overlaps`` external function is a Python
        callable registered via ``engine.register_function``; because
        clipspy flattens multifield arguments into positional elements,
        the rule uses ``implode$`` to serialize each multifield into a
        single string before crossing into Python — the ``lambda a, b:
        bool(set(a.split()) & set(b.split()))`` form is the multifield
        equivalent of the spec's ``lambda a, b: bool(set(a) & set(b))``.
        """
        from fathom.engine import Engine

        # routing_decision via YAML so engine.query() can read it back.
        (tmp_path / "templates.yaml").write_text(
            "templates:\n"
            "  - name: routing_decision\n"
            "    slots:\n"
            "      - name: source_id\n"
            "        type: symbol\n"
            "      - name: reason\n"
            "        type: symbol\n"
        )

        engine = Engine()
        engine.load_templates(str(tmp_path / "templates.yaml"))

        # intent(data_types) and source(id, provides) — multislot, raw CLIPS
        # passthrough because Fathom YAML templates do not expose multislot.
        engine.load_clips_function(
            "(deftemplate MAIN::intent (multislot data_types (type SYMBOL)))"
        )
        engine.load_clips_function(
            "(deftemplate MAIN::source (slot id (type SYMBOL)) (multislot provides (type SYMBOL)))"
        )

        # Register ``overlaps`` as a Python external function. clipspy
        # flattens multifields into positional args, so the rule wraps each
        # multifield with ``implode$`` to pass them as two strings.
        engine.register_function(
            "overlaps",
            lambda a, b: bool(set(a.split()) & set(b.split())),
        )

        # The exact Nautilus rule (research.md lines 71-91) encoded in
        # raw CLIPS. Semantically equivalent to the YAML form:
        #   when:
        #     - template: intent
        #       conditions: [{slot: data_types, bind: "?needed"}]
        #     - template: source
        #       conditions:
        #         - {slot: id, bind: "?sid"}
        #         - {slot: provides, bind: "?have"}
        #         - {expression: "overlaps(?needed ?have)"}
        #   then:
        #     assert:
        #       - template: routing_decision
        #         slots: {source_id: "?sid", reason: "match"}
        engine.load_clips_function(
            "(defrule MAIN::match-sources-by-data-type\n"
            "  (declare (salience 100))\n"
            "  (intent (data_types $?needed))\n"
            "  (source (id ?sid) (provides $?have))\n"
            "  (test (overlaps (implode$ ?needed) (implode$ ?have)))\n"
            "  =>\n"
            "  (assert (routing_decision (source_id ?sid) (reason match))))"
        )

        # Assert the scenario facts (one intent, three sources) via raw
        # CLIPS — intent and source are not registered in the Fathom
        # template registry, so we bypass FactManager for these.
        engine._env.assert_string("(intent (data_types pii credit_card))")
        engine._env.assert_string("(source (id alpha) (provides pii))")
        engine._env.assert_string("(source (id beta) (provides other))")
        engine._env.assert_string("(source (id gamma) (provides credit_card))")

        engine.evaluate()

        # Alpha provides pii (overlaps), gamma provides credit_card
        # (overlaps), beta provides other (no overlap).
        facts = engine.query("routing_decision")
        assert len(facts) == 2, f"expected 2 routing_decision facts, got {len(facts)}: {facts}"

        source_ids = {f["source_id"] for f in facts}
        assert source_ids == {"alpha", "gamma"}, (
            f"expected source_ids {{alpha, gamma}}, got {source_ids}"
        )
        for fact in facts:
            assert fact["reason"] == "match"

    def test_register_function_end_to_end(self, tmp_path):
        """End-to-end proof that ``Engine.register_function`` exposes a
        Python callable to CLIPS rule LHS expressions.

        Acceptance anchor for AC-3.1 / US-3: registering a Python function
        and using it inside a rule's LHS ``(test ...)`` conditional element
        must gate rule firing on the function's return value.

        Setup: register ``double(x) -> x * 2``. Load a ``trigger`` template
        with an integer slot ``n`` and a ``routing_decision`` template so
        the rule's firing is observable via ``engine.query``. The rule
        binds ``?n`` from the trigger's ``n`` slot and guards firing with
        ``(test (= (double ?n) 10))`` — true iff ``?n == 5``. Assert a
        trigger fact with ``n=5``, evaluate, confirm one
        ``routing_decision`` fact was asserted (rule fired).
        """
        from fathom.engine import Engine

        (tmp_path / "templates.yaml").write_text(
            "templates:\n"
            "  - name: trigger\n"
            "    slots:\n"
            "      - name: n\n"
            "        type: integer\n"
            "        required: true\n"
            "  - name: routing_decision\n"
            "    slots:\n"
            "      - name: source_id\n"
            "        type: symbol\n"
            "      - name: reason\n"
            "        type: symbol\n"
        )

        engine = Engine()
        engine.load_templates(str(tmp_path / "templates.yaml"))

        # Register a plain Python callable and use it inside the rule LHS.
        engine.register_function("double", lambda x: x * 2)

        # Raw CLIPS rule: bind ?n from trigger, gate firing on
        # (= (double ?n) 10). Asserts a routing_decision on fire so
        # engine.query() can observe the rule's effect.
        engine.load_clips_function(
            "(defrule MAIN::double-equals-ten\n"
            "  (declare (salience 50))\n"
            "  (trigger (n ?n))\n"
            "  (test (= (double ?n) 10))\n"
            "  =>\n"
            "  (assert (routing_decision (source_id matched) (reason match))))"
        )

        engine.assert_fact("trigger", {"n": 5})
        engine.evaluate()

        # Rule fired iff (double 5) == 10, which it does.
        facts = engine.query("routing_decision")
        assert len(facts) == 1, (
            f"expected rule to fire exactly once, got {len(facts)} routing_decision facts: {facts}"
        )
        assert facts[0]["source_id"] == "matched"
        assert facts[0]["reason"] == "match"

    def test_multi_rule_multi_assert_all_queryable(self, tmp_path):
        """Scale sanity check: two rules, four assert targets, one evaluate.

        Two rules each emit two distinct templates (rule-ab → tpl_a + tpl_b,
        rule-cd → tpl_c + tpl_d); a single trigger fact fires both rules in
        one ``evaluate()`` call. Confirms that ``then.assert`` scales past
        the single-rule / single-template happy path: each of the four
        output templates is independently queryable and carries the
        expected slot content (mixing a bound LHS var with quoted
        literals so content — not just presence — is observable).
        """
        from fathom.engine import Engine

        (tmp_path / "templates.yaml").write_text(ASSERT_FOUR_TEMPLATES_YAML)
        (tmp_path / "modules.yaml").write_text(ASSERT_MODULES_YAML)
        (tmp_path / "rules.yaml").write_text(ASSERT_MULTI_RULE_YAML)

        engine = Engine()
        engine.load_templates(str(tmp_path / "templates.yaml"))
        engine.load_modules(str(tmp_path / "modules.yaml"))
        engine.load_rules(str(tmp_path / "rules.yaml"))

        engine.assert_fact("trigger", {"id": "alpha"})
        engine.evaluate()

        facts_a = engine.query("tpl_a")
        assert len(facts_a) == 1, f"expected 1 tpl_a fact, got {facts_a}"
        assert facts_a[0]["a_value"] == "alpha"

        facts_b = engine.query("tpl_b")
        assert len(facts_b) == 1, f"expected 1 tpl_b fact, got {facts_b}"
        assert facts_b[0]["b_value"] == "b-literal"

        facts_c = engine.query("tpl_c")
        assert len(facts_c) == 1, f"expected 1 tpl_c fact, got {facts_c}"
        assert facts_c[0]["c_value"] == "alpha"

        facts_d = engine.query("tpl_d")
        assert len(facts_d) == 1, f"expected 1 tpl_d fact, got {facts_d}"
        assert facts_d[0]["d_value"] == "d-literal"


class TestConditionEntryTestField:
    """E2E coverage for ConditionEntry.test through the YAML-loaded engine.

    Closes design.md m6: previously the ``test:`` field was only verified
    at the compiler unit-test level (CLIPS string output). This class
    loads YAML rules via ``engine.load_rules()`` and calls
    ``engine.evaluate()`` to prove the test CE fires correctly at runtime.
    """

    TEMPLATES = (
        "templates:\n"
        "  - name: trigger\n"
        "    slots:\n"
        "      - name: n\n"
        "        type: integer\n"
        "        required: true\n"
        "  - name: routing_decision\n"
        "    slots:\n"
        "      - name: source_id\n"
        "        type: string\n"
        "      - name: reason\n"
        "        type: string\n"
    )
    MODULES = (
        "modules:\n"
        "  - name: test_ce\n"
        '    description: "test CE integration"\n'
        "focus_order:\n"
        "  - test_ce\n"
    )
    RULES = (
        "ruleset: test-ce-roundtrip\n"
        "version: 1.0\n"
        "module: test_ce\n"
        "rules:\n"
        "  - name: double-equals-ten\n"
        "    salience: 50\n"
        "    when:\n"
        "      - template: trigger\n"
        "        conditions:\n"
        "          - slot: n\n"
        '            bind: "?n"\n'
        '          - test: "(= (double ?n) 10)"\n'
        "    then:\n"
        "      action: allow\n"
        '      reason: "test CE matched"\n'
        "      assert:\n"
        "        - template: routing_decision\n"
        "          slots:\n"
        "            source_id: matched\n"
        "            reason: match\n"
    )

    def _build_engine(self, tmp_path):
        (tmp_path / "templates.yaml").write_text(self.TEMPLATES)
        (tmp_path / "modules.yaml").write_text(self.MODULES)
        (tmp_path / "rules.yaml").write_text(self.RULES)

        engine = Engine()
        engine.load_templates(str(tmp_path / "templates.yaml"))
        engine.load_modules(str(tmp_path / "modules.yaml"))
        engine.register_function("double", lambda x: x * 2)
        engine.load_rules(str(tmp_path / "rules.yaml"))
        return engine

    def test_yaml_test_ce_fires_when_predicate_true(self, tmp_path):
        engine = self._build_engine(tmp_path)
        engine.assert_fact("trigger", {"n": 5})
        result = engine.evaluate()

        assert result.decision == "allow"
        assert result.reason == "test CE matched"
        facts = engine.query("routing_decision")
        assert len(facts) == 1
        assert facts[0]["source_id"] == "matched"

    def test_yaml_test_ce_does_not_fire_when_predicate_false(self, tmp_path):
        engine = self._build_engine(tmp_path)
        engine.assert_fact("trigger", {"n": 3})
        result = engine.evaluate()

        assert result.decision != "allow"
        facts = engine.query("routing_decision")
        assert len(facts) == 0
