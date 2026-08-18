"""OWASP LLM Top 10 agentic safety rule pack.

Addresses:
- LLM01: Prompt Injection detection
- LLM04: Excessive Agency denial
- LLM06: Insecure Output Handling flagging
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fathom.rule_packs._helpers import load_pack_yaml, validate_pack_structure

PACK_DIR = Path(__file__).resolve().parent


def get_templates() -> list[dict[str, Any]]:
    """Load all template definitions from this pack."""
    validate_pack_structure(PACK_DIR)
    data = load_pack_yaml(PACK_DIR, "templates/owasp_templates.yaml")
    result: list[dict[str, Any]] = data.get("templates", [])
    return result


def get_modules() -> list[dict[str, Any]]:
    """Load all module definitions from this pack."""
    data = load_pack_yaml(PACK_DIR, "modules/owasp_modules.yaml")
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
