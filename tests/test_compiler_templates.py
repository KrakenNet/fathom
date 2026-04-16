"""Unit tests for template compilation and YAML parsing in Compiler."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fathom.errors import CompilationError
from fathom.models import SlotDefinition, SlotType, TemplateDefinition

if TYPE_CHECKING:
    from pathlib import Path

    from fathom.compiler import Compiler

# ---------------------------------------------------------------------------
# compile_template tests
# ---------------------------------------------------------------------------


class TestCompileTemplateSlotTypes:
    """Tests for slot type compilation."""

    @pytest.mark.parametrize(
        "slot_type,clips_type",
        [
            (SlotType.STRING, "STRING"),
            (SlotType.SYMBOL, "SYMBOL"),
            (SlotType.FLOAT, "FLOAT"),
            (SlotType.INTEGER, "INTEGER"),
        ],
    )
    def test_slot_type_compiles_to_clips_type(
        self, compiler: Compiler, slot_type: SlotType, clips_type: str
    ) -> None:
        defn = TemplateDefinition(
            name="test",
            slots=[SlotDefinition(name="field", type=slot_type)],
        )
        result = compiler.compile_template(defn)
        assert f"(type {clips_type})" in result

    @pytest.mark.parametrize(
        "slot_type,clips_type",
        [
            (SlotType.STRING, "STRING"),
            (SlotType.SYMBOL, "SYMBOL"),
            (SlotType.FLOAT, "FLOAT"),
            (SlotType.INTEGER, "INTEGER"),
        ],
    )
    def test_slot_type_with_default(
        self, compiler: Compiler, slot_type: SlotType, clips_type: str
    ) -> None:
        defn = TemplateDefinition(
            name="test",
            slots=[
                SlotDefinition(
                    name="field",
                    type=slot_type,
                    default="hello" if slot_type == SlotType.STRING else 42,
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert f"(type {clips_type})" in result
        assert "(default " in result

    @pytest.mark.parametrize(
        "slot_type",
        [SlotType.STRING, SlotType.SYMBOL, SlotType.FLOAT, SlotType.INTEGER],
    )
    def test_single_slot_structure(self, compiler: Compiler, slot_type: SlotType) -> None:
        defn = TemplateDefinition(
            name="single",
            slots=[SlotDefinition(name="val", type=slot_type)],
        )
        result = compiler.compile_template(defn)
        assert result.startswith("(deftemplate MAIN::single")
        assert "(slot val " in result
        assert result.strip().endswith(")")


class TestCompileTemplateDefaults:
    """Tests for default value compilation."""

    def test_string_default_quoted(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[SlotDefinition(name="s", type=SlotType.STRING, default="hello")],
        )
        result = compiler.compile_template(defn)
        assert '(default "hello")' in result

    def test_symbol_default_unquoted(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[SlotDefinition(name="s", type=SlotType.SYMBOL, default="active")],
        )
        result = compiler.compile_template(defn)
        assert "(default active)" in result

    def test_integer_default(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[SlotDefinition(name="s", type=SlotType.INTEGER, default=42)],
        )
        result = compiler.compile_template(defn)
        assert "(default 42)" in result

    def test_float_default(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[SlotDefinition(name="s", type=SlotType.FLOAT, default=3.14)],
        )
        result = compiler.compile_template(defn)
        assert "(default 3.14)" in result

    def test_no_default_omitted(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[SlotDefinition(name="s", type=SlotType.STRING)],
        )
        result = compiler.compile_template(defn)
        assert "default" not in result

    def test_string_default_with_quotes_escaped(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="s",
                    type=SlotType.STRING,
                    default='say "hi"',
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert r"say \"hi\"" in result

    def test_string_default_with_backslash_escaped(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="s",
                    type=SlotType.STRING,
                    default="path\\to\\file",
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert "path\\\\to\\\\file" in result

    def test_zero_default_is_included(self, compiler: Compiler) -> None:
        """Default of 0 should not be treated as None."""
        defn = TemplateDefinition(
            name="t",
            slots=[SlotDefinition(name="s", type=SlotType.INTEGER, default=0)],
        )
        result = compiler.compile_template(defn)
        assert "(default 0)" in result


class TestCompileTemplateAllowedValues:
    """Tests for allowed_values constraint compilation."""

    def test_string_allowed_values(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="status",
                    type=SlotType.STRING,
                    allowed_values=["active", "inactive"],
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert '(allowed-strings "active" "inactive")' in result

    def test_symbol_allowed_values(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="status",
                    type=SlotType.SYMBOL,
                    allowed_values=["active", "inactive"],
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert "(allowed-symbols active inactive)" in result

    def test_string_allowed_values_with_quotes(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="msg",
                    type=SlotType.STRING,
                    allowed_values=['say "hi"', "ok"],
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert r"\"hi\"" in result

    def test_float_allowed_values_ignored(self, compiler: Compiler) -> None:
        """Float type has no allowed-values directive in CLIPS."""
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="val",
                    type=SlotType.FLOAT,
                    allowed_values=["1.0", "2.0"],
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert "allowed-" not in result

    def test_integer_allowed_values_ignored(self, compiler: Compiler) -> None:
        """Integer type has no allowed-values directive in CLIPS."""
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="val",
                    type=SlotType.INTEGER,
                    allowed_values=["1", "2"],
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert "allowed-" not in result

    def test_no_allowed_values_omitted(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[SlotDefinition(name="s", type=SlotType.SYMBOL)],
        )
        result = compiler.compile_template(defn)
        assert "allowed-" not in result

    def test_single_allowed_value_string(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="s",
                    type=SlotType.STRING,
                    allowed_values=["only"],
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert '(allowed-strings "only")' in result

    def test_single_allowed_value_symbol(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="s",
                    type=SlotType.SYMBOL,
                    allowed_values=["only"],
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert "(allowed-symbols only)" in result

    @pytest.mark.parametrize(
        "vals",
        [
            ["a", "b", "c"],
            ["x", "y"],
            ["alpha", "beta", "gamma", "delta"],
        ],
    )
    def test_multiple_symbol_allowed_values(self, compiler: Compiler, vals: list[str]) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="s",
                    type=SlotType.SYMBOL,
                    allowed_values=vals,
                )
            ],
        )
        result = compiler.compile_template(defn)
        expected = "(allowed-symbols " + " ".join(vals) + ")"
        assert expected in result

    @pytest.mark.parametrize(
        "vals",
        [
            ["a", "b", "c"],
            ["x", "y"],
            ["alpha", "beta", "gamma", "delta"],
        ],
    )
    def test_multiple_string_allowed_values(self, compiler: Compiler, vals: list[str]) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="s",
                    type=SlotType.STRING,
                    allowed_values=vals,
                )
            ],
        )
        result = compiler.compile_template(defn)
        quoted = " ".join(f'"{v}"' for v in vals)
        expected = f"(allowed-strings {quoted})"
        assert expected in result


class TestCompileTemplateMultipleSlots:
    """Tests for templates with multiple slots."""

    def test_two_slots(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="agent",
            slots=[
                SlotDefinition(name="id", type=SlotType.STRING),
                SlotDefinition(name="level", type=SlotType.INTEGER),
            ],
        )
        result = compiler.compile_template(defn)
        assert "(slot id " in result
        assert "(slot level " in result

    def test_three_mixed_type_slots(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="record",
            slots=[
                SlotDefinition(name="name", type=SlotType.STRING),
                SlotDefinition(name="status", type=SlotType.SYMBOL),
                SlotDefinition(name="score", type=SlotType.FLOAT),
            ],
        )
        result = compiler.compile_template(defn)
        assert "(slot name " in result
        assert "(slot status " in result
        assert "(slot score " in result
        assert "(type STRING)" in result
        assert "(type SYMBOL)" in result
        assert "(type FLOAT)" in result

    def test_four_slots_all_types(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="all_types",
            slots=[
                SlotDefinition(name="a", type=SlotType.STRING),
                SlotDefinition(name="b", type=SlotType.SYMBOL),
                SlotDefinition(name="c", type=SlotType.FLOAT),
                SlotDefinition(name="d", type=SlotType.INTEGER),
            ],
        )
        result = compiler.compile_template(defn)
        for slot_name in ("a", "b", "c", "d"):
            assert f"(slot {slot_name} " in result

    def test_slots_with_mixed_defaults_and_allowed(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="mixed",
            slots=[
                SlotDefinition(
                    name="role",
                    type=SlotType.SYMBOL,
                    allowed_values=["admin", "user"],
                    default="user",
                ),
                SlotDefinition(
                    name="age",
                    type=SlotType.INTEGER,
                    default=0,
                ),
                SlotDefinition(name="label", type=SlotType.STRING),
            ],
        )
        result = compiler.compile_template(defn)
        assert "(allowed-symbols admin user)" in result
        assert "(default user)" in result
        assert "(default 0)" in result
        assert "(slot label " in result

    @pytest.mark.parametrize("count", [1, 2, 5, 10])
    def test_n_slots_appear_in_output(self, compiler: Compiler, count: int) -> None:
        slots = [SlotDefinition(name=f"s{i}", type=SlotType.STRING) for i in range(count)]
        defn = TemplateDefinition(name="many", slots=slots)
        result = compiler.compile_template(defn)
        for i in range(count):
            assert f"(slot s{i} " in result

    def test_slot_order_preserved(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="ordered",
            slots=[
                SlotDefinition(name="first", type=SlotType.STRING),
                SlotDefinition(name="second", type=SlotType.SYMBOL),
                SlotDefinition(name="third", type=SlotType.INTEGER),
            ],
        )
        result = compiler.compile_template(defn)
        pos_first = result.index("(slot first ")
        pos_second = result.index("(slot second ")
        pos_third = result.index("(slot third ")
        assert pos_first < pos_second < pos_third


class TestCompileTemplateStructure:
    """Tests for overall deftemplate structure."""

    def test_deftemplate_name(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="my_template",
            slots=[SlotDefinition(name="x", type=SlotType.STRING)],
        )
        result = compiler.compile_template(defn)
        assert result.startswith("(deftemplate MAIN::my_template")

    def test_starts_with_open_paren(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[SlotDefinition(name="x", type=SlotType.STRING)],
        )
        result = compiler.compile_template(defn)
        assert result[0] == "("

    def test_ends_with_close_paren(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[SlotDefinition(name="x", type=SlotType.STRING)],
        )
        result = compiler.compile_template(defn)
        assert result.rstrip().endswith(")")

    def test_output_is_multiline(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(name="a", type=SlotType.STRING),
                SlotDefinition(name="b", type=SlotType.INTEGER),
            ],
        )
        result = compiler.compile_template(defn)
        assert "\n" in result

    def test_indentation(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[SlotDefinition(name="x", type=SlotType.STRING)],
        )
        result = compiler.compile_template(defn)
        lines = result.split("\n")
        # Slot lines should be indented
        for line in lines[1:-1]:
            assert line.startswith("    ")

    @pytest.mark.parametrize(
        "name",
        ["agent", "data_request", "my-template", "template123", "T"],
    )
    def test_various_template_names(self, compiler: Compiler, name: str) -> None:
        defn = TemplateDefinition(
            name=name,
            slots=[SlotDefinition(name="x", type=SlotType.STRING)],
        )
        result = compiler.compile_template(defn)
        assert f"(deftemplate MAIN::{name}" in result


class TestCompileTemplateValidation:
    """Tests for invalid input validation."""

    def test_empty_name_raises(self, compiler: Compiler) -> None:
        # Empty name now rejected at the Pydantic model layer.
        with pytest.raises(ValueError, match="valid CLIPS identifier"):
            TemplateDefinition(
                name="",
                slots=[SlotDefinition(name="x", type=SlotType.STRING)],
            )

    def test_empty_slots_raises(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(name="t", slots=[])
        with pytest.raises(CompilationError, match="no slots"):
            compiler.compile_template(defn)

    def test_empty_name_error_has_construct(self, compiler: Compiler) -> None:
        with pytest.raises(ValueError, match="TemplateDefinition.name"):
            TemplateDefinition(
                name="",
                slots=[SlotDefinition(name="x", type=SlotType.STRING)],
            )

    def test_empty_slots_error_has_construct(self, compiler: Compiler) -> None:
        defn = TemplateDefinition(name="bad", slots=[])
        with pytest.raises(CompilationError) as exc_info:
            compiler.compile_template(defn)
        assert "bad" in (exc_info.value.construct or "")


class TestCompileTemplateEscaping:
    """Tests for string escaping in compilation output."""

    @pytest.mark.parametrize(
        "input_str,expected_fragment",
        [
            ("hello", '"hello"'),
            ('say "yes"', r'"say \"yes\""'),
            ("back\\slash", '"back\\\\slash"'),
            ('both "and" \\', r'"both \"and\" \\"'),
            ("", '""'),
        ],
    )
    def test_string_default_escaping(
        self, compiler: Compiler, input_str: str, expected_fragment: str
    ) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="s",
                    type=SlotType.STRING,
                    default=input_str,
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert f"(default {expected_fragment})" in result

    @pytest.mark.parametrize(
        "input_str,expected_fragment",
        [
            ("hello", '"hello"'),
            ('say "hi"', r'"say \"hi\""'),
            ("back\\slash", '"back\\\\slash"'),
        ],
    )
    def test_string_allowed_value_escaping(
        self, compiler: Compiler, input_str: str, expected_fragment: str
    ) -> None:
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="s",
                    type=SlotType.STRING,
                    allowed_values=[input_str],
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert expected_fragment in result


class TestCompileTemplateCombinations:
    """Parametrized combination tests for slot type x feature."""

    @pytest.mark.parametrize("slot_type", [SlotType.STRING, SlotType.SYMBOL])
    @pytest.mark.parametrize(
        "allowed",
        [["a"], ["a", "b"], ["x", "y", "z"]],
    )
    def test_slot_type_with_allowed_values(
        self,
        compiler: Compiler,
        slot_type: SlotType,
        allowed: list[str],
    ) -> None:
        defn = TemplateDefinition(
            name="combo",
            slots=[
                SlotDefinition(
                    name="f",
                    type=slot_type,
                    allowed_values=allowed,
                )
            ],
        )
        result = compiler.compile_template(defn)
        if slot_type == SlotType.STRING:
            assert "allowed-strings" in result
        else:
            assert "allowed-symbols" in result

    @pytest.mark.parametrize(
        "slot_type,default",
        [
            (SlotType.STRING, "test"),
            (SlotType.SYMBOL, "active"),
            (SlotType.FLOAT, 1.5),
            (SlotType.INTEGER, 10),
        ],
    )
    def test_slot_type_with_default_combination(
        self,
        compiler: Compiler,
        slot_type: SlotType,
        default: str | float | int,
    ) -> None:
        defn = TemplateDefinition(
            name="combo",
            slots=[
                SlotDefinition(
                    name="f",
                    type=slot_type,
                    default=default,
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert "(default " in result

    @pytest.mark.parametrize("required", [True, False])
    @pytest.mark.parametrize("slot_type", [SlotType.STRING, SlotType.SYMBOL])
    def test_required_flag_does_not_affect_clips_output(
        self,
        compiler: Compiler,
        required: bool,
        slot_type: SlotType,
    ) -> None:
        """required is enforced in Python, not in CLIPS deftemplate."""
        defn = TemplateDefinition(
            name="t",
            slots=[
                SlotDefinition(
                    name="f",
                    type=slot_type,
                    required=required,
                )
            ],
        )
        result = compiler.compile_template(defn)
        assert "required" not in result.lower()


# ---------------------------------------------------------------------------
# parse_template_file tests
# ---------------------------------------------------------------------------


class TestParseTemplateFileValid:
    """Tests for valid YAML template file parsing."""

    def test_parses_fixture_file(self, compiler: Compiler, sample_template_path: Path) -> None:
        result = compiler.parse_template_file(sample_template_path)
        assert len(result) == 2
        assert result[0].name == "agent"
        assert result[1].name == "data_request"

    def test_fixture_slot_types(self, compiler: Compiler, sample_template_path: Path) -> None:
        result = compiler.parse_template_file(sample_template_path)
        agent = result[0]
        assert agent.slots[0].name == "id"
        assert agent.slots[0].type == SlotType.STRING
        assert agent.slots[1].name == "clearance"
        assert agent.slots[1].type == SlotType.SYMBOL

    def test_fixture_allowed_values(self, compiler: Compiler, sample_template_path: Path) -> None:
        result = compiler.parse_template_file(sample_template_path)
        clearance_slot = result[0].slots[1]
        assert clearance_slot.allowed_values is not None
        assert "secret" in clearance_slot.allowed_values

    def test_single_template_file(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "single.yaml"
        yaml_file.write_text(
            "templates:\n  - name: one\n    slots:\n      - name: x\n        type: string\n"
        )
        result = compiler.parse_template_file(yaml_file)
        assert len(result) == 1
        assert result[0].name == "one"

    def test_multiple_templates_file(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "multi.yaml"
        yaml_file.write_text(
            "templates:\n"
            "  - name: a\n"
            "    slots:\n"
            "      - name: x\n"
            "        type: string\n"
            "  - name: b\n"
            "    slots:\n"
            "      - name: y\n"
            "        type: integer\n"
        )
        result = compiler.parse_template_file(yaml_file)
        assert len(result) == 2
        assert result[0].name == "a"
        assert result[1].name == "b"

    def test_template_with_all_slot_features(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "full.yaml"
        yaml_file.write_text(
            "templates:\n"
            "  - name: full\n"
            "    slots:\n"
            "      - name: status\n"
            "        type: symbol\n"
            "        allowed_values: [active, inactive]\n"
            "        default: active\n"
            "        required: true\n"
        )
        result = compiler.parse_template_file(yaml_file)
        slot = result[0].slots[0]
        assert slot.name == "status"
        assert slot.type == SlotType.SYMBOL
        assert slot.allowed_values == ["active", "inactive"]
        assert slot.default == "active"
        assert slot.required is True

    def test_template_with_description(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "desc.yaml"
        yaml_file.write_text(
            "templates:\n"
            "  - name: t\n"
            "    description: A test template\n"
            "    slots:\n"
            "      - name: x\n"
            "        type: string\n"
        )
        result = compiler.parse_template_file(yaml_file)
        assert result[0].description == "A test template"

    def test_returns_template_definition_objects(
        self, compiler: Compiler, sample_template_path: Path
    ) -> None:
        result = compiler.parse_template_file(sample_template_path)
        assert all(isinstance(t, TemplateDefinition) for t in result)


class TestParseTemplateFileErrors:
    """Tests for parse_template_file error cases."""

    def test_invalid_yaml_syntax(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("templates:\n  - name: [invalid yaml\n")
        with pytest.raises(CompilationError, match="(?i)invalid YAML"):
            compiler.parse_template_file(yaml_file)

    def test_missing_templates_key(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "no_key.yaml"
        yaml_file.write_text("rules:\n  - name: x\n")
        with pytest.raises(CompilationError, match="templates"):
            compiler.parse_template_file(yaml_file)

    def test_templates_not_a_list(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "not_list.yaml"
        yaml_file.write_text("templates:\n  name: x\n")
        with pytest.raises(CompilationError, match="list"):
            compiler.parse_template_file(yaml_file)

    def test_template_entry_not_a_dict(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "not_dict.yaml"
        yaml_file.write_text("templates:\n  - just a string\n")
        with pytest.raises(CompilationError, match="not a mapping"):
            compiler.parse_template_file(yaml_file)

    def test_duplicate_template_names(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "dup.yaml"
        yaml_file.write_text(
            "templates:\n"
            "  - name: same\n"
            "    slots:\n"
            "      - name: x\n"
            "        type: string\n"
            "  - name: same\n"
            "    slots:\n"
            "      - name: y\n"
            "        type: string\n"
        )
        with pytest.raises(CompilationError, match="(?i)duplicate"):
            compiler.parse_template_file(yaml_file)

    def test_missing_name_field(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "no_name.yaml"
        yaml_file.write_text("templates:\n  - slots:\n      - name: x\n        type: string\n")
        with pytest.raises(CompilationError, match="(?i)invalid template"):
            compiler.parse_template_file(yaml_file)

    def test_missing_slots_field(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "no_slots.yaml"
        yaml_file.write_text("templates:\n  - name: t\n")
        with pytest.raises(CompilationError, match="(?i)invalid template"):
            compiler.parse_template_file(yaml_file)

    def test_unknown_slot_type(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad_type.yaml"
        yaml_file.write_text(
            "templates:\n  - name: t\n    slots:\n      - name: x\n        type: boolean\n"
        )
        with pytest.raises(CompilationError, match="(?i)invalid template"):
            compiler.parse_template_file(yaml_file)

    def test_nonexistent_file(self, compiler: Compiler, tmp_path: Path) -> None:
        with pytest.raises(CompilationError, match="(?i)cannot read"):
            compiler.parse_template_file(tmp_path / "missing.yaml")

    def test_empty_yaml_file(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        with pytest.raises(CompilationError, match="templates"):
            compiler.parse_template_file(yaml_file)

    def test_yaml_with_only_null(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "null.yaml"
        yaml_file.write_text("null\n")
        with pytest.raises(CompilationError, match="templates"):
            compiler.parse_template_file(yaml_file)

    def test_error_includes_file_path(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "err.yaml"
        yaml_file.write_text("not_templates: []\n")
        with pytest.raises(CompilationError) as exc_info:
            compiler.parse_template_file(yaml_file)
        assert exc_info.value.file is not None
        assert "err.yaml" in exc_info.value.file

    def test_duplicate_error_includes_construct(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "dup2.yaml"
        yaml_file.write_text(
            "templates:\n"
            "  - name: dup\n"
            "    slots:\n"
            "      - name: x\n"
            "        type: string\n"
            "  - name: dup\n"
            "    slots:\n"
            "      - name: y\n"
            "        type: string\n"
        )
        with pytest.raises(CompilationError) as exc_info:
            compiler.parse_template_file(yaml_file)
        assert "dup" in (exc_info.value.construct or "")

    @pytest.mark.parametrize(
        "content,match_str",
        [
            ("templates: {}", "list"),
            ("templates: 42", "list"),
            ("templates: hello", "list"),
        ],
    )
    def test_templates_various_non_list_types(
        self,
        compiler: Compiler,
        tmp_path: Path,
        content: str,
        match_str: str,
    ) -> None:
        yaml_file = tmp_path / "non_list.yaml"
        yaml_file.write_text(content + "\n")
        with pytest.raises(CompilationError, match=match_str):
            compiler.parse_template_file(yaml_file)

    def test_invalid_yaml_tabs(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "tabs.yaml"
        yaml_file.write_text("templates:\n\t- name: bad\n")
        with pytest.raises(CompilationError, match="(?i)invalid YAML"):
            compiler.parse_template_file(yaml_file)


class TestParseTemplateFileEdgeCases:
    """Edge case tests for template file parsing."""

    def test_template_with_extra_keys_ignored(self, compiler: Compiler, tmp_path: Path) -> None:
        """Pydantic ignores extra keys by default."""
        yaml_file = tmp_path / "extra.yaml"
        yaml_file.write_text(
            "templates:\n"
            "  - name: t\n"
            "    extra_key: ignored\n"
            "    slots:\n"
            "      - name: x\n"
            "        type: string\n"
        )
        result = compiler.parse_template_file(yaml_file)
        assert result[0].name == "t"

    def test_slot_missing_type_raises(self, compiler: Compiler, tmp_path: Path) -> None:
        """SlotType is required; omitting it raises CompilationError."""
        yaml_file = tmp_path / "no_type.yaml"
        yaml_file.write_text("templates:\n  - name: t\n    slots:\n      - name: x\n")
        with pytest.raises(CompilationError, match="(?i)invalid template"):
            compiler.parse_template_file(yaml_file)

    @pytest.mark.parametrize("count", [1, 3, 5])
    def test_file_with_n_templates(self, compiler: Compiler, tmp_path: Path, count: int) -> None:
        lines = ["templates:"]
        for i in range(count):
            lines.extend(
                [
                    f"  - name: t{i}",
                    "    slots:",
                    f"      - name: s{i}",
                    "        type: string",
                ]
            )
        yaml_file = tmp_path / "multi.yaml"
        yaml_file.write_text("\n".join(lines) + "\n")
        result = compiler.parse_template_file(yaml_file)
        assert len(result) == count

    def test_template_with_many_slots(self, compiler: Compiler, tmp_path: Path) -> None:
        lines = [
            "templates:",
            "  - name: big",
            "    slots:",
        ]
        for i in range(10):
            lines.extend(
                [
                    f"      - name: field{i}",
                    "        type: string",
                ]
            )
        yaml_file = tmp_path / "big.yaml"
        yaml_file.write_text("\n".join(lines) + "\n")
        result = compiler.parse_template_file(yaml_file)
        assert len(result[0].slots) == 10
