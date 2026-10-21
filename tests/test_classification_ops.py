"""Unit tests for classification operator enhancements.

Covers multi-hierarchy loading, scoped rank/below/meets functions,
compartment parsing, dominance checks, and backward compatibility.
"""

from __future__ import annotations

from fathom.compiler import Compiler
from fathom.engine import (
    Engine,
    compartments_superset,
    dominates,
    has_compartment,
    parse_compartments,
)
from fathom.models import HierarchyDefinition

# ---------------------------------------------------------------------------
# Compartment parsing
# ---------------------------------------------------------------------------


class TestParseCompartments:
    """Tests for parse_compartments helper."""

    def test_empty_string_returns_empty_list(self) -> None:
        assert parse_compartments("") == []

    def test_whitespace_only_returns_empty_list(self) -> None:
        assert parse_compartments("   ") == []

    def test_single_compartment(self) -> None:
        assert parse_compartments("NATO") == ["NATO"]

    def test_two_compartments_pipe_delimited(self) -> None:
        assert parse_compartments("NATO|FVEY") == ["NATO", "FVEY"]

    def test_three_compartments(self) -> None:
        assert parse_compartments("NATO|FVEY|SAR") == ["NATO", "FVEY", "SAR"]

    def test_strips_whitespace_around_names(self) -> None:
        assert parse_compartments(" NATO | FVEY ") == ["NATO", "FVEY"]

    def test_trailing_pipe_ignored(self) -> None:
        result = parse_compartments("NATO|FVEY|")
        assert result == ["NATO", "FVEY"]

    def test_leading_pipe_ignored(self) -> None:
        result = parse_compartments("|NATO|FVEY")
        assert result == ["NATO", "FVEY"]

    def test_multiple_consecutive_pipes_ignored(self) -> None:
        result = parse_compartments("NATO||FVEY")
        assert result == ["NATO", "FVEY"]


# ---------------------------------------------------------------------------
# has_compartment
# ---------------------------------------------------------------------------


class TestHasCompartment:
    """Tests for has_compartment helper."""

    def test_present_compartment(self) -> None:
        assert has_compartment("NATO|FVEY", "NATO") is True

    def test_absent_compartment(self) -> None:
        assert has_compartment("NATO|FVEY", "SAR") is False

    def test_empty_subject_always_false(self) -> None:
        assert has_compartment("", "NATO") is False

    def test_single_compartment_match(self) -> None:
        assert has_compartment("NATO", "NATO") is True

    def test_single_compartment_no_match(self) -> None:
        assert has_compartment("NATO", "FVEY") is False


# ---------------------------------------------------------------------------
# compartments_superset
# ---------------------------------------------------------------------------


class TestCompartmentsSuperset:
    """Tests for compartments_superset helper."""

    def test_superset_returns_true(self) -> None:
        assert compartments_superset("NATO|FVEY|SAR", "NATO|FVEY") is True

    def test_exact_match_is_superset(self) -> None:
        assert compartments_superset("NATO|FVEY", "NATO|FVEY") is True

    def test_subset_returns_false(self) -> None:
        assert compartments_superset("NATO", "NATO|FVEY") is False

    def test_empty_required_always_true(self) -> None:
        assert compartments_superset("NATO", "") is True

    def test_empty_subject_empty_required(self) -> None:
        assert compartments_superset("", "") is True

    def test_empty_subject_nonempty_required(self) -> None:
        assert compartments_superset("", "NATO") is False


# ---------------------------------------------------------------------------
# Dominance (level + compartment combined)
# ---------------------------------------------------------------------------

_STANDARD_HIERARCHY = HierarchyDefinition(
    name="classification",
    levels=["unclassified", "confidential", "secret", "top-secret"],
)

_REGISTRY: dict[str, HierarchyDefinition] = {"classification": _STANDARD_HIERARCHY}


class TestDominates:
    """Tests for the dominates() pure function."""

    def test_higher_level_empty_compartments_dominates(self) -> None:
        assert dominates("secret", "", "confidential", "", "classification", _REGISTRY) is True

    def test_same_level_empty_compartments_dominates(self) -> None:
        assert dominates("secret", "", "secret", "", "classification", _REGISTRY) is True

    def test_lower_level_does_not_dominate(self) -> None:
        assert dominates("confidential", "", "secret", "", "classification", _REGISTRY) is False

    def test_higher_level_with_superset_compartments(self) -> None:
        assert (
            dominates("top-secret", "NATO|FVEY", "secret", "NATO", "classification", _REGISTRY)
            is True
        )

    def test_higher_level_missing_compartment_fails(self) -> None:
        assert (
            dominates("top-secret", "NATO", "secret", "NATO|FVEY", "classification", _REGISTRY)
            is False
        )

    def test_same_level_compartment_superset(self) -> None:
        assert (
            dominates("secret", "NATO|FVEY", "secret", "NATO", "classification", _REGISTRY) is True
        )

    def test_same_level_compartment_subset_fails(self) -> None:
        assert (
            dominates("secret", "NATO", "secret", "NATO|FVEY", "classification", _REGISTRY)
            is False
        )

    def test_unknown_hierarchy_returns_false(self) -> None:
        assert dominates("secret", "", "secret", "", "nonexistent", _REGISTRY) is False

    def test_unknown_level_returns_false(self) -> None:
        assert dominates("cosmic", "", "unclassified", "", "classification", _REGISTRY) is False

    def test_both_empty_compartments_same_level(self) -> None:
        assert (
            dominates("unclassified", "", "unclassified", "", "classification", _REGISTRY) is True
        )


# ---------------------------------------------------------------------------
# Multi-hierarchy: compiler compile_all_classification_functions
# ---------------------------------------------------------------------------


class TestMultiHierarchyCompilation:
    """Tests for compile_all_classification_functions with multiple hierarchies."""

    def test_two_hierarchies_both_scoped(self) -> None:
        compiler = Compiler()
        hierarchies = {
            "classification": HierarchyDefinition(
                name="classification",
                levels=["unclassified", "confidential", "secret"],
            ),
            "integrity": HierarchyDefinition(
                name="integrity",
                levels=["low", "medium", "high"],
            ),
        }
        result = compiler.compile_all_classification_functions(hierarchies)
        assert "classification-rank" in result
        assert "classification-below" in result
        assert "integrity-rank" in result
        assert "integrity-below" in result

    def test_first_hierarchy_gets_unscoped_shims(self) -> None:
        compiler = Compiler()
        hierarchies = {
            "classification": HierarchyDefinition(
                name="classification",
                levels=["unclassified", "secret"],
            ),
            "integrity": HierarchyDefinition(
                name="integrity",
                levels=["low", "high"],
            ),
        }
        result = compiler.compile_all_classification_functions(hierarchies)
        # Unscoped 'below' should delegate to the first hierarchy
        assert "deffunction MAIN::below" in result
        assert "deffunction MAIN::meets-or-exceeds" in result
        assert "deffunction MAIN::within-scope" in result

    def test_second_hierarchy_no_unscoped_shims(self) -> None:
        compiler = Compiler()
        hierarchies = {
            "classification": HierarchyDefinition(
                name="classification",
                levels=["unclassified", "secret"],
            ),
            "integrity": HierarchyDefinition(
                name="integrity",
                levels=["low", "high"],
            ),
        }
        result = compiler.compile_all_classification_functions(hierarchies)
        # Count: first hierarchy = 7 (4 scoped + 3 shims), second = 4 scoped only
        assert result.count("deffunction") == 11

    def test_single_hierarchy_backward_compat(self) -> None:
        compiler = Compiler()
        hierarchies = {
            "classification": HierarchyDefinition(
                name="classification",
                levels=["unclassified", "confidential", "secret", "top-secret"],
            ),
        }
        result = compiler.compile_all_classification_functions(hierarchies)
        # Should have unscoped shims for backward compat
        assert "deffunction MAIN::below" in result
        assert "deffunction MAIN::meets-or-exceeds" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for classification ops."""

    def test_dominates_empty_registry(self) -> None:
        assert dominates("secret", "", "secret", "", "classification", {}) is False

    def test_compartments_superset_disjoint_sets(self) -> None:
        assert compartments_superset("NATO|FVEY", "SAR|TK") is False

    def test_parse_compartments_coerces_non_string(self) -> None:
        # Engine passes CLIPS values as strings, but parse_compartments should handle gracefully
        result = parse_compartments(123)  # type: ignore[arg-type]
        assert result == ["123"]

    def test_dominates_unknown_subject_known_object(self) -> None:
        # Unknown subject rank -1 < known object rank 0, so fails
        assert dominates("cosmic", "", "unclassified", "", "classification", _REGISTRY) is False


# ---------------------------------------------------------------------------
# What the reference says a hierarchy is called, and where it lives
# ---------------------------------------------------------------------------


_HIER_TEMPLATES = """
templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
      - name: trust
        type: symbol
        required: true
"""

_HIER_MODULES = """
modules:
  - name: gate
focus_order:
  - gate
"""

_TRUST_HIERARCHY = """
name: trust
levels: [untrusted, basic, verified]
"""

_SCOPED_CALL_RULES = """
module: gate
ruleset: scoped-call
version: "1.0"

rules:
  - name: deny-below-basic
    when:
      - template: agent
        conditions:
          - slot: trust
            bind: "?t"
          - test: "(trust-below ?t basic)"
    then:
      action: deny
      reason: "below basic trust"
"""


def _hierarchy_pack(root, *, hierarchy_ref: str, rules: str):
    """A pack whose classification function is named for the function, not the
    hierarchy -- which is the normal way to write one."""
    for subdir, name, body in (
        ("templates", "templates.yaml", _HIER_TEMPLATES),
        ("modules", "modules.yaml", _HIER_MODULES),
        ("rules", "rules.yaml", rules),
        ("hierarchies", "trust.yaml", _TRUST_HIERARCHY),
        (
            "functions",
            "functions.yaml",
            "functions:\n"
            "  - name: rank_trust\n"
            "    type: classification\n"
            "    params: [a, b]\n"
            f"    hierarchy_ref: {hierarchy_ref}\n",
        ),
    ):
        (root / subdir).mkdir(parents=True, exist_ok=True)
        (root / subdir / name).write_text(body, encoding="utf-8")
    return root


class TestHierarchyNamingAndResolution:
    """`<hier>-below` and a bare `hierarchy_ref` are both documented."""

    def test_a_rule_can_call_the_hierarchys_own_deffunction(self, tmp_path) -> None:
        """The emitted family is documented as `<hier>-rank`, `<hier>-below`...

        It was emitted under the *function's* name instead, so a `test:` CE
        calling the documented name failed to compile.
        """
        pack = _hierarchy_pack(
            tmp_path / "pack", hierarchy_ref="trust.yaml", rules=_SCOPED_CALL_RULES
        )
        engine = Engine.from_rules(str(pack), default_decision="allow")
        engine.assert_fact("agent", {"id": "a-1", "trust": "untrusted"})

        assert engine.evaluate().decision == "deny"

    def test_a_bare_hierarchy_ref_resolves(self, tmp_path) -> None:
        """`hierarchy_ref: clearance` is the reference page's worked example.

        Resolution was strictly by filename, so the documented form looked for
        a file literally named `trust` and raised CompilationError.
        """
        pack = _hierarchy_pack(tmp_path / "pack", hierarchy_ref="trust", rules=_SCOPED_CALL_RULES)
        engine = Engine.from_rules(str(pack), default_decision="allow")
        engine.assert_fact("agent", {"id": "a-1", "trust": "untrusted"})

        assert engine.evaluate().decision == "deny"


# ---------------------------------------------------------------------------
# An out-of-hierarchy level fails closed on every entry point
# ---------------------------------------------------------------------------

_FC_TEMPLATES = """
templates:
  - name: subj
    slots:
      - {name: clearance, type: symbol}
      - {name: trust, type: symbol}
      - {name: comps, type: string, default: ""}
  - name: obj
    slots:
      - {name: level, type: symbol}
      - {name: trust_req, type: symbol}
      - {name: comps, type: string, default: ""}
"""

_FC_ONE_HIER = """
hierarchies:
  - name: clearance
    levels: [unclassified, confidential, secret, top-secret]
functions:
  - {name: c, type: classification, params: [a, b], hierarchy_ref: clearance}
"""

_FC_TWO_HIER = """
hierarchies:
  - name: clearance
    levels: [unclassified, confidential, secret, top-secret]
  - name: trust
    levels: [anon, verified, staff]
functions:
  - {name: c, type: classification, params: [a, b], hierarchy_ref: clearance}
  - {name: t, type: classification, params: [a, b], hierarchy_ref: trust}
"""


def _fc_engine(
    root,
    subj_conditions: str,
    functions: str = _FC_ONE_HIER,
    obj_conditions: str = "[{slot: level, bind: '?ol'}, {slot: comps, bind: '?oc'}]",
) -> Engine:
    rules = (
        "ruleset: rs\nmodule: m\nrules:\n  - name: hit\n    when:\n"
        "      - template: obj\n        alias: $o\n"
        f"        conditions: {obj_conditions}\n"
        "      - template: subj\n        conditions:\n"
        f"{subj_conditions}"
        "    then: {action: allow, reason: hit}\n"
    )
    for sub, body in (
        ("templates", _FC_TEMPLATES),
        ("modules", "modules:\n  - name: m\n"),
        ("functions", functions),
        ("rules", rules),
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
        (root / sub / "a.yaml").write_text(body, encoding="utf-8")
    return Engine.from_rules(str(root))


def _fires(engine: Engine, subj: dict, obj: dict) -> bool:
    return engine.evaluate_once([("subj", subj), ("obj", obj)]).decision == "allow"


class TestUnknownLevelFailsClosed:
    """An unknown or mis-cased label must never compare as a rank.

    The rank of a level outside the hierarchy is -1, and `below`,
    `meets_or_exceeds` and `dominates` compared it like any other rank, so
    `secret >= TOP-SECRET` and `none >= codeword` were both true.
    """

    def test_dominates_both_unknown_is_false(self) -> None:
        assert dominates("cosmic", "", "ultra", "", "classification", _REGISTRY) is False

    def test_dominates_unknown_object_is_false(self) -> None:
        assert dominates("top-secret", "", "TOP-SECRET", "", "classification", _REGISTRY) is False

    def test_meets_or_exceeds_cross_ref_unknown_either_side(self, tmp_path) -> None:
        cond = "          - {slot: clearance, expression: 'meets_or_exceeds($o.level)'}\n"
        engine = _fc_engine(tmp_path, cond, obj_conditions="[]")
        assert _fires(engine, {"clearance": "secret"}, {"level": "confidential"})
        assert not _fires(engine, {"clearance": "secret"}, {"level": "TOP-SECRET"})
        assert not _fires(engine, {"clearance": "none"}, {"level": "codeword"})
        assert not _fires(engine, {"clearance": "none"}, {"level": "unclassified"})

    def test_below_cross_ref_unknown_either_side(self, tmp_path) -> None:
        cond = "          - {slot: clearance, expression: 'below($o.level)'}\n"
        engine = _fc_engine(tmp_path, cond, obj_conditions="[]")
        assert _fires(engine, {"clearance": "confidential"}, {"level": "secret"})
        assert not _fires(engine, {"clearance": "codeword"}, {"level": "secret"})

    def test_scoped_deffunctions_in_a_test_ce(self, tmp_path) -> None:
        cond = (
            "          - {slot: clearance, bind: '?sl'}\n"
            "          - test: '(clearance-meets-or-exceeds ?sl ?ol)'\n"
        )
        engine = _fc_engine(tmp_path, cond)
        assert _fires(engine, {"clearance": "secret"}, {"level": "secret"})
        assert not _fires(engine, {"clearance": "secret"}, {"level": "codeword"})

    def test_fathom_dominates_builtin(self, tmp_path) -> None:
        cond = (
            "          - {slot: clearance, bind: '?sl'}\n"
            "          - {slot: comps, bind: '?sc'}\n"
            "          - test: '(fathom-dominates ?sl ?sc ?ol ?oc clearance)'\n"
        )
        engine = _fc_engine(tmp_path, cond)
        subj = {"clearance": "secret", "comps": "nato"}
        assert _fires(engine, subj, {"level": "secret", "comps": "nato"})
        assert not _fires(engine, subj, {"level": "TOP-SECRET", "comps": "nato"})
        assert not _fires(engine, subj, {"level": "codeword", "comps": "nato"})

    def test_cross_ref_with_two_hierarchies_is_refused(self, tmp_path) -> None:
        """The cross-ref form went to the first hierarchy's shim, where every
        level of the second ranks -1, so `anon >= staff` was true."""
        import pytest

        from fathom.errors import CompilationError

        cond = "          - {slot: trust, expression: 'meets_or_exceeds($o.trust_req)'}\n"
        with pytest.raises(CompilationError, match="more than one hierarchy"):
            _fc_engine(tmp_path, cond, _FC_TWO_HIER)
