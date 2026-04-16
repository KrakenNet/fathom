"""Unit tests for module compilation and YAML parsing in Compiler."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fathom.errors import CompilationError
from fathom.models import ModuleDefinition

if TYPE_CHECKING:
    from pathlib import Path

    from fathom.compiler import Compiler

# ---------------------------------------------------------------------------
# compile_module tests
# ---------------------------------------------------------------------------


class TestCompileModuleBasic:
    """Tests for basic module compilation output."""

    def test_basic_module(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="governance")
        result = compiler.compile_module(defn)
        assert "(defmodule governance" in result
        assert "(import MAIN ?ALL)" in result

    def test_module_starts_with_defmodule(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="test")
        result = compiler.compile_module(defn)
        assert result.startswith("(defmodule test")

    def test_module_ends_with_close_paren(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="test")
        result = compiler.compile_module(defn)
        assert result.rstrip().endswith(")")

    def test_module_is_single_line(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="test")
        result = compiler.compile_module(defn)
        assert "\n" not in result

    @pytest.mark.parametrize(
        "name",
        [
            "governance",
            "classification",
            "routing",
            "my-module",
            "audit_log",
            "M1",
            "a",
            "test-module-123",
        ],
    )
    def test_various_module_names(self, compiler: Compiler, name: str) -> None:
        defn = ModuleDefinition(name=name)
        result = compiler.compile_module(defn)
        assert f"(defmodule {name}" in result

    def test_module_with_description(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="governance", description="Governance rules")
        result = compiler.compile_module(defn)
        # Description is metadata, not included in CLIPS output
        assert "(defmodule governance" in result
        assert "Governance rules" not in result

    def test_module_import_all_templates(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="routing")
        result = compiler.compile_module(defn)
        assert "?ALL" in result

    def test_module_import_from_main(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="routing")
        result = compiler.compile_module(defn)
        assert "MAIN" in result


class TestCompileModuleOutputFormat:
    """Tests for exact output format of compile_module."""

    def test_exact_format_simple(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="governance")
        result = compiler.compile_module(defn)
        assert result == "(defmodule governance (import MAIN ?ALL))"

    @pytest.mark.parametrize(
        "name,expected",
        [
            (
                "classification",
                "(defmodule classification (import MAIN ?ALL))",
            ),
            (
                "routing",
                "(defmodule routing (import MAIN ?ALL))",
            ),
            (
                "audit",
                "(defmodule audit (import MAIN ?ALL))",
            ),
        ],
    )
    def test_exact_format_parametrized(self, compiler: Compiler, name: str, expected: str) -> None:
        defn = ModuleDefinition(name=name)
        result = compiler.compile_module(defn)
        assert result == expected

    def test_contains_import_directive(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="test")
        result = compiler.compile_module(defn)
        assert "(import MAIN ?ALL)" in result

    def test_open_paren_at_start(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="test")
        result = compiler.compile_module(defn)
        assert result[0] == "("

    def test_close_paren_at_end(self, compiler: Compiler) -> None:
        defn = ModuleDefinition(name="test")
        result = compiler.compile_module(defn)
        assert result[-1] == ")"


class TestCompileModuleValidation:
    """Tests for compile_module input validation."""

    def test_empty_name_raises(self, compiler: Compiler) -> None:
        # Empty name now rejected at the Pydantic model layer.
        with pytest.raises(ValueError, match="valid CLIPS identifier"):
            ModuleDefinition(name="")

    def test_empty_name_error_has_construct(self, compiler: Compiler) -> None:
        with pytest.raises(ValueError, match="ModuleDefinition.name"):
            ModuleDefinition(name="")

    def test_empty_name_error_message(self, compiler: Compiler) -> None:
        with pytest.raises(ValueError, match="valid CLIPS identifier"):
            ModuleDefinition(name="")


# ---------------------------------------------------------------------------
# compile_focus_stack tests
# ---------------------------------------------------------------------------


class TestCompileFocusStack:
    """Tests for focus stack compilation with reversal."""

    @pytest.mark.parametrize(
        "order,expected",
        [
            (["A"], "(focus A)"),
            (["A", "B"], "(focus B A)"),
            (["A", "B", "C"], "(focus C B A)"),
            (["A", "B", "C", "D"], "(focus D C B A)"),
            (["A", "B", "C", "D", "E"], "(focus E D C B A)"),
        ],
    )
    def test_focus_reversal(self, compiler: Compiler, order: list[str], expected: str) -> None:
        result = compiler.compile_focus_stack(order)
        assert result == expected

    @pytest.mark.parametrize(
        "order,expected",
        [
            (
                ["classification", "governance", "routing"],
                "(focus routing governance classification)",
            ),
            (
                ["governance"],
                "(focus governance)",
            ),
            (
                ["audit", "governance"],
                "(focus governance audit)",
            ),
        ],
    )
    def test_focus_real_module_names(
        self, compiler: Compiler, order: list[str], expected: str
    ) -> None:
        result = compiler.compile_focus_stack(order)
        assert result == expected

    def test_focus_starts_with_focus_keyword(self, compiler: Compiler) -> None:
        result = compiler.compile_focus_stack(["A"])
        assert result.startswith("(focus ")

    def test_focus_ends_with_close_paren(self, compiler: Compiler) -> None:
        result = compiler.compile_focus_stack(["A", "B"])
        assert result.endswith(")")

    def test_focus_single_element_not_reversed(self, compiler: Compiler) -> None:
        result = compiler.compile_focus_stack(["only"])
        assert result == "(focus only)"

    def test_focus_two_elements_swapped(self, compiler: Compiler) -> None:
        result = compiler.compile_focus_stack(["first", "second"])
        assert result == "(focus second first)"

    def test_focus_preserves_module_names(self, compiler: Compiler) -> None:
        names = ["my-module", "test_mod", "M1"]
        result = compiler.compile_focus_stack(names)
        for name in names:
            assert name in result

    def test_focus_order_is_push_semantics(self, compiler: Compiler) -> None:
        """First in YAML = first to execute = last pushed onto stack."""
        result = compiler.compile_focus_stack(["exec_first", "exec_second"])
        # exec_first should be last in the focus command (pushed last = top)
        assert result == "(focus exec_second exec_first)"

    @pytest.mark.parametrize("count", [1, 2, 3, 5, 8])
    def test_focus_n_modules_all_present(self, compiler: Compiler, count: int) -> None:
        modules = [f"mod{i}" for i in range(count)]
        result = compiler.compile_focus_stack(modules)
        for mod in modules:
            assert mod in result


# ---------------------------------------------------------------------------
# parse_module_file tests
# ---------------------------------------------------------------------------


class TestParseModuleFileValid:
    """Tests for valid YAML module file parsing."""

    def test_parses_fixture_file(self, compiler: Compiler, sample_modules_path: Path) -> None:
        modules, focus_order = compiler.parse_module_file(sample_modules_path)
        assert len(modules) == 1
        assert modules[0].name == "governance"

    def test_fixture_focus_order(self, compiler: Compiler, sample_modules_path: Path) -> None:
        _modules, focus_order = compiler.parse_module_file(sample_modules_path)
        assert focus_order == ["governance"]

    def test_fixture_module_description(
        self, compiler: Compiler, sample_modules_path: Path
    ) -> None:
        modules, _focus_order = compiler.parse_module_file(sample_modules_path)
        assert modules[0].description == "Action-level governance rules"

    def test_returns_module_definition_objects(
        self, compiler: Compiler, sample_modules_path: Path
    ) -> None:
        modules, _focus_order = compiler.parse_module_file(sample_modules_path)
        assert all(isinstance(m, ModuleDefinition) for m in modules)

    def test_single_module_file(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "single.yaml"
        yaml_file.write_text(
            "modules:\n  - name: test\n    description: Test module\nfocus_order:\n  - test\n"
        )
        modules, focus_order = compiler.parse_module_file(yaml_file)
        assert len(modules) == 1
        assert modules[0].name == "test"
        assert focus_order == ["test"]

    def test_multiple_modules_file(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "multi.yaml"
        yaml_file.write_text(
            "modules:\n"
            "  - name: classification\n"
            "  - name: governance\n"
            "  - name: routing\n"
            "focus_order:\n"
            "  - classification\n"
            "  - governance\n"
            "  - routing\n"
        )
        modules, focus_order = compiler.parse_module_file(yaml_file)
        assert len(modules) == 3
        assert modules[0].name == "classification"
        assert modules[1].name == "governance"
        assert modules[2].name == "routing"
        assert focus_order == ["classification", "governance", "routing"]

    def test_modules_without_focus_order(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "no_focus.yaml"
        yaml_file.write_text("modules:\n  - name: standalone\n")
        modules, focus_order = compiler.parse_module_file(yaml_file)
        assert len(modules) == 1
        assert focus_order == []

    def test_module_with_description_preserved(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "desc.yaml"
        yaml_file.write_text("modules:\n  - name: gov\n    description: Governance module\n")
        modules, _focus_order = compiler.parse_module_file(yaml_file)
        assert modules[0].description == "Governance module"

    def test_module_without_description_defaults_empty(
        self, compiler: Compiler, tmp_path: Path
    ) -> None:
        yaml_file = tmp_path / "no_desc.yaml"
        yaml_file.write_text("modules:\n  - name: minimal\n")
        modules, _focus_order = compiler.parse_module_file(yaml_file)
        assert modules[0].description == ""

    def test_returns_tuple(self, compiler: Compiler, sample_modules_path: Path) -> None:
        result = compiler.parse_module_file(sample_modules_path)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_focus_order_is_list_of_strings(
        self, compiler: Compiler, sample_modules_path: Path
    ) -> None:
        _modules, focus_order = compiler.parse_module_file(sample_modules_path)
        assert isinstance(focus_order, list)
        assert all(isinstance(s, str) for s in focus_order)


class TestParseModuleFileErrors:
    """Tests for parse_module_file error cases."""

    def test_invalid_yaml_syntax(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("modules:\n  - name: [invalid yaml\n")
        with pytest.raises(CompilationError, match="(?i)invalid YAML"):
            compiler.parse_module_file(yaml_file)

    def test_missing_modules_key(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "no_key.yaml"
        yaml_file.write_text("templates:\n  - name: x\n")
        with pytest.raises(CompilationError, match="modules"):
            compiler.parse_module_file(yaml_file)

    def test_modules_not_a_list(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "not_list.yaml"
        yaml_file.write_text("modules:\n  name: x\n")
        with pytest.raises(CompilationError, match="list"):
            compiler.parse_module_file(yaml_file)

    def test_module_entry_not_a_dict(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "not_dict.yaml"
        yaml_file.write_text("modules:\n  - just a string\n")
        with pytest.raises(CompilationError, match="not a mapping"):
            compiler.parse_module_file(yaml_file)

    def test_duplicate_module_names(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "dup.yaml"
        yaml_file.write_text("modules:\n  - name: same\n  - name: same\n")
        with pytest.raises(CompilationError, match="(?i)duplicate"):
            compiler.parse_module_file(yaml_file)

    def test_duplicate_error_includes_construct(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "dup2.yaml"
        yaml_file.write_text("modules:\n  - name: dup\n  - name: dup\n")
        with pytest.raises(CompilationError) as exc_info:
            compiler.parse_module_file(yaml_file)
        assert "dup" in (exc_info.value.construct or "")

    def test_nonexistent_file(self, compiler: Compiler, tmp_path: Path) -> None:
        with pytest.raises(CompilationError, match="(?i)cannot read"):
            compiler.parse_module_file(tmp_path / "missing.yaml")

    def test_empty_yaml_file(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        with pytest.raises(CompilationError, match="modules"):
            compiler.parse_module_file(yaml_file)

    def test_yaml_with_only_null(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "null.yaml"
        yaml_file.write_text("null\n")
        with pytest.raises(CompilationError, match="modules"):
            compiler.parse_module_file(yaml_file)

    def test_error_includes_file_path(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "err.yaml"
        yaml_file.write_text("not_modules: []\n")
        with pytest.raises(CompilationError) as exc_info:
            compiler.parse_module_file(yaml_file)
        assert exc_info.value.file is not None
        assert "err.yaml" in exc_info.value.file

    @pytest.mark.parametrize(
        "content,match_str",
        [
            ("modules: {}", "list"),
            ("modules: 42", "list"),
            ("modules: hello", "list"),
        ],
    )
    def test_modules_various_non_list_types(
        self,
        compiler: Compiler,
        tmp_path: Path,
        content: str,
        match_str: str,
    ) -> None:
        yaml_file = tmp_path / "non_list.yaml"
        yaml_file.write_text(content + "\n")
        with pytest.raises(CompilationError, match=match_str):
            compiler.parse_module_file(yaml_file)

    def test_invalid_yaml_tabs(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "tabs.yaml"
        yaml_file.write_text("modules:\n\t- name: bad\n")
        with pytest.raises(CompilationError, match="(?i)invalid YAML"):
            compiler.parse_module_file(yaml_file)

    def test_focus_order_not_a_list(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad_focus.yaml"
        yaml_file.write_text("modules:\n  - name: test\nfocus_order: not-a-list\n")
        with pytest.raises(CompilationError, match="focus_order.*list"):
            compiler.parse_module_file(yaml_file)

    def test_missing_name_field(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "no_name.yaml"
        yaml_file.write_text("modules:\n  - description: Missing name\n")
        with pytest.raises(CompilationError, match="(?i)invalid module"):
            compiler.parse_module_file(yaml_file)


class TestParseModuleFileEdgeCases:
    """Edge case tests for module file parsing."""

    def test_module_with_extra_keys_ignored(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "extra.yaml"
        yaml_file.write_text("modules:\n  - name: test\n    extra_key: ignored\n")
        modules, _focus_order = compiler.parse_module_file(yaml_file)
        assert modules[0].name == "test"

    @pytest.mark.parametrize("count", [1, 3, 5])
    def test_file_with_n_modules(self, compiler: Compiler, tmp_path: Path, count: int) -> None:
        lines = ["modules:"]
        for i in range(count):
            lines.append(f"  - name: mod{i}")
        yaml_file = tmp_path / "multi.yaml"
        yaml_file.write_text("\n".join(lines) + "\n")
        modules, _focus_order = compiler.parse_module_file(yaml_file)
        assert len(modules) == count

    def test_empty_focus_order_list(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "empty_focus.yaml"
        yaml_file.write_text("modules:\n  - name: test\nfocus_order: []\n")
        _modules, focus_order = compiler.parse_module_file(yaml_file)
        assert focus_order == []

    def test_focus_order_with_many_modules(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "many_focus.yaml"
        module_lines = "\n".join(f"  - name: mod{i}" for i in range(8))
        focus_lines = "\n".join(f"  - mod{i}" for i in range(8))
        yaml_file.write_text(f"modules:\n{module_lines}\nfocus_order:\n{focus_lines}\n")
        modules, focus_order = compiler.parse_module_file(yaml_file)
        assert len(modules) == 8
        assert len(focus_order) == 8


# ---------------------------------------------------------------------------
# Integration: compile_module + parse_module_file
# ---------------------------------------------------------------------------


class TestModuleCompileIntegration:
    """Tests that parsed modules compile correctly."""

    def test_parsed_module_compiles(self, compiler: Compiler, sample_modules_path: Path) -> None:
        modules, _focus_order = compiler.parse_module_file(sample_modules_path)
        result = compiler.compile_module(modules[0])
        assert "(defmodule governance" in result
        assert "(import MAIN ?ALL)" in result

    def test_parsed_focus_order_compiles(
        self, compiler: Compiler, sample_modules_path: Path
    ) -> None:
        _modules, focus_order = compiler.parse_module_file(sample_modules_path)
        result = compiler.compile_focus_stack(focus_order)
        assert result == "(focus governance)"

    def test_multiple_parsed_modules_compile(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "multi.yaml"
        yaml_file.write_text(
            "modules:\n"
            "  - name: classification\n"
            "  - name: governance\n"
            "  - name: routing\n"
            "focus_order:\n"
            "  - classification\n"
            "  - governance\n"
            "  - routing\n"
        )
        modules, focus_order = compiler.parse_module_file(yaml_file)
        for mod in modules:
            result = compiler.compile_module(mod)
            assert f"(defmodule {mod.name}" in result
        focus = compiler.compile_focus_stack(focus_order)
        assert focus == "(focus routing governance classification)"
