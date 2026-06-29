"""Unit tests for :mod:`fathom.yaml_utils`."""

from __future__ import annotations

from pathlib import Path

import pytest

from fathom.yaml_utils import (
    YAMLValidationError,
    load_and_validate,
    validate_document,
    validate_yaml_file,
)


def test_validate_document_accepts_valid_template() -> None:
    data = {"name": "t", "slots": [{"name": "s", "type": "string"}]}

    assert validate_document(data, Path("f.yaml")) == []


def test_validate_document_reports_template_validation_error() -> None:
    data = {"name": "t", "slots": [{"name": "s", "type": "WRONG"}]}

    errors = validate_document(data, Path("f.yaml"))

    assert len(errors) == 1
    assert "template validation error" in errors[0]
    assert "type" in errors[0]


def test_validate_document_ignores_unknown_top_level_keys() -> None:
    assert validate_document({"foo": "bar"}, Path("f.yaml")) == []


def test_validate_yaml_file_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        validate_yaml_file(tmp_path / "missing.yaml")


def test_validate_yaml_file_raises_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")

    with pytest.raises(YAMLValidationError) as exc_info:
        validate_yaml_file(path)

    assert exc_info.value.errors == [f"{path}: no valid YAML mappings found"]


def test_validate_yaml_file_returns_all_yaml_mappings(tmp_path: Path) -> None:
    path = tmp_path / "multi.yaml"
    path.write_text("name: first\n---\nname: second\n", encoding="utf-8")

    assert validate_yaml_file(path) == [{"name": "first"}, {"name": "second"}]


def test_load_and_validate_requires_expected_top_level_key(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("templates: []\n", encoding="utf-8")

    with pytest.raises(YAMLValidationError) as exc_info:
        load_and_validate(path, "rules")

    assert exc_info.value.errors == [
        f"{path}: expected top-level key 'rules' for schema type 'rules'"
    ]


def test_load_and_validate_returns_parsed_mapping(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("rules: []\n", encoding="utf-8")

    assert load_and_validate(path, "rules") == {"rules": []}
