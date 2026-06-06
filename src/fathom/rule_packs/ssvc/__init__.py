"""SSVC rule pack: supplier, deployer, and CISA vulnerability-triage trees.

Reference implementation of Stakeholder-Specific Vulnerability Categorization
(SSVC) decision trees, one module per tree:

- ``ssvc_supplier`` — CERT/CC supplier patch-development priority tree
  (decision table 1.0.0; 36 branches -> defer/scheduled/out-of-cycle/immediate)
- ``ssvc_deployer`` — CERT/CC deployer patch-application priority tree
  (decision table 1.0.0; 72 branches -> defer/scheduled/out-of-cycle/immediate)
- ``ssvc_cisa`` — CISA SSVC v2.0.3 triage tree
  (36 branches -> Track/Track*/Attend/Act)

Provenance:

- Primary enumeration source: the sha256-pinned decision-table CSVs in
  ``references/csv/`` (from the CERT/CC SSVC repository).
- The CISA tree is additionally page-cited against the archived CISA SSVC
  Guide (``references/cisa-ssvc-guide-508c.pdf``, Table 9, p.10) — the two
  agree on all 36 branches.
- Branch lists: ``references/branches-{supplier,deployer,cisa}.yaml``
  (generated; see ``scripts/generate_ssvc_rules.py``).

Version-bump rule: an upstream SSVC tree update is a minor version bump on
this pack. Silent edits to ``SSVC_META`` or ``references/SHA256SUMS`` are
forbidden; both must change together. See ``README.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fathom.rule_packs._helpers import load_pack_yaml, validate_pack_structure

PACK_DIR = Path(__file__).resolve().parent
_SHA256SUMS_PATH = PACK_DIR / "references" / "SHA256SUMS"

#: The reference whose hash anchors ``ssvc_meta`` facts: the archived CISA
#: SSVC Guide (the only stakeholder-published PDF; CERT/CC trees are pinned
#: per-file in SHA256SUMS).
_GUIDE_FILENAME = "cisa-ssvc-guide-508c.pdf"


def _read_source_sha256() -> str | None:
    """Parse the CISA guide sha256 out of `references/SHA256SUMS` at import time.

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
            if len(parts) >= 2 and parts[-1].endswith(_GUIDE_FILENAME):
                return parts[0]
    except OSError:
        return None
    return None


SSVC_META: dict[str, Any] = {
    "version": "2.0.3",
    "source": "CISA SSVC Guide v2.0.3 + CERT/CC SSVC decision tables",
    "source_sha256": _read_source_sha256(),
    "branches_source": "references/branches-{supplier,deployer,cisa}.yaml",
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
