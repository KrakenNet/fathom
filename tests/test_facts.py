"""Fact assertion and validation tests for FactManager (~80 tests).

Tests cover:
- Valid assertion with all slot types
- Missing required slot raises ValidationError
- Unknown slot name raises ValidationError
- Invalid allowed_values raises ValidationError
- Type mismatch raises ValidationError
- Default value application
- Bulk assert atomicity
- Assertion against unknown template
- Type coercion (int->float, float->int, any->str)
- Bool rejection for integer/float slots
"""

from __future__ import annotations

import pytest

from fathom.engine import Engine
from fathom.errors import ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_with_templates(tmp_path, yaml_str: str) -> Engine:
    """Create an Engine with templates from a YAML string."""
    p = tmp_path / "templates.yaml"
    p.write_text(yaml_str)
    e = Engine()
    e.load_templates(str(p))
    return e


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def all_types_engine(tmp_path):
    """Engine with a template using all four slot types."""
    yaml_str = """\
templates:
  - name: all_types
    slots:
      - name: s_string
        type: string
        required: true
      - name: s_symbol
        type: symbol
        required: true
      - name: s_float
        type: float
        required: true
      - name: s_integer
        type: integer
        required: true
"""
    return _engine_with_templates(tmp_path, yaml_str)


@pytest.fixture
def defaults_engine(tmp_path):
    """Engine with a template having default values for each slot type."""
    yaml_str = """\
templates:
  - name: with_defaults
    slots:
      - name: label
        type: string
        default: unnamed
      - name: status
        type: symbol
        default: active
      - name: score
        type: float
        default: 0.0
      - name: count
        type: integer
        default: 1
      - name: tag
        type: string
        required: true
"""
    return _engine_with_templates(tmp_path, yaml_str)


@pytest.fixture
def allowed_engine(tmp_path):
    """Engine with a template using allowed_values for string and symbol."""
    yaml_str = """\
templates:
  - name: constrained
    slots:
      - name: color
        type: string
        allowed_values: [red, green, blue]
      - name: level
        type: symbol
        allowed_values: [low, medium, high]
      - name: id
        type: string
        required: true
"""
    return _engine_with_templates(tmp_path, yaml_str)


@pytest.fixture
def multi_template_engine(tmp_path):
    """Engine with multiple templates for bulk assert tests."""
    yaml_str = """\
templates:
  - name: user
    slots:
      - name: name
        type: string
        required: true
      - name: age
        type: integer
        required: true
  - name: item
    slots:
      - name: label
        type: string
        required: true
      - name: weight
        type: float
"""
    return _engine_with_templates(tmp_path, yaml_str)


@pytest.fixture
def coercion_engine(tmp_path):
    """Engine with a template for testing type coercion."""
    yaml_str = """\
templates:
  - name: coerce
    slots:
      - name: f_val
        type: float
      - name: i_val
        type: integer
      - name: s_val
        type: string
"""
    return _engine_with_templates(tmp_path, yaml_str)


@pytest.fixture
def optional_engine(tmp_path):
    """Engine with a template that has all optional slots."""
    yaml_str = """\
templates:
  - name: optional
    slots:
      - name: a
        type: string
      - name: b
        type: integer
      - name: c
        type: float
      - name: d
        type: symbol
"""
    return _engine_with_templates(tmp_path, yaml_str)


# ===========================================================================
# 1. Valid assertion with all slot types
# ===========================================================================


class TestValidAssertionAllTypes:
    """Valid assertions for each slot type and combinations."""

    def test_assert_string_slot(self, all_types_engine):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": "hello",
                "s_symbol": "sym",
                "s_float": 1.5,
                "s_integer": 42,
            },
        )
        facts = all_types_engine.query("all_types")
        assert len(facts) == 1
        assert facts[0]["s_string"] == "hello"

    def test_assert_symbol_slot(self, all_types_engine):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": "x",
                "s_symbol": "mysym",
                "s_float": 0.0,
                "s_integer": 0,
            },
        )
        facts = all_types_engine.query("all_types")
        assert facts[0]["s_symbol"] == "mysym"

    def test_assert_float_slot(self, all_types_engine):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": "x",
                "s_symbol": "s",
                "s_float": 3.14,
                "s_integer": 1,
            },
        )
        facts = all_types_engine.query("all_types")
        assert facts[0]["s_float"] == pytest.approx(3.14)

    def test_assert_integer_slot(self, all_types_engine):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": "x",
                "s_symbol": "s",
                "s_float": 1.0,
                "s_integer": 99,
            },
        )
        facts = all_types_engine.query("all_types")
        assert facts[0]["s_integer"] == 99

    @pytest.mark.parametrize(
        "s_string,s_symbol,s_float,s_integer",
        [
            ("", "a", 0.0, 0),
            ("long string with spaces", "sym_with_underscores", 999999.99, -42),
            ("special!@#", "x", -1.5, 1),
            ("unicode_\u00e9", "ok", 0.001, 2147483647),
        ],
    )
    def test_assert_various_values(self, all_types_engine, s_string, s_symbol, s_float, s_integer):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": s_string,
                "s_symbol": s_symbol,
                "s_float": s_float,
                "s_integer": s_integer,
            },
        )
        facts = all_types_engine.query("all_types")
        assert len(facts) >= 1

    def test_assert_multiple_facts(self, all_types_engine):
        for i in range(3):
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": f"item{i}",
                    "s_symbol": "s",
                    "s_float": float(i),
                    "s_integer": i,
                },
            )
        facts = all_types_engine.query("all_types")
        assert len(facts) == 3

    def test_assert_optional_slots_omitted(self, optional_engine):
        """Asserting with no data should work when all slots are optional."""
        optional_engine.assert_fact("optional", {})
        facts = optional_engine.query("optional")
        assert len(facts) == 1


# ===========================================================================
# 2. Missing required slot raises ValidationError
# ===========================================================================


class TestMissingRequired:
    """Missing required slots must raise ValidationError."""

    @pytest.mark.parametrize(
        "missing_slot,data",
        [
            ("s_string", {"s_symbol": "s", "s_float": 1.0, "s_integer": 1}),
            ("s_symbol", {"s_string": "x", "s_float": 1.0, "s_integer": 1}),
            ("s_float", {"s_string": "x", "s_symbol": "s", "s_integer": 1}),
            ("s_integer", {"s_string": "x", "s_symbol": "s", "s_float": 1.0}),
        ],
    )
    def test_missing_single_required(self, all_types_engine, missing_slot, data):
        with pytest.raises(ValidationError, match="Missing required"):
            all_types_engine.assert_fact("all_types", data)

    def test_missing_all_required(self, all_types_engine):
        with pytest.raises(ValidationError, match="Missing required"):
            all_types_engine.assert_fact("all_types", {})

    def test_missing_required_has_template_attr(self, all_types_engine):
        with pytest.raises(ValidationError) as exc_info:
            all_types_engine.assert_fact("all_types", {})
        assert exc_info.value.template == "all_types"

    def test_missing_required_has_slot_attr(self, all_types_engine):
        with pytest.raises(ValidationError) as exc_info:
            all_types_engine.assert_fact(
                "all_types", {"s_symbol": "s", "s_float": 1.0, "s_integer": 1}
            )
        assert exc_info.value.slot == "s_string"

    def test_missing_required_with_defaults_present(self, defaults_engine):
        """Required slot 'tag' is missing even though defaulted slots are fine."""
        with pytest.raises(ValidationError, match="Missing required"):
            defaults_engine.assert_fact("with_defaults", {})


# ===========================================================================
# 3. Unknown slot name raises ValidationError
# ===========================================================================


class TestUnknownSlot:
    """Unknown slot names must raise ValidationError with typo suggestions."""

    def test_unknown_slot_raises(self, all_types_engine):
        with pytest.raises(ValidationError, match="Unknown slot"):
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": 1.0,
                    "s_integer": 1,
                    "nonexistent": "val",
                },
            )

    def test_unknown_slot_with_typo_suggestion(self, all_types_engine):
        """A close typo should trigger 'Did you mean' suggestion."""
        with pytest.raises(ValidationError, match="Did you mean"):
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": 1.0,
                    "s_integer": 1,
                    "s_striing": "val",
                },
            )

    @pytest.mark.parametrize(
        "bad_slot",
        [
            "unknown",
            "foo_bar",
            "S_STRING",
            "s-string",
            "string",
        ],
    )
    def test_various_unknown_slots(self, all_types_engine, bad_slot):
        with pytest.raises(ValidationError, match="Unknown slot"):
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": 1.0,
                    "s_integer": 1,
                    bad_slot: "val",
                },
            )

    def test_unknown_slot_has_template_attr(self, all_types_engine):
        with pytest.raises(ValidationError) as exc_info:
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": 1.0,
                    "s_integer": 1,
                    "bogus": "val",
                },
            )
        assert exc_info.value.template == "all_types"

    def test_unknown_slot_has_slot_attr(self, all_types_engine):
        with pytest.raises(ValidationError) as exc_info:
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": 1.0,
                    "s_integer": 1,
                    "bogus": "val",
                },
            )
        assert exc_info.value.slot == "bogus"


# ===========================================================================
# 4. Invalid allowed_values raises ValidationError
# ===========================================================================


class TestAllowedValues:
    """Allowed values enforcement for string and symbol slots."""

    def test_valid_string_allowed(self, allowed_engine):
        allowed_engine.assert_fact("constrained", {"id": "1", "color": "red"})
        facts = allowed_engine.query("constrained")
        assert facts[0]["color"] == "red"

    def test_valid_symbol_allowed(self, allowed_engine):
        allowed_engine.assert_fact("constrained", {"id": "1", "level": "high"})
        facts = allowed_engine.query("constrained")
        assert facts[0]["level"] == "high"

    @pytest.mark.parametrize("color", ["yellow", "purple", "RED", ""])
    def test_invalid_string_allowed_values(self, allowed_engine, color):
        with pytest.raises(ValidationError, match="not in allowed values"):
            allowed_engine.assert_fact("constrained", {"id": "1", "color": color})

    @pytest.mark.parametrize("level", ["critical", "none", "HIGH", ""])
    def test_invalid_symbol_allowed_values(self, allowed_engine, level):
        with pytest.raises(ValidationError, match="not in allowed values"):
            allowed_engine.assert_fact("constrained", {"id": "1", "level": level})

    def test_allowed_values_error_has_value_attr(self, allowed_engine):
        with pytest.raises(ValidationError) as exc_info:
            allowed_engine.assert_fact("constrained", {"id": "1", "color": "orange"})
        assert exc_info.value.value == "orange"
        assert exc_info.value.slot == "color"

    @pytest.mark.parametrize("valid_color", ["red", "green", "blue"])
    def test_all_valid_string_values(self, allowed_engine, valid_color):
        allowed_engine.assert_fact("constrained", {"id": f"c-{valid_color}", "color": valid_color})
        facts = allowed_engine.query("constrained", {"color": valid_color})
        assert len(facts) == 1

    @pytest.mark.parametrize("valid_level", ["low", "medium", "high"])
    def test_all_valid_symbol_values(self, allowed_engine, valid_level):
        allowed_engine.assert_fact("constrained", {"id": f"l-{valid_level}", "level": valid_level})
        facts = allowed_engine.query("constrained", {"level": valid_level})
        assert len(facts) == 1


# ===========================================================================
# 5. Type mismatch raises ValidationError
# ===========================================================================


class TestTypeMismatch:
    """Type mismatch detection for all slot types."""

    @pytest.mark.parametrize(
        "slot_name,bad_value,expected_type",
        [
            # Note: int/float for s_string are coerced to str, so not type errors
            ("s_symbol", 123, "symbol"),
            ("s_symbol", 1.5, "symbol"),
            ("s_float", "not_a_number", "float"),
            ("s_integer", "not_a_number", "integer"),
            ("s_integer", 1.5, "integer"),
        ],
    )
    def test_type_mismatch_raises(self, all_types_engine, slot_name, bad_value, expected_type):
        """Supplying wrong type for each slot raises ValidationError."""
        data = {
            "s_string": "x",
            "s_symbol": "s",
            "s_float": 1.0,
            "s_integer": 1,
        }
        data[slot_name] = bad_value
        with pytest.raises(ValidationError, match="expects"):
            all_types_engine.assert_fact("all_types", data)

    @pytest.mark.parametrize("bad_value", [123, 1.5, True])
    def test_non_string_coerced_for_string_slot(self, all_types_engine, bad_value):
        """Non-string values for string slots are coerced to str, not rejected."""
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": bad_value,
                "s_symbol": "s",
                "s_float": 1.0,
                "s_integer": 1,
            },
        )
        facts = all_types_engine.query("all_types")
        assert facts[0]["s_string"] == str(bad_value)

    def test_type_error_has_expected_attr(self, all_types_engine):
        with pytest.raises(ValidationError) as exc_info:
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": "bad",
                    "s_integer": 1,
                },
            )
        assert exc_info.value.expected == "float"
        assert exc_info.value.slot == "s_float"

    def test_type_error_has_value_attr(self, all_types_engine):
        with pytest.raises(ValidationError) as exc_info:
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": 1.0,
                    "s_integer": "bad",
                },
            )
        assert exc_info.value.value == "bad"

    @pytest.mark.parametrize(
        "bad_value",
        [
            [1, 2, 3],
            {"nested": "dict"},
            None,
        ],
    )
    def test_exotic_type_mismatches_integer(self, all_types_engine, bad_value):
        data = {"s_string": "x", "s_symbol": "s", "s_float": 1.0, "s_integer": bad_value}
        with pytest.raises((ValidationError, TypeError)):
            all_types_engine.assert_fact("all_types", data)


# ===========================================================================
# 6. Bool rejection for integer and float slots
# ===========================================================================


class TestBoolRejection:
    """Bool should be rejected for INTEGER and FLOAT slots despite bool being int subclass."""

    def test_bool_rejected_for_integer(self, all_types_engine):
        with pytest.raises(ValidationError, match="expects integer"):
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": 1.0,
                    "s_integer": True,
                },
            )

    def test_bool_rejected_for_integer_false(self, all_types_engine):
        with pytest.raises(ValidationError, match="expects integer"):
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": 1.0,
                    "s_integer": False,
                },
            )

    def test_bool_rejected_for_float(self, all_types_engine):
        with pytest.raises(ValidationError, match="expects float"):
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": True,
                    "s_integer": 1,
                },
            )

    def test_bool_rejected_for_float_false(self, all_types_engine):
        with pytest.raises(ValidationError, match="expects float"):
            all_types_engine.assert_fact(
                "all_types",
                {
                    "s_string": "x",
                    "s_symbol": "s",
                    "s_float": False,
                    "s_integer": 1,
                },
            )


# ===========================================================================
# 7. Default value application
# ===========================================================================


class TestDefaultValues:
    """Default values are applied for missing optional slots."""

    def test_string_default_applied(self, defaults_engine):
        defaults_engine.assert_fact("with_defaults", {"tag": "test"})
        facts = defaults_engine.query("with_defaults")
        assert facts[0]["label"] == "unnamed"

    def test_symbol_default_applied(self, defaults_engine):
        defaults_engine.assert_fact("with_defaults", {"tag": "test"})
        facts = defaults_engine.query("with_defaults")
        assert facts[0]["status"] == "active"

    def test_float_default_applied(self, defaults_engine):
        defaults_engine.assert_fact("with_defaults", {"tag": "test"})
        facts = defaults_engine.query("with_defaults")
        assert facts[0]["score"] == pytest.approx(0.0)

    def test_integer_default_applied(self, defaults_engine):
        defaults_engine.assert_fact("with_defaults", {"tag": "test"})
        facts = defaults_engine.query("with_defaults")
        assert facts[0]["count"] == 1

    def test_explicit_overrides_default(self, defaults_engine):
        defaults_engine.assert_fact(
            "with_defaults", {"tag": "test", "label": "custom", "count": 42}
        )
        facts = defaults_engine.query("with_defaults")
        assert facts[0]["label"] == "custom"
        assert facts[0]["count"] == 42

    @pytest.mark.parametrize(
        "slot,override,expected",
        [
            ("label", "override_str", "override_str"),
            ("status", "inactive", "inactive"),
            ("score", 9.9, 9.9),
            ("count", 100, 100),
        ],
    )
    def test_each_default_overridden(self, defaults_engine, slot, override, expected):
        data = {"tag": "test", slot: override}
        defaults_engine.assert_fact("with_defaults", data)
        facts = defaults_engine.query("with_defaults", {"tag": "test", slot: expected})
        assert len(facts) >= 1


# ===========================================================================
# 8. Bulk assert atomicity
# ===========================================================================


class TestBulkAssert:
    """Bulk assert: all valid passes, one invalid fails all."""

    def test_bulk_assert_all_valid(self, multi_template_engine):
        multi_template_engine.assert_facts(
            [
                ("user", {"name": "Alice", "age": 30}),
                ("user", {"name": "Bob", "age": 25}),
                ("item", {"label": "widget"}),
            ]
        )
        users = multi_template_engine.query("user")
        items = multi_template_engine.query("item")
        assert len(users) == 2
        assert len(items) == 1

    def test_bulk_assert_one_invalid_fails_all(self, multi_template_engine):
        """If second fact is invalid, no facts should be asserted."""
        with pytest.raises(ValidationError):
            multi_template_engine.assert_facts(
                [
                    ("user", {"name": "Alice", "age": 30}),
                    ("user", {"name": "Bob"}),  # missing required 'age'
                    ("item", {"label": "widget"}),
                ]
            )
        # Nothing should have been asserted
        users = multi_template_engine.query("user")
        items = multi_template_engine.query("item")
        assert len(users) == 0
        assert len(items) == 0

    def test_bulk_assert_invalid_at_start(self, multi_template_engine):
        """Invalid first fact should prevent all assertions."""
        with pytest.raises(ValidationError):
            multi_template_engine.assert_facts(
                [
                    ("user", {"name": "Alice"}),  # missing 'age'
                    ("user", {"name": "Bob", "age": 25}),
                ]
            )
        assert multi_template_engine.count("user") == 0

    def test_bulk_assert_invalid_at_end(self, multi_template_engine):
        """Invalid last fact should prevent all assertions."""
        with pytest.raises(ValidationError):
            multi_template_engine.assert_facts(
                [
                    ("user", {"name": "Alice", "age": 30}),
                    ("item", {"label": "widget"}),
                    ("user", {}),  # missing required fields
                ]
            )
        assert multi_template_engine.count("user") == 0
        assert multi_template_engine.count("item") == 0

    def test_bulk_assert_empty_list(self, multi_template_engine):
        """Empty list should succeed without asserting anything."""
        multi_template_engine.assert_facts([])
        assert multi_template_engine.count("user") == 0

    def test_bulk_assert_unknown_template(self, multi_template_engine):
        """Unknown template in bulk assert should fail all."""
        with pytest.raises(ValidationError, match="Unknown template"):
            multi_template_engine.assert_facts(
                [
                    ("user", {"name": "Alice", "age": 30}),
                    ("nonexistent", {"x": 1}),
                ]
            )
        assert multi_template_engine.count("user") == 0

    def test_bulk_assert_type_error_fails_all(self, multi_template_engine):
        """Type mismatch in one fact should fail all."""
        with pytest.raises(ValidationError):
            multi_template_engine.assert_facts(
                [
                    ("user", {"name": "Alice", "age": 30}),
                    ("user", {"name": "Bob", "age": "not_int"}),
                ]
            )
        assert multi_template_engine.count("user") == 0


# ===========================================================================
# 9. Assertion against unknown template
# ===========================================================================


class TestUnknownTemplate:
    """Assertion against unknown template must raise ValidationError."""

    def test_unknown_template_raises(self, all_types_engine):
        with pytest.raises(ValidationError, match="Unknown template"):
            all_types_engine.assert_fact("nonexistent_template", {"key": "val"})

    def test_unknown_template_has_template_attr(self, all_types_engine):
        with pytest.raises(ValidationError) as exc_info:
            all_types_engine.assert_fact("nope", {"key": "val"})
        assert exc_info.value.template == "nope"

    @pytest.mark.parametrize(
        "bad_name",
        [
            "nonexistent",
            "ALLTYPE",
            "all_type",
            "All_Types",
            "",
        ],
    )
    def test_various_unknown_template_names(self, all_types_engine, bad_name):
        with pytest.raises(ValidationError, match="Unknown template"):
            all_types_engine.assert_fact(bad_name, {})


# ===========================================================================
# 10. Type coercion
# ===========================================================================


class TestTypeCoercion:
    """Type coercion: int->float, float->int (if no fractional), any->str."""

    def test_int_for_float_passes_validation_but_clips_rejects(self, coercion_engine):
        """Int for float slot passes Python validation but CLIPS rejects the raw int.

        _coerce_for_clips only handles symbol coercion; int->float is not coerced.
        CLIPS itself rejects the int, so a ValidationError is raised at assertion time.
        """
        with pytest.raises(ValidationError, match="CLIPS assertion failed"):
            coercion_engine.assert_fact("coerce", {"f_val": 5})

    def test_float_coerced_to_int_no_fractional(self, coercion_engine):
        """Supplying 3.0 for integer slot should coerce to int 3."""
        coercion_engine.assert_fact("coerce", {"i_val": 3.0})
        facts = coercion_engine.query("coerce")
        assert facts[0]["i_val"] == 3
        assert isinstance(facts[0]["i_val"], int)

    def test_float_with_fraction_not_coerced_to_int(self, coercion_engine):
        """Supplying 3.5 for integer slot should raise (not coercible)."""
        with pytest.raises(ValidationError, match="expects integer"):
            coercion_engine.assert_fact("coerce", {"i_val": 3.5})

    def test_int_coerced_to_string(self, coercion_engine):
        """Non-string value for string slot should coerce to str."""
        coercion_engine.assert_fact("coerce", {"s_val": 42})
        facts = coercion_engine.query("coerce")
        assert facts[0]["s_val"] == "42"

    def test_float_coerced_to_string(self, coercion_engine):
        coercion_engine.assert_fact("coerce", {"s_val": 3.14})
        facts = coercion_engine.query("coerce")
        assert facts[0]["s_val"] == "3.14"

    @pytest.mark.parametrize("int_val", [0, -1, 100, 2147483647])
    def test_various_ints_for_float_rejected_by_clips(self, coercion_engine, int_val):
        """CLIPS rejects raw int for float-typed slots (no int->float coercion)."""
        with pytest.raises(ValidationError, match="CLIPS assertion failed"):
            coercion_engine.assert_fact("coerce", {"f_val": int_val})

    @pytest.mark.parametrize("float_val", [0.0, -1.0, 100.0])
    def test_various_whole_floats_coerced_to_int(self, coercion_engine, float_val):
        coercion_engine.assert_fact("coerce", {"i_val": float_val})
        facts = coercion_engine.query("coerce", {"i_val": int(float_val)})
        assert len(facts) >= 1


# ===========================================================================
# 11. Query and count after assertion
# ===========================================================================


class TestQueryAfterAssertion:
    """Verify that asserted facts can be queried back correctly."""

    def test_query_with_filter(self, multi_template_engine):
        multi_template_engine.assert_fact("user", {"name": "Alice", "age": 30})
        multi_template_engine.assert_fact("user", {"name": "Bob", "age": 25})
        results = multi_template_engine.query("user", {"name": "Alice"})
        assert len(results) == 1
        assert results[0]["age"] == 30

    def test_count_facts(self, multi_template_engine):
        multi_template_engine.assert_fact("user", {"name": "Alice", "age": 30})
        multi_template_engine.assert_fact("user", {"name": "Bob", "age": 25})
        assert multi_template_engine.count("user") == 2

    def test_count_with_filter(self, multi_template_engine):
        multi_template_engine.assert_fact("user", {"name": "Alice", "age": 30})
        multi_template_engine.assert_fact("user", {"name": "Bob", "age": 30})
        multi_template_engine.assert_fact("user", {"name": "Carol", "age": 25})
        assert multi_template_engine.count("user", {"age": 30}) == 2


# ===========================================================================
# 12. Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_string_is_valid_string(self, all_types_engine):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": "",
                "s_symbol": "s",
                "s_float": 0.0,
                "s_integer": 0,
            },
        )
        facts = all_types_engine.query("all_types")
        assert facts[0]["s_string"] == ""

    def test_zero_integer(self, all_types_engine):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": "x",
                "s_symbol": "s",
                "s_float": 0.0,
                "s_integer": 0,
            },
        )
        facts = all_types_engine.query("all_types")
        assert facts[0]["s_integer"] == 0

    def test_negative_integer(self, all_types_engine):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": "x",
                "s_symbol": "s",
                "s_float": 0.0,
                "s_integer": -999,
            },
        )
        facts = all_types_engine.query("all_types")
        assert facts[0]["s_integer"] == -999

    def test_negative_float(self, all_types_engine):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": "x",
                "s_symbol": "s",
                "s_float": -42.5,
                "s_integer": 1,
            },
        )
        facts = all_types_engine.query("all_types")
        assert facts[0]["s_float"] == pytest.approx(-42.5)

    def test_very_large_integer(self, all_types_engine):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": "x",
                "s_symbol": "s",
                "s_float": 1.0,
                "s_integer": 2147483647,
            },
        )
        facts = all_types_engine.query("all_types")
        assert facts[0]["s_integer"] == 2147483647

    def test_very_small_float(self, all_types_engine):
        all_types_engine.assert_fact(
            "all_types",
            {
                "s_string": "x",
                "s_symbol": "s",
                "s_float": 0.000001,
                "s_integer": 1,
            },
        )
        facts = all_types_engine.query("all_types")
        assert facts[0]["s_float"] == pytest.approx(0.000001)

    def test_validation_error_is_fathom_error(self):
        """ValidationError should be a FathomError subclass."""
        from fathom.errors import FathomError

        assert issubclass(ValidationError, FathomError)

    def test_retract_after_assert(self, multi_template_engine):
        multi_template_engine.assert_fact("user", {"name": "Alice", "age": 30})
        assert multi_template_engine.count("user") == 1
        multi_template_engine.retract("user", {"name": "Alice"})
        assert multi_template_engine.count("user") == 0

    def test_clear_facts_after_assert(self, multi_template_engine):
        multi_template_engine.assert_fact("user", {"name": "Alice", "age": 30})
        multi_template_engine.assert_fact("item", {"label": "widget"})
        multi_template_engine.clear_facts()
        assert multi_template_engine.count("user") == 0
        assert multi_template_engine.count("item") == 0


# ===========================================================================
# 13. Fixture-based template tests (from agent.yaml)
# ===========================================================================


class TestFixtureTemplates:
    """Tests using the agent fixture template."""

    def test_assert_agent_fact(self, engine, sample_template_path):
        engine.load_templates(str(sample_template_path))
        engine.assert_fact("agent", {"id": "agent-1", "clearance": "secret"})
        facts = engine.query("agent")
        assert len(facts) == 1
        assert facts[0]["id"] == "agent-1"
        assert facts[0]["clearance"] == "secret"

    def test_agent_invalid_clearance(self, engine, sample_template_path):
        engine.load_templates(str(sample_template_path))
        with pytest.raises(ValidationError, match="not in allowed values"):
            engine.assert_fact("agent", {"id": "agent-1", "clearance": "invalid"})

    @pytest.mark.parametrize(
        "clearance",
        [
            "unclassified",
            "cui",
            "confidential",
            "secret",
            "top-secret",
        ],
    )
    def test_agent_all_valid_clearances(self, engine, sample_template_path, clearance):
        engine.load_templates(str(sample_template_path))
        engine.assert_fact("agent", {"id": f"a-{clearance}", "clearance": clearance})
        facts = engine.query("agent", {"clearance": clearance})
        assert len(facts) == 1

    def test_data_request_missing_agent_id(self, engine, sample_template_path):
        engine.load_templates(str(sample_template_path))
        with pytest.raises(ValidationError, match="Missing required"):
            engine.assert_fact("data_request", {"classification": "secret"})


def test_ttl_timestamps_cleared_on_reset() -> None:
    """After reset, previously-asserted timestamps must not affect new facts."""
    import time

    from fathom.engine import Engine
    from fathom.models import SlotDefinition, SlotType, TemplateDefinition

    engine = Engine()
    engine._template_registry["event"] = TemplateDefinition(
        name="event",
        slots=[SlotDefinition(name="kind", type=SlotType.STRING, required=True)],
    )
    engine._safe_build(
        "(deftemplate event (slot kind (type STRING)))",
        context="event",
    )
    engine._fact_manager.set_ttl("event", seconds=1)
    engine.assert_fact("event", {"kind": "first"})
    # Artificially age the first fact's timestamp.
    for fact_idx in list(engine._fact_manager._fact_timestamps):
        engine._fact_manager._fact_timestamps[fact_idx] = time.time() - 3600

    engine.reset()

    # After reset, indices start over and the stale dict must be empty.
    assert engine._fact_manager._fact_timestamps == {}

    engine.assert_fact("event", {"kind": "second"})
    # TTL cleanup now must NOT retract the new fact (its timestamp is fresh).
    engine._fact_manager.cleanup_expired()
    assert engine.query("event") == [{"kind": "second"}]
