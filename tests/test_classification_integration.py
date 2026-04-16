"""Integration test for classification + compartments end-to-end.

Loads a hierarchy YAML, compiles classification functions,
builds BLP access-control rules using fathom-dominates, and
verifies that the full evaluate() pipeline produces correct
allow/deny decisions based on level + compartment dominance.
"""

from __future__ import annotations

import pytest

from fathom.engine import Engine


@pytest.fixture
def blp_engine(tmp_path):
    """Engine with hierarchy, templates, and BLP defrule using fathom-dominates."""
    # -- hierarchy YAML --
    hier_file = tmp_path / "security.yaml"
    hier_file.write_text(
        "name: security\nlevels:\n  - unclassified\n  - confidential\n  - secret\n  - top_secret\n"
    )

    # -- function YAML referencing the hierarchy --
    func_file = tmp_path / "functions.yaml"
    func_file.write_text(
        "functions:\n"
        "  - name: security\n"
        "    type: classification\n"
        "    params: [a, b]\n"
        "    hierarchy_ref: security.yaml\n"
    )

    # -- template YAML for subject and resource --
    tmpl_file = tmp_path / "templates.yaml"
    tmpl_file.write_text(
        "templates:\n"
        "  - name: subject\n"
        "    slots:\n"
        "      - name: id\n"
        "        type: symbol\n"
        "        required: true\n"
        "      - name: level\n"
        "        type: symbol\n"
        "        required: true\n"
        "      - name: compartments\n"
        "        type: string\n"
        '        default: ""\n'
        "  - name: resource\n"
        "    slots:\n"
        "      - name: id\n"
        "        type: symbol\n"
        "        required: true\n"
        "      - name: level\n"
        "        type: symbol\n"
        "        required: true\n"
        "      - name: compartments\n"
        "        type: string\n"
        '        default: ""\n'
    )

    engine = Engine()
    engine.load_templates(str(tmpl_file))
    engine.load_functions(str(func_file))

    # -- Raw CLIPS rules using fathom-dominates --
    # Allow rule: subject dominates resource -> allow (high salience)
    allow_rule = (
        "(defrule MAIN::blp-allow\n"
        "    (declare (salience 100))\n"
        "    (subject (id ?sid) (level ?slvl) (compartments ?scomps))\n"
        "    (resource (id ?oid) (level ?olvl) (compartments ?ocomps))\n"
        '    (test (fathom-dominates ?slvl ?scomps ?olvl ?ocomps "security"))\n'
        "    =>\n"
        "    (assert (__fathom_decision\n"
        "        (action allow)\n"
        '        (reason "Subject dominates resource - access granted")\n'
        '        (rule "MAIN::blp-allow"))))'
    )
    engine._safe_build(allow_rule, context="rule:blp-allow")

    # Deny rule: subject does NOT dominate resource -> deny (lower salience)
    deny_rule = (
        "(defrule MAIN::blp-deny\n"
        "    (declare (salience 50))\n"
        "    (subject (id ?sid) (level ?slvl) (compartments ?scomps))\n"
        "    (resource (id ?oid) (level ?olvl) (compartments ?ocomps))\n"
        '    (test (not (fathom-dominates ?slvl ?scomps ?olvl ?ocomps "security")))\n'
        "    =>\n"
        "    (assert (__fathom_decision\n"
        "        (action deny)\n"
        '        (reason "Subject does not dominate resource - access denied")\n'
        '        (rule "MAIN::blp-deny"))))'
    )
    engine._safe_build(deny_rule, context="rule:blp-deny")

    return engine


# ---------------------------------------------------------------------------
# BLP lattice: higher level + superset compartments = allow
# ---------------------------------------------------------------------------


class TestBLPAllow:
    """Subject with higher level + superset compartments -> allow."""

    def test_higher_level_no_compartments(self, blp_engine):
        """top_secret subject accessing secret resource (no compartments) -> allow."""
        blp_engine.assert_fact("subject", {"id": "s1", "level": "top_secret", "compartments": ""})
        blp_engine.assert_fact("resource", {"id": "o1", "level": "secret", "compartments": ""})
        result = blp_engine.evaluate()
        assert result.decision == "allow"

    def test_same_level_no_compartments(self, blp_engine):
        """Same level, no compartments -> allow (dominance is >=)."""
        blp_engine.assert_fact("subject", {"id": "s1", "level": "secret", "compartments": ""})
        blp_engine.assert_fact("resource", {"id": "o1", "level": "secret", "compartments": ""})
        result = blp_engine.evaluate()
        assert result.decision == "allow"

    def test_higher_level_superset_compartments(self, blp_engine):
        """top_secret with NATO|FVEY accessing secret with NATO -> allow."""
        blp_engine.assert_fact(
            "subject", {"id": "s1", "level": "top_secret", "compartments": "NATO|FVEY"}
        )
        blp_engine.assert_fact("resource", {"id": "o1", "level": "secret", "compartments": "NATO"})
        result = blp_engine.evaluate()
        assert result.decision == "allow"

    def test_same_level_exact_compartments(self, blp_engine):
        """Same level, exact same compartments -> allow."""
        blp_engine.assert_fact(
            "subject", {"id": "s1", "level": "secret", "compartments": "NATO|FVEY"}
        )
        blp_engine.assert_fact(
            "resource", {"id": "o1", "level": "secret", "compartments": "NATO|FVEY"}
        )
        result = blp_engine.evaluate()
        assert result.decision == "allow"

    def test_higher_level_object_empty_compartments(self, blp_engine):
        """Higher level subject with compartments, resource has none -> allow."""
        blp_engine.assert_fact(
            "subject", {"id": "s1", "level": "top_secret", "compartments": "NATO"}
        )
        blp_engine.assert_fact(
            "resource", {"id": "o1", "level": "confidential", "compartments": ""}
        )
        result = blp_engine.evaluate()
        assert result.decision == "allow"


# ---------------------------------------------------------------------------
# BLP lattice: lower level = deny
# ---------------------------------------------------------------------------


class TestBLPDeny:
    """Subject with lower level or missing compartments -> deny."""

    def test_lower_level_no_compartments(self, blp_engine):
        """confidential subject accessing secret resource -> deny."""
        blp_engine.assert_fact(
            "subject", {"id": "s1", "level": "confidential", "compartments": ""}
        )
        blp_engine.assert_fact("resource", {"id": "o1", "level": "secret", "compartments": ""})
        result = blp_engine.evaluate()
        assert result.decision == "deny"

    def test_lower_level_with_compartments(self, blp_engine):
        """Lower level even with superset compartments -> deny."""
        blp_engine.assert_fact(
            "subject", {"id": "s1", "level": "confidential", "compartments": "NATO|FVEY"}
        )
        blp_engine.assert_fact("resource", {"id": "o1", "level": "secret", "compartments": "NATO"})
        result = blp_engine.evaluate()
        assert result.decision == "deny"

    def test_same_level_missing_compartment(self, blp_engine):
        """Same level but subject missing required compartment -> deny."""
        blp_engine.assert_fact("subject", {"id": "s1", "level": "secret", "compartments": "NATO"})
        blp_engine.assert_fact(
            "resource", {"id": "o1", "level": "secret", "compartments": "NATO|FVEY"}
        )
        result = blp_engine.evaluate()
        assert result.decision == "deny"

    def test_higher_level_missing_compartment(self, blp_engine):
        """Higher level but missing required compartment -> deny."""
        blp_engine.assert_fact(
            "subject", {"id": "s1", "level": "top_secret", "compartments": "NATO"}
        )
        blp_engine.assert_fact(
            "resource", {"id": "o1", "level": "secret", "compartments": "NATO|FVEY"}
        )
        result = blp_engine.evaluate()
        assert result.decision == "deny"

    def test_unclassified_accessing_top_secret(self, blp_engine):
        """Lowest level accessing highest level -> deny."""
        blp_engine.assert_fact(
            "subject", {"id": "s1", "level": "unclassified", "compartments": ""}
        )
        blp_engine.assert_fact(
            "resource", {"id": "o1", "level": "top_secret", "compartments": "NATO|FVEY"}
        )
        result = blp_engine.evaluate()
        assert result.decision == "deny"


# ---------------------------------------------------------------------------
# Edge cases: same level different compartments, empty compartments
# ---------------------------------------------------------------------------


class TestBLPEdgeCases:
    """Edge cases for BLP lattice evaluation."""

    def test_both_empty_compartments_unclassified(self, blp_engine):
        """Lowest level with no compartments on both sides -> allow."""
        blp_engine.assert_fact(
            "subject", {"id": "s1", "level": "unclassified", "compartments": ""}
        )
        blp_engine.assert_fact(
            "resource", {"id": "o1", "level": "unclassified", "compartments": ""}
        )
        result = blp_engine.evaluate()
        assert result.decision == "allow"

    def test_disjoint_compartments_same_level(self, blp_engine):
        """Same level but completely disjoint compartments -> deny."""
        blp_engine.assert_fact(
            "subject", {"id": "s1", "level": "secret", "compartments": "NATO|FVEY"}
        )
        blp_engine.assert_fact(
            "resource", {"id": "o1", "level": "secret", "compartments": "SAR|TK"}
        )
        result = blp_engine.evaluate()
        assert result.decision == "deny"

    def test_subject_empty_object_has_compartments(self, blp_engine):
        """Subject has no compartments, resource requires some -> deny."""
        blp_engine.assert_fact("subject", {"id": "s1", "level": "top_secret", "compartments": ""})
        blp_engine.assert_fact("resource", {"id": "o1", "level": "secret", "compartments": "NATO"})
        result = blp_engine.evaluate()
        assert result.decision == "deny"

    def test_rule_trace_populated(self, blp_engine):
        """Evaluation result includes rule trace."""
        blp_engine.assert_fact("subject", {"id": "s1", "level": "top_secret", "compartments": ""})
        blp_engine.assert_fact("resource", {"id": "o1", "level": "secret", "compartments": ""})
        result = blp_engine.evaluate()
        assert result.decision == "allow"
        assert len(result.rule_trace) > 0

    def test_reason_present_in_result(self, blp_engine):
        """Evaluation result contains a reason string."""
        blp_engine.assert_fact(
            "subject", {"id": "s1", "level": "confidential", "compartments": ""}
        )
        blp_engine.assert_fact("resource", {"id": "o1", "level": "secret", "compartments": ""})
        result = blp_engine.evaluate()
        assert result.decision == "deny"
        assert result.reason is not None
        assert len(result.reason) > 0
