"""SSVC v2.0.3 rule pack — vulnerability triage per CISA Stakeholder-Specific Vulnerability Categorization.

Reference implementation of CISA's Stakeholder-Specific Vulnerability
Categorization (SSVC) v2.0.3 decision tree for coordinator-level
vulnerability triage.

- Version: 2.0.3
- Source: CISA PDF (Nov 2021)
- Source sha256: pinned in `references/SHA256SUMS` (asserted at test time)
- Branches source: `references/branches.yaml` (enumerated from the CISA PDF)

Version-bump rule: a CISA SSVC tree update is a minor version bump on this
pack. Silent edits to `SSVC_META.version` or `references/SHA256SUMS` are
forbidden; both must change together. See `README.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fathom.rule_packs._helpers import load_pack_yaml, validate_pack_structure

PACK_DIR = Path(__file__).resolve().parent
_SHA256SUMS_PATH = PACK_DIR / "references" / "SHA256SUMS"
_PDF_FILENAME = "cisa-ssvc-v2.0.3.pdf"


def _read_source_sha256() -> str | None:
    """Parse the PDF sha256 out of `references/SHA256SUMS` at import time.

    Tolerates a missing or empty file (returns ``None``) so the pack remains
    importable before the PDF + SHA file are committed. Once present, the
    file is expected to contain standard `<sha256-hex>  <filename>` lines.
    """
    if not _SHA256SUMS_PATH.is_file():
        return None
    try:
        for line in _SHA256SUMS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[-1].endswith(_PDF_FILENAME):
                return parts[0]
    except OSError:
        return None
    return None


SSVC_META: dict[str, Any] = {
    "version": "2.0.3",
    "source": "CISA PDF",
    "source_sha256": _read_source_sha256(),
    "branches_source": "references/branches.yaml",
}


def get_templates() -> list[dict[str, Any]]:
    """Load all template definitions from this pack."""
    validate_pack_structure(PACK_DIR)
    data = load_pack_yaml(PACK_DIR, "templates/ssvc_templates.yaml")
    result: list[dict[str, Any]] = data.get("templates", [])
    return result


def get_modules() -> list[dict[str, Any]]:
    """Load all module definitions from this pack."""
    data = load_pack_yaml(PACK_DIR, "modules/ssvc_modules.yaml")
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
