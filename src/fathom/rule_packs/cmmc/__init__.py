"""CMMC Level 2 Cybersecurity Maturity Model Certification rule pack.

Reference implementation covering key CMMC Level 2 practices derived
from NIST SP 800-171:
- AC (Access Control): authorized access and CUI flow enforcement
- AU (Audit and Accountability): audit record generation and traceability
- IR (Incident Response): incident handling capabilities

DISCLAIMER: This rule pack is a reference implementation for demonstration
and educational purposes only. It does NOT constitute certified CMMC
compliance tooling. Organizations must perform their own CMMC assessment
with an authorized C3PAO (CMMC Third-Party Assessment Organization).

Depends on the NIST SP 800-53 rule pack (nist-800-53) for foundational
controls that CMMC Level 2 derives from NIST SP 800-171 / 800-53.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fathom.rule_packs._helpers import load_pack_yaml, validate_pack_structure

PACK_DIR = Path(__file__).resolve().parent


def get_templates() -> list[dict[str, Any]]:
    """Load all template definitions from this pack."""
    validate_pack_structure(PACK_DIR)
    data = load_pack_yaml(PACK_DIR, "templates/cmmc_templates.yaml")
    result: list[dict[str, Any]] = data.get("templates", [])
    return result


def get_modules() -> list[dict[str, Any]]:
    """Load all module definitions from this pack."""
    data = load_pack_yaml(PACK_DIR, "modules/cmmc_modules.yaml")
    result: list[dict[str, Any]] = data.get("modules", [])
    return result


def get_rules() -> list[dict[str, Any]]:
    """Load all rule definitions from this pack."""
    rules_dir = PACK_DIR / "rules"
    results: list[dict[str, Any]] = []
    for yaml_file in sorted(rules_dir.glob("*.yaml")):
        data = load_pack_yaml(PACK_DIR, f"rules/{yaml_file.name}")
        results.extend(data.get("rules", []))
    return results
