"""Unit tests for function compilation and YAML parsing in Compiler."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fathom.errors import CompilationError
from fathom.models import FunctionDefinition, HierarchyDefinition

if TYPE_CHECKING:
    from pathlib import Path

    from fathom.compiler import Compiler

# ---------------------------------------------------------------------------
# compile_function dispatch tests
# ---------------------------------------------------------------------------


class TestCompileFunctionRaw:
    """Tests for raw CLIPS function passthrough."""

    def test_raw_function_returns_body(self, compiler: Compiler) -> None:
        defn = FunctionDefinition(
            name="my-fn",
            type="raw",
            params=[],
            body="(deffunction my-fn () (+ 1 2))",
        )
        result = compiler.compile_function(defn)
        assert result == "(deffunction my-fn () (+ 1 2))"

    def test_raw_function_preserves_body_exactly(self, compiler: Compiler) -> None:
        body = "(deffunction MAIN::custom (?x ?y)\n    (+ ?x ?y))"
        defn = FunctionDefinition(name="custom", type="raw", params=["x", "y"], body=body)
        result = compiler.compile_function(defn)
        assert result == body

    def test_raw_function_multiline_body(self, compiler: Compiler) -> None:
        body = (
            "(deffunction MAIN::complex (?a)\n"
            "    (if (> ?a 0)\n"
            "        then ?a\n"
            "        else (- 0 ?a)))"
        )
        defn = FunctionDefinition(name="complex", type="raw", params=["a"], body=body)
        result = compiler.compile_function(defn)
        assert result == body

    def test_raw_no_body_raises(self, compiler: Compiler) -> None:
        defn = FunctionDefinition(name="bad-fn", type="raw", params=[], body=None)
        with pytest.raises(CompilationError, match="no body"):
            compiler.compile_function(defn)

    def test_raw_no_body_error_construct(self, compiler: Compiler) -> None:
        defn = FunctionDefinition(name="bad-fn", type="raw", params=[], body=None)
        with pytest.raises(CompilationError) as exc_info:
            compiler.compile_function(defn)
        assert exc_info.value.construct == "function:bad-fn"

    @pytest.mark.parametrize(
        "body",
        [
            "(deffunction noop () TRUE)",
            "(deffunction add (?a ?b) (+ ?a ?b))",
            '(deffunction greet (?name) (str-cat "Hello " ?name))',
        ],
    )
    def test_raw_various_bodies(self, compiler: Compiler, body: str) -> None:
        defn = FunctionDefinition(name="fn", type="raw", params=[], body=body)
        result = compiler.compile_function(defn)
        assert result == body


class TestCompileFunctionTemporal:
    """Tests for temporal function compilation (returns empty stub)."""

    def test_temporal_returns_empty(self, compiler: Compiler) -> None:
        defn = FunctionDefinition(
            name="changed_within",
            type="temporal",
            params=["timestamp", "window"],
        )
        result = compiler.compile_function(defn)
        assert result == ""

    def test_temporal_count_exceeds_returns_empty(self, compiler: Compiler) -> None:
        defn = FunctionDefinition(
            name="count_exceeds",
            type="temporal",
            params=["template", "slot", "value", "threshold"],
        )
        result = compiler.compile_function(defn)
        assert result == ""

    def test_temporal_rate_exceeds_returns_empty(self, compiler: Compiler) -> None:
        defn = FunctionDefinition(
            name="rate_exceeds",
            type="temporal",
            params=["template", "slot", "value", "threshold", "window"],
        )
        result = compiler.compile_function(defn)
        assert result == ""

    @pytest.mark.parametrize(
        "name",
        ["changed_within", "count_exceeds", "rate_exceeds", "my_temporal"],
    )
    def test_temporal_various_names_return_empty(self, compiler: Compiler, name: str) -> None:
        defn = FunctionDefinition(name=name, type="temporal", params=[])
        result = compiler.compile_function(defn)
        assert result == ""


class TestCompileFunctionValidation:
    """Tests for compile_function input validation."""

    def test_empty_name_raises(self, compiler: Compiler) -> None:
        # Empty name now rejected by the Pydantic CLIPS-identifier validator.
        with pytest.raises(ValueError, match="valid CLIPS identifier"):
            FunctionDefinition(name="", type="raw", params=[], body="x")

    def test_empty_name_error_construct(self, compiler: Compiler) -> None:
        with pytest.raises(ValueError, match="FunctionDefinition.name"):
            FunctionDefinition(name="", type="raw", params=[], body="x")

    def test_classification_without_hierarchy_ref_raises(self, compiler: Compiler) -> None:
        defn = FunctionDefinition(
            name="cls",
            type="classification",
            params=["a", "b"],
            hierarchy_ref=None,
        )
        with pytest.raises(CompilationError, match="hierarchy_ref"):
            compiler.compile_function(defn)

    def test_classification_missing_hierarchy_raises(self, compiler: Compiler) -> None:
        defn = FunctionDefinition(
            name="cls",
            type="classification",
            params=["a", "b"],
            hierarchy_ref="nonexistent.yaml",
        )
        with pytest.raises(CompilationError, match="not found"):
            compiler.compile_function(defn, hierarchy={})

    def test_classification_none_hierarchy_dict_raises(self, compiler: Compiler) -> None:
        defn = FunctionDefinition(
            name="cls",
            type="classification",
            params=["a", "b"],
            hierarchy_ref="test.yaml",
        )
        with pytest.raises(CompilationError, match="not found"):
            compiler.compile_function(defn, hierarchy=None)

    def test_classification_missing_hierarchy_error_construct(self, compiler: Compiler) -> None:
        defn = FunctionDefinition(
            name="cls",
            type="classification",
            params=["a", "b"],
            hierarchy_ref="missing.yaml",
        )
        with pytest.raises(CompilationError) as exc_info:
            compiler.compile_function(defn, hierarchy={})
        assert exc_info.value.construct == "function:cls"


# ---------------------------------------------------------------------------
# _compile_classification_functions tests
# ---------------------------------------------------------------------------


class TestClassificationFunctionsRank:
    """Tests for the rank deffunction generation."""

    def _make_hierarchy(self, name: str, levels: list[str]) -> dict[str, HierarchyDefinition]:
        return {name: HierarchyDefinition(name=name, levels=levels)}

    def _make_defn(self, name: str, ref: str) -> FunctionDefinition:
        return FunctionDefinition(
            name=name,
            type="classification",
            params=["a", "b"],
            hierarchy_ref=ref,
        )

    def test_rank_function_present(self, compiler: Compiler) -> None:
        hier = self._make_hierarchy("cls", ["low", "high"])
        defn = self._make_defn("cls", "cls.yaml")
        result = compiler.compile_function(defn, hierarchy=hier)
        assert "deffunction MAIN::cls-rank" in result

    def test_rank_uses_switch(self, compiler: Compiler) -> None:
        hier = self._make_hierarchy("cls", ["low", "high"])
        defn = self._make_defn("cls", "cls.yaml")
        result = compiler.compile_function(defn, hierarchy=hier)
        assert "(switch ?level" in result

    @pytest.mark.parametrize(
        "levels,expected_cases",
        [
            (["low", "high"], [("low", "0"), ("high", "1")]),
            (
                ["a", "b", "c", "d", "e"],
                [("a", "0"), ("b", "1"), ("c", "2"), ("d", "3"), ("e", "4")],
            ),
        ],
    )
    def test_rank_case_indices(
        self,
        compiler: Compiler,
        levels: list[str],
        expected_cases: list[tuple[str, str]],
    ) -> None:
        hier = self._make_hierarchy("cls", levels)
        defn = self._make_defn("cls", "cls.yaml")
        result = compiler.compile_function(defn, hierarchy=hier)
        for level, idx in expected_cases:
            assert f"(case {level} then {idx})" in result

    def test_rank_default_minus_one(self, compiler: Compiler) -> None:
        hier = self._make_hierarchy("cls", ["low", "high"])
        defn = self._make_defn("cls", "cls.yaml")
        result = compiler.compile_function(defn, hierarchy=hier)
        assert "(default -1)" in result

    @pytest.mark.parametrize(
        "levels",
        [
            ["low", "high"],
            ["a", "b", "c", "d", "e"],
            ["l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9", "l10"],
        ],
        ids=["2-levels", "5-levels", "10-levels"],
    )
    def test_rank_all_levels_present(self, compiler: Compiler, levels: list[str]) -> None:
        hier = self._make_hierarchy("cls", levels)
        defn = self._make_defn("cls", "cls.yaml")
        result = compiler.compile_function(defn, hierarchy=hier)
        for level in levels:
            assert f"(case {level}" in result

    def test_rank_param_is_level(self, compiler: Compiler) -> None:
        hier = self._make_hierarchy("cls", ["low", "high"])
        defn = self._make_defn("cls", "cls.yaml")
        result = compiler.compile_function(defn, hierarchy=hier)
        assert "(?level)" in result


class TestClassificationFunctionsBelow:
    """Tests for the 'below' deffunction generation."""

    def _compile(self, compiler: Compiler, levels: list[str]) -> str:
        hier = {"cls": HierarchyDefinition(name="cls", levels=levels)}
        defn = FunctionDefinition(
            name="cls",
            type="classification",
            params=["a", "b"],
            hierarchy_ref="cls.yaml",
        )
        return compiler.compile_function(defn, hierarchy=hier)

    def test_below_function_present(self, compiler: Compiler) -> None:
        result = self._compile(compiler, ["low", "high"])
        assert "deffunction MAIN::below" in result

    def test_below_uses_less_than(self, compiler: Compiler) -> None:
        result = self._compile(compiler, ["low", "high"])
        assert "(< (cls-rank ?a) (cls-rank ?b))" in result

    def test_below_has_two_params(self, compiler: Compiler) -> None:
        result = self._compile(compiler, ["low", "high"])
        assert "(?a ?b)" in result

    @pytest.mark.parametrize(
        "levels",
        [
            ["low", "high"],
            ["a", "b", "c"],
            ["l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9", "l10"],
        ],
        ids=["2-levels", "3-levels", "10-levels"],
    )
    def test_below_references_rank_function(self, compiler: Compiler, levels: list[str]) -> None:
        result = self._compile(compiler, levels)
        # below should call cls-rank
        assert "cls-rank" in result


class TestClassificationFunctionsMeetsOrExceeds:
    """Tests for the 'meets-or-exceeds' deffunction generation."""

    def _compile(self, compiler: Compiler, levels: list[str]) -> str:
        hier = {"cls": HierarchyDefinition(name="cls", levels=levels)}
        defn = FunctionDefinition(
            name="cls",
            type="classification",
            params=["a", "b"],
            hierarchy_ref="cls.yaml",
        )
        return compiler.compile_function(defn, hierarchy=hier)

    def test_meets_or_exceeds_present(self, compiler: Compiler) -> None:
        result = self._compile(compiler, ["low", "high"])
        assert "deffunction MAIN::meets-or-exceeds" in result

    def test_meets_or_exceeds_uses_gte(self, compiler: Compiler) -> None:
        result = self._compile(compiler, ["low", "high"])
        assert "(>= (cls-rank ?a) (cls-rank ?b))" in result

    def test_meets_or_exceeds_has_two_params(self, compiler: Compiler) -> None:
        result = self._compile(compiler, ["low", "high"])
        # Find the scoped meets-or-exceeds deffunction line
        lines = result.split("\n")
        meets_line = [
            line for line in lines if "cls-meets-or-exceeds" in line and "deffunction" in line
        ]
        assert len(meets_line) == 1
        assert "(?a ?b)" in meets_line[0]

    @pytest.mark.parametrize(
        "levels",
        [
            ["low", "high"],
            ["a", "b", "c", "d", "e"],
            ["l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9", "l10"],
        ],
        ids=["2-levels", "5-levels", "10-levels"],
    )
    def test_meets_or_exceeds_references_rank(self, compiler: Compiler, levels: list[str]) -> None:
        result = self._compile(compiler, levels)
        assert "cls-rank" in result


class TestClassificationFunctionsWithinScope:
    """Tests for the 'within-scope' deffunction generation."""

    def _compile(self, compiler: Compiler, levels: list[str]) -> str:
        hier = {"cls": HierarchyDefinition(name="cls", levels=levels)}
        defn = FunctionDefinition(
            name="cls",
            type="classification",
            params=["a", "b"],
            hierarchy_ref="cls.yaml",
        )
        return compiler.compile_function(defn, hierarchy=hier)

    def test_within_scope_present(self, compiler: Compiler) -> None:
        result = self._compile(compiler, ["low", "high"])
        assert "deffunction MAIN::within-scope" in result

    def test_within_scope_uses_and(self, compiler: Compiler) -> None:
        result = self._compile(compiler, ["low", "high"])
        assert "(and (>= (cls-rank ?a) 0) (>= (cls-rank ?b) 0))" in result

    def test_within_scope_checks_both_params(self, compiler: Compiler) -> None:
        result = self._compile(compiler, ["low", "high"])
        assert "(cls-rank ?a)" in result
        assert "(cls-rank ?b)" in result

    @pytest.mark.parametrize(
        "levels",
        [
            ["low", "high"],
            ["a", "b", "c"],
            ["l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9", "l10"],
        ],
        ids=["2-levels", "3-levels", "10-levels"],
    )
    def test_within_scope_references_rank(self, compiler: Compiler, levels: list[str]) -> None:
        result = self._compile(compiler, levels)
        assert "cls-rank" in result


class TestClassificationFunctionsFullOutput:
    """Tests for full classification function compilation output."""

    def _compile(self, compiler: Compiler, name: str, levels: list[str]) -> str:
        hier = {name: HierarchyDefinition(name=name, levels=levels)}
        defn = FunctionDefinition(
            name=name,
            type="classification",
            params=["a", "b"],
            hierarchy_ref=f"{name}.yaml",
        )
        return compiler.compile_function(defn, hierarchy=hier)

    def test_generates_seven_functions_for_first_hierarchy(self, compiler: Compiler) -> None:
        result = self._compile(compiler, "cls", ["low", "high"])
        # 4 scoped (rank, below, meets-or-exceeds, within-scope) + 3 unscoped shims
        assert result.count("deffunction") == 7

    def test_functions_separated_by_double_newline(self, compiler: Compiler) -> None:
        result = self._compile(compiler, "cls", ["low", "high"])
        parts = result.split("\n\n")
        # 4 scoped + 3 unscoped shims = 7 parts
        assert len(parts) == 7

    def test_all_four_function_names(self, compiler: Compiler) -> None:
        result = self._compile(compiler, "cls", ["low", "high"])
        assert "cls-rank" in result
        assert "below" in result
        assert "meets-or-exceeds" in result
        assert "within-scope" in result

    @pytest.mark.parametrize(
        "name",
        ["classification", "clearance", "risk", "priority", "severity"],
    )
    def test_various_hierarchy_names(self, compiler: Compiler, name: str) -> None:
        result = self._compile(compiler, name, ["low", "mid", "high"])
        assert f"{name}-rank" in result
        assert "deffunction" in result

    @pytest.mark.parametrize(
        "levels",
        [
            ["low", "high"],
            ["a", "b", "c", "d", "e"],
            ["l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9", "l10"],
        ],
        ids=["2-levels", "5-levels", "10-levels"],
    )
    def test_hierarchy_sizes(self, compiler: Compiler, levels: list[str]) -> None:
        result = self._compile(compiler, "cls", levels)
        # 4 scoped + 3 unscoped shims = 7 for first hierarchy
        assert result.count("deffunction") == 7
        # Every level should appear in a case statement
        for level in levels:
            assert f"(case {level}" in result

    def test_five_level_hierarchy_correct_indices(self, compiler: Compiler) -> None:
        levels = ["unclassified", "cui", "confidential", "secret", "top-secret"]
        result = self._compile(compiler, "classification", levels)
        assert "(case unclassified then 0)" in result
        assert "(case cui then 1)" in result
        assert "(case confidential then 2)" in result
        assert "(case secret then 3)" in result
        assert "(case top-secret then 4)" in result

    def test_ten_level_hierarchy_indices(self, compiler: Compiler) -> None:
        levels = [f"level-{i}" for i in range(10)]
        result = self._compile(compiler, "cls", levels)
        for i, level in enumerate(levels):
            assert f"(case {level} then {i})" in result

    def test_rank_function_comes_first(self, compiler: Compiler) -> None:
        result = self._compile(compiler, "cls", ["low", "high"])
        parts = result.split("\n\n")
        assert "cls-rank" in parts[0]

    def test_below_function_is_second(self, compiler: Compiler) -> None:
        result = self._compile(compiler, "cls", ["low", "high"])
        parts = result.split("\n\n")
        assert "below" in parts[1]

    def test_meets_or_exceeds_is_third(self, compiler: Compiler) -> None:
        result = self._compile(compiler, "cls", ["low", "high"])
        parts = result.split("\n\n")
        assert "meets-or-exceeds" in parts[2]

    def test_within_scope_is_fourth(self, compiler: Compiler) -> None:
        result = self._compile(compiler, "cls", ["low", "high"])
        parts = result.split("\n\n")
        assert "within-scope" in parts[3]

    def test_main_module_prefix(self, compiler: Compiler) -> None:
        result = self._compile(compiler, "cls", ["low", "high"])
        # 4 scoped + 3 unscoped shims = 7 MAIN:: prefixes
        assert result.count("MAIN::") == 7


# ---------------------------------------------------------------------------
# parse_function_file tests
# ---------------------------------------------------------------------------


class TestParseFunctionFileValid:
    """Tests for valid YAML function file parsing."""

    def test_parses_classification_fixture(
        self, compiler: Compiler, sample_functions_path: Path
    ) -> None:
        functions = compiler.parse_function_file(sample_functions_path / "classification.yaml")
        assert len(functions) == 1
        assert functions[0].name == "classification"

    def test_classification_fixture_type(
        self, compiler: Compiler, sample_functions_path: Path
    ) -> None:
        functions = compiler.parse_function_file(sample_functions_path / "classification.yaml")
        assert functions[0].type == "classification"

    def test_classification_fixture_hierarchy_ref(
        self, compiler: Compiler, sample_functions_path: Path
    ) -> None:
        functions = compiler.parse_function_file(sample_functions_path / "classification.yaml")
        assert functions[0].hierarchy_ref == "classification.yaml"

    def test_parses_temporal_fixture(
        self, compiler: Compiler, sample_functions_path: Path
    ) -> None:
        functions = compiler.parse_function_file(sample_functions_path / "temporal.yaml")
        assert len(functions) == 3

    def test_temporal_fixture_types(self, compiler: Compiler, sample_functions_path: Path) -> None:
        functions = compiler.parse_function_file(sample_functions_path / "temporal.yaml")
        assert all(f.type == "temporal" for f in functions)

    def test_returns_function_definition_objects(
        self, compiler: Compiler, sample_functions_path: Path
    ) -> None:
        functions = compiler.parse_function_file(sample_functions_path / "classification.yaml")
        assert all(isinstance(f, FunctionDefinition) for f in functions)

    def test_single_raw_function(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "raw.yaml"
        yaml_file.write_text(
            "functions:\n"
            "  - name: my-fn\n"
            "    type: raw\n"
            "    params: []\n"
            '    body: "(deffunction my-fn () TRUE)"\n'
        )
        functions = compiler.parse_function_file(yaml_file)
        assert len(functions) == 1
        assert functions[0].name == "my-fn"
        assert functions[0].type == "raw"

    def test_multiple_functions_in_file(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "multi.yaml"
        yaml_file.write_text(
            "functions:\n"
            "  - name: fn1\n"
            "    type: temporal\n"
            "    params: [a]\n"
            "  - name: fn2\n"
            "    type: temporal\n"
            "    params: [a, b]\n"
        )
        functions = compiler.parse_function_file(yaml_file)
        assert len(functions) == 2
        assert functions[0].name == "fn1"
        assert functions[1].name == "fn2"

    def test_function_params_preserved(
        self, compiler: Compiler, sample_functions_path: Path
    ) -> None:
        functions = compiler.parse_function_file(sample_functions_path / "classification.yaml")
        assert functions[0].params == ["a", "b"]


class TestParseFunctionFileErrors:
    """Tests for parse_function_file error cases."""

    def test_invalid_yaml_syntax(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("functions:\n  - name: [invalid yaml\n")
        with pytest.raises(CompilationError, match="(?i)invalid YAML"):
            compiler.parse_function_file(yaml_file)

    def test_missing_functions_key(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "no_key.yaml"
        yaml_file.write_text("templates:\n  - name: x\n")
        with pytest.raises(CompilationError, match="functions"):
            compiler.parse_function_file(yaml_file)

    def test_functions_not_a_list(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "not_list.yaml"
        yaml_file.write_text("functions:\n  name: x\n")
        with pytest.raises(CompilationError, match="list"):
            compiler.parse_function_file(yaml_file)

    def test_function_entry_not_a_dict(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "not_dict.yaml"
        yaml_file.write_text("functions:\n  - just a string\n")
        with pytest.raises(CompilationError, match="not a mapping"):
            compiler.parse_function_file(yaml_file)

    def test_duplicate_function_names(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "dup.yaml"
        yaml_file.write_text(
            "functions:\n"
            "  - name: same\n"
            "    type: temporal\n"
            "    params: []\n"
            "  - name: same\n"
            "    type: temporal\n"
            "    params: []\n"
        )
        with pytest.raises(CompilationError, match="(?i)duplicate"):
            compiler.parse_function_file(yaml_file)

    def test_duplicate_error_includes_construct(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "dup2.yaml"
        yaml_file.write_text(
            "functions:\n"
            "  - name: dup\n"
            "    type: temporal\n"
            "    params: []\n"
            "  - name: dup\n"
            "    type: temporal\n"
            "    params: []\n"
        )
        with pytest.raises(CompilationError) as exc_info:
            compiler.parse_function_file(yaml_file)
        assert "dup" in (exc_info.value.construct or "")

    def test_nonexistent_file(self, compiler: Compiler, tmp_path: Path) -> None:
        with pytest.raises(CompilationError, match="(?i)cannot read"):
            compiler.parse_function_file(tmp_path / "missing.yaml")

    def test_empty_yaml_file(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        with pytest.raises(CompilationError, match="functions"):
            compiler.parse_function_file(yaml_file)

    def test_yaml_with_only_null(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "null.yaml"
        yaml_file.write_text("null\n")
        with pytest.raises(CompilationError, match="functions"):
            compiler.parse_function_file(yaml_file)

    def test_error_includes_file_path(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "err.yaml"
        yaml_file.write_text("not_functions: []\n")
        with pytest.raises(CompilationError) as exc_info:
            compiler.parse_function_file(yaml_file)
        assert exc_info.value.file is not None
        assert "err.yaml" in exc_info.value.file

    @pytest.mark.parametrize(
        "content,match_str",
        [
            ("functions: {}", "list"),
            ("functions: 42", "list"),
            ("functions: hello", "list"),
        ],
    )
    def test_functions_various_non_list_types(
        self,
        compiler: Compiler,
        tmp_path: Path,
        content: str,
        match_str: str,
    ) -> None:
        yaml_file = tmp_path / "non_list.yaml"
        yaml_file.write_text(content + "\n")
        with pytest.raises(CompilationError, match=match_str):
            compiler.parse_function_file(yaml_file)

    def test_invalid_yaml_tabs(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "tabs.yaml"
        yaml_file.write_text("functions:\n\t- name: bad\n")
        with pytest.raises(CompilationError, match="(?i)invalid YAML"):
            compiler.parse_function_file(yaml_file)

    def test_missing_params_field(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "no_params.yaml"
        yaml_file.write_text("functions:\n  - name: fn\n    type: raw\n")
        with pytest.raises(CompilationError, match="(?i)invalid function"):
            compiler.parse_function_file(yaml_file)


# ---------------------------------------------------------------------------
# Integration: parse + compile
# ---------------------------------------------------------------------------


class TestFunctionCompileIntegration:
    """Tests that parsed functions compile correctly."""

    def test_parsed_classification_compiles(
        self, compiler: Compiler, sample_functions_path: Path
    ) -> None:
        functions = compiler.parse_function_file(sample_functions_path / "classification.yaml")
        hier = {
            "classification": HierarchyDefinition(
                name="classification",
                levels=[
                    "unclassified",
                    "cui",
                    "confidential",
                    "secret",
                    "top-secret",
                ],
            )
        }
        result = compiler.compile_function(functions[0], hierarchy=hier)
        assert "classification-rank" in result
        assert "below" in result
        assert "meets-or-exceeds" in result
        assert "within-scope" in result

    def test_parsed_temporal_compiles(
        self, compiler: Compiler, sample_functions_path: Path
    ) -> None:
        functions = compiler.parse_function_file(sample_functions_path / "temporal.yaml")
        for fn in functions:
            result = compiler.compile_function(fn)
            assert result == ""

    def test_parsed_raw_compiles(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "raw.yaml"
        yaml_file.write_text(
            "functions:\n"
            "  - name: adder\n"
            "    type: raw\n"
            "    params: [a, b]\n"
            '    body: "(deffunction adder (?a ?b) (+ ?a ?b))"\n'
        )
        functions = compiler.parse_function_file(yaml_file)
        result = compiler.compile_function(functions[0])
        assert result == "(deffunction adder (?a ?b) (+ ?a ?b))"

    def test_classification_with_fixture_hierarchy(
        self, compiler: Compiler, sample_functions_path: Path
    ) -> None:
        functions = compiler.parse_function_file(sample_functions_path / "classification.yaml")
        hier = {
            "classification": HierarchyDefinition(
                name="classification",
                levels=[
                    "unclassified",
                    "cui",
                    "confidential",
                    "secret",
                    "top-secret",
                ],
            )
        }
        result = compiler.compile_function(functions[0], hierarchy=hier)
        assert "(case unclassified then 0)" in result
        assert "(case top-secret then 4)" in result
        # 4 scoped + 3 unscoped shims = 7 for first hierarchy
        assert result.count("deffunction") == 7
