"""Tests for the CISA SSVC v2.0.3 rule pack.

These tests pin the authoritative CISA SSVC PDF (see C4, FR-11, AC-4.3) so that
any silent edit to the archived reference fails loudly, and exercise every
published branch of the deployer tree (see C4, FR-12, AC-4.4).
"""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest
import yaml

from fathom.engine import Engine
from fathom.rule_packs.ssvc import SSVC_META

REFERENCES_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "fathom"
    / "rule_packs"
    / "ssvc"
    / "references"
)
PDF_PATH = REFERENCES_DIR / "cisa-ssvc-v2.0.3.pdf"
SHA256SUMS_PATH = REFERENCES_DIR / "SHA256SUMS"
BRANCHES_PATH = REFERENCES_DIR / "branches.yaml"

_ssvc_pkg = importlib.import_module("fathom.rule_packs.ssvc")
PACK_DIR = str(Path(_ssvc_pkg.__path__[0]))


def _load_pinned_hash(sums_path: Path, filename: str) -> str:
    """Parse a SHA256SUMS file and return the hex digest for *filename*."""
    for raw_line in sums_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Format: "<hex>  <filename>" (two spaces per coreutils convention).
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0], parts[1].strip()
        if name == filename:
            return digest
    raise AssertionError(
        f"no sha256 pin for {filename!r} in {sums_path}"
    )


def test_pdf_sha256() -> None:
    """Archived CISA PDF must match the hash pinned in SHA256SUMS."""
    pinned = _load_pinned_hash(SHA256SUMS_PATH, "cisa-ssvc-v2.0.3.pdf")
    computed = hashlib.sha256(PDF_PATH.read_bytes()).hexdigest()
    assert computed == pinned, (
        f"SSVC PDF sha256 drift: computed={computed} pinned={pinned}"
    )


# ---------------------------------------------------------------------------
# All-branches parametrized test (C4 / FR-12 / AC-4.4)
# ---------------------------------------------------------------------------


def _load_branches() -> list[dict[str, str]]:
    """Load the published CISA SSVC branches from the YAML reference."""
    with open(BRANCHES_PATH) as f:
        data = yaml.safe_load(f)
    assert isinstance(data, list) and data, "branches.yaml must be a non-empty list"
    return data


_BRANCHES = _load_branches()
_BRANCH_IDS = [
    f"{i + 1:02d}-{b['exploitation']}-{b['exposure']}-"
    f"auto_{b['automatable']}-{b['mission_impact']}->"
    f"{b['decision']}"
    for i, b in enumerate(_BRANCHES)
]


@pytest.mark.parametrize("branch", _BRANCHES, ids=_BRANCH_IDS)
def test_all_published_branches(branch: dict[str, str]) -> None:
    """Every CISA-published branch must yield its canonical decision label.

    For each branch, assert the 4 input facts (exploitation, exposure,
    automatable, mission_impact) with the branch's values, evaluate the
    ssvc pack, and confirm the resulting decision metadata carries the
    published CISA label (Track / Track* / Attend / Act).
    """
    engine = Engine.from_rules(PACK_DIR)

    engine.assert_fact("exploitation", {"value": branch["exploitation"]})
    engine.assert_fact("exposure", {"value": branch["exposure"]})
    engine.assert_fact("automatable", {"value": branch["automatable"]})
    engine.assert_fact("mission_impact", {"value": branch["mission_impact"]})

    result = engine.evaluate()

    assert result.decision == "route", (
        f"branch {branch!r}: expected action=route, got {result.decision!r}"
    )
    assert result.metadata.get("decision") == branch["decision"], (
        f"branch {branch!r}: expected metadata.decision={branch['decision']!r}, "
        f"got metadata={result.metadata!r}"
    )


# ---------------------------------------------------------------------------
# Provenance meta-facts persist through evaluation (C4 / AC-4.3 / NFR-7)
# ---------------------------------------------------------------------------


def test_meta_facts_present() -> None:
    """`ssvc_meta` provenance facts must survive a full evaluate() round-trip.

    The ssvc_meta template (see :mod:`fathom.rule_packs.ssvc`) carries three
    slots -- ``version``, ``source``, ``source_sha256`` -- which together
    anchor any decision this pack emits to a specific authoritative SSVC
    document. Per C4 / AC-4.3 / NFR-7 the facts are required to be present
    on every evaluation, so this test asserts them, runs a valid 4-fact
    branch to quiescence, and then re-queries working memory to confirm the
    meta fact is still there with the canonical ``SSVC_META`` values.

    Note on naming: the task description refers to the keys as
    ``ssvc_version`` / ``ssvc_source`` / ``ssvc_source_sha256``. The actual
    template slots are ``version`` / ``source`` / ``source_sha256`` scoped
    under the ``ssvc_meta`` template name -- the ``ssvc_`` prefix is the
    template, not a slot prefix. We assert against the real slot names.
    """
    engine = Engine.from_rules(PACK_DIR)

    engine.assert_fact(
        "ssvc_meta",
        {
            "version": SSVC_META["version"],
            "source": SSVC_META["source"],
            "source_sha256": SSVC_META["source_sha256"],
        },
    )

    # Seed a valid 4-fact set so evaluate() runs a real branch, not a no-op.
    branch = _BRANCHES[0]
    engine.assert_fact("exploitation", {"value": branch["exploitation"]})
    engine.assert_fact("exposure", {"value": branch["exposure"]})
    engine.assert_fact("automatable", {"value": branch["automatable"]})
    engine.assert_fact("mission_impact", {"value": branch["mission_impact"]})

    engine.evaluate()

    meta_facts = engine.query("ssvc_meta")
    assert len(meta_facts) == 1, (
        f"expected exactly one ssvc_meta fact post-eval, got {meta_facts!r}"
    )
    meta = meta_facts[0]
    assert meta["version"] == "2.0.3", (
        f"ssvc_meta.version drift: got {meta['version']!r}"
    )
    assert meta["source"] == "CISA PDF", (
        f"ssvc_meta.source drift: got {meta['source']!r}"
    )
    pinned_sha = _load_pinned_hash(SHA256SUMS_PATH, "cisa-ssvc-v2.0.3.pdf")
    assert meta["source_sha256"] == pinned_sha, (
        f"ssvc_meta.source_sha256 drift: got {meta['source_sha256']!r} "
        f"pinned={pinned_sha!r}"
    )
