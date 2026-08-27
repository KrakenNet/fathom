"""Unit tests for classification operator enhancements.

Covers multi-hierarchy loading, scoped rank/below/meets functions,
compartment parsing, dominance checks, and backward compatibility.
"""

from __future__ import annotations

from fathom.compiler import Compiler
from fathom.engine import (
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

    def test_dominates_both_unknown_levels_same_rank(self) -> None:
        # Both unknown levels get rank -1; -1 >= -1 is true, empty comps superset of empty
        assert dominates("cosmic", "", "ultra", "", "classification", _REGISTRY) is True

    def test_dominates_unknown_subject_known_object(self) -> None:
        # Unknown subject rank -1 < known object rank 0, so fails
        assert dominates("cosmic", "", "unclassified", "", "classification", _REGISTRY) is False
