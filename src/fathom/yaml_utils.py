"""Reusable YAML validation helpers for Fathom.

Extracted from the CLI ``validate`` command so that rule pack loading,
programmatic validation, and the CLI can share one code-path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError

from fathom.models import (
    ModuleDefinition,
    RuleDefinition,
    RulesetDefinition,
    TemplateDefinition,
)

# Top-level keys that identify each schema type.
_SCHEMA_KEYS: dict[str, str] = {
    "ruleset": "ruleset",
    "templates": "templates",
    "rules": "rules",
    "modules": "modules",
}


class YAMLValidationError(Exception):
    """Raised when YAML validation fails."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"YAML validation failed with {len(errors)} error(s)")


def validate_yaml_file(path: Path) -> dict[str, Any] | list[dict[str, Any]]:
    """Load a YAML file, validate it is parseable, and return its content.

    Supports multi-document YAML files.  Returns a single dict when the file
    contains exactly one document, otherwise a list of dicts.

    Raises:
        FileNotFoundError: If *path* does not exist.
        YAMLValidationError: If the file is not valid YAML or is empty.
    """
    if not path.is_file():
        raise FileNotFoundError(f"YAML file not found: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise YAMLValidationError([f"{path}: read error: {exc}"]) from exc

    try:
        docs = list(yaml.safe_load_all(content))
    except yaml.YAMLError as exc:
        raise YAMLValidationError([f"{path}: YAML parse error: {exc}"]) from exc

    # Filter to dict documents only
    dict_docs = [d for d in docs if isinstance(d, dict)]
    if not dict_docs:
        raise YAMLValidationError([f"{path}: no valid YAML mappings found"])

    return dict_docs[0] if len(dict_docs) == 1 else dict_docs


def validate_document(
    data: dict[str, Any],
    file_path: Path,
) -> list[str]:
    """Validate a single YAML document against known Fathom models.

    Detects the document type by inspecting top-level keys and validates
    against the appropriate Pydantic model.

    Returns a list of error strings (empty on success).
    """
    errors: list[str] = []

    if "ruleset" in data:
        try:
            RulesetDefinition(**data)
        except PydanticValidationError as exc:
            for err in exc.errors():
                loc = " -> ".join(str(p) for p in err["loc"])
                errors.append(f"{file_path}: ruleset validation error at {loc}: {err['msg']}")
    elif "slots" in data:
        try:
            TemplateDefinition(**data)
        except PydanticValidationError as exc:
            for err in exc.errors():
                loc = " -> ".join(str(p) for p in err["loc"])
                errors.append(f"{file_path}: template validation error at {loc}: {err['msg']}")
    elif "when" in data and "then" in data:
        try:
            RuleDefinition(**data)
        except PydanticValidationError as exc:
            for err in exc.errors():
                loc = " -> ".join(str(p) for p in err["loc"])
                errors.append(f"{file_path}: rule validation error at {loc}: {err['msg']}")
    elif "name" in data and not data.get("params"):
        try:
            ModuleDefinition(**data)
        except PydanticValidationError as exc:
            for err in exc.errors():
                loc = " -> ".join(str(p) for p in err["loc"])
                errors.append(f"{file_path}: module validation error at {loc}: {err['msg']}")

    return errors


def load_and_validate(path: Path, schema_type: str) -> dict[str, Any]:
    """Load a YAML file and validate it contains expected top-level keys.

    Args:
        path: Path to the YAML file.
        schema_type: Expected type — one of ``"templates"``, ``"rules"``,
            ``"modules"``, or ``"ruleset"``.

    Returns:
        Parsed YAML content as a dictionary.

    Raises:
        FileNotFoundError: If *path* does not exist.
        YAMLValidationError: On parse errors or missing expected keys.
    """
    result = validate_yaml_file(path)
    data = result if isinstance(result, dict) else result[0]

    if schema_type in _SCHEMA_KEYS:
        expected_key = _SCHEMA_KEYS[schema_type]
        if expected_key not in data:
            raise YAMLValidationError(
                [
                    f"{path}: expected top-level key "
                    f"'{expected_key}' for schema type '{schema_type}'"
                ]
            )

    return data
