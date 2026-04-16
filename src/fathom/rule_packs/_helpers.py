"""Shared helpers for rule pack loading and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import yaml

from fathom.errors import CompilationError

# Subdirectories that a well-formed rule pack should contain.
REQUIRED_SUBDIRS = ("templates", "rules", "modules")


def load_pack_yaml(pack_dir: Path, filename: str) -> dict[str, Any]:
    """Load and parse a YAML file from a rule pack directory.

    Args:
        pack_dir: Root directory of the rule pack.
        filename: Relative path to the YAML file within *pack_dir*.

    Returns:
        Parsed YAML content as a dictionary.

    Raises:
        CompilationError: If the file does not exist, cannot be read,
            or does not parse to a dictionary.
    """
    filepath = pack_dir / filename
    if not filepath.is_file():
        raise CompilationError(
            f"Pack YAML file not found: {filepath}",
            file=str(filepath),
        )
    try:
        with open(filepath) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as exc:
        raise CompilationError(
            f"Cannot read pack YAML file: {filepath}",
            file=str(filepath),
            detail=str(exc),
        ) from exc

    if not isinstance(data, dict):
        raise CompilationError(
            f"Pack YAML file must contain a mapping, got {type(data).__name__}",
            file=str(filepath),
        )
    return data


def validate_pack_structure(pack_dir: Path) -> None:
    """Validate that a rule pack directory has the required structure.

    Checks for the presence of *templates/*, *rules/*, and *modules/*
    subdirectories.

    Args:
        pack_dir: Root directory of the rule pack.

    Raises:
        CompilationError: If *pack_dir* does not exist or is missing
            required subdirectories.
    """
    if not pack_dir.is_dir():
        raise CompilationError(
            f"Pack directory does not exist: {pack_dir}",
            file=str(pack_dir),
        )
    missing = [d for d in REQUIRED_SUBDIRS if not (pack_dir / d).is_dir()]
    if missing:
        raise CompilationError(
            f"Pack directory missing required subdirectories: {', '.join(missing)}",
            file=str(pack_dir),
            detail=f"Expected: {', '.join(REQUIRED_SUBDIRS)}",
        )
