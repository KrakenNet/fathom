"""NIST SP 800-53 security and privacy controls rule pack.

Reference implementation for demonstration and testing purposes only.
This pack is NOT a certified compliance tool and does not guarantee
conformance with NIST SP 800-53. Organizations must perform their
own assessment and authorization processes.

Addresses:
- AC (Access Control): access request policy enforcement
- AU (Audit and Accountability): audit event tracking
- SC (System and Communications Protection): data transfer controls
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fathom.rule_packs._helpers import load_pack_yaml, validate_pack_structure

PACK_DIR = Path(__file__).resolve().parent


def get_templates() -> list[dict[str, Any]]:
    """Load all template definitions from this pack."""
    validate_pack_structure(PACK_DIR)
    data = load_pack_yaml(PACK_DIR, "templates/nist_templates.yaml")
    result: list[dict[str, Any]] = data.get("templates", [])
    return result


def get_modules() -> list[dict[str, Any]]:
    """Load all module definitions from this pack."""
    data = load_pack_yaml(PACK_DIR, "modules/nist_modules.yaml")
    result: list[dict[str, Any]] = data.get("modules", [])
    return result


def get_rules() -> list[dict[str, Any]]:
    """Load all rule definitions from this pack."""
    results: list[dict[str, Any]] = []
    rules_dir = PACK_DIR / "rules"
    for yaml_file in sorted(rules_dir.glob("*.yaml")):
        data = load_pack_yaml(PACK_DIR, f"rules/{yaml_file.name}")
        results.extend(data.get("rules", []))
    return results
