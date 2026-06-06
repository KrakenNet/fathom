"""Tests for the SSVC rule pack (supplier, deployer, and CISA trees).

These tests pin every archived SSVC reference (PDFs + decision-table CSVs)
so any silent edit fails loudly, assert the load-bearing branch counts per
tree, verify the committed branch lists match the pinned CSVs, and exercise
every published branch of all three trees end to end.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
from pathlib import Path

import pytest
import yaml

from fathom.engine import Engine
from fathom.rule_packs.ssvc import SSVC_META

REFERENCES_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "fathom" / "rule_packs" / "ssvc" / "references"
)
SHA256SUMS_PATH = REFERENCES_DIR / "SHA256SUMS"
GUIDE_FILENAME = "cisa-ssvc-guide-508c.pdf"

_ssvc_pkg = importlib.import_module("fathom.rule_packs.ssvc")
PACK_DIR = str(Path(_ssvc_pkg.__path__[0]))

# Tree id -> (branch count, pinned CSV, CSV column -> branch slot, label map).
# Counts are load-bearing: they match the published cartesian products
# (supplier 3*3*2*2, deployer 3*3*2*4, cisa 3*2*2*3).
TREES: dict[str, dict] = {
    "supplier": {
        "count": 36,
        "csv": "supplier_patch_development_priority_1_0_0.csv",
        "columns": {
            "Exploitation v1.1.0": "exploitation",
            "Utility v1.0.1": "utility",
            "Technical Impact v1.0.0": "technical_impact",
            "Public Safety Impact v2.0.1": "public_safety_impact",
        },
        "labels": {},
    },
    "deployer": {
        "count": 72,
        "csv": "deployer_patch_application_priority_1_0_0.csv",
        "columns": {
            "Exploitation v1.1.0": "exploitation",
            "System Exposure v1.0.1": "exposure",
            "Automatable v2.0.0": "automatable",
            "Human Impact v2.0.2": "human_impact",
        },
        "labels": {},
    },
    "cisa": {
        "count": 36,
        "csv": "cisa_coordinator_2_0_3.csv",
        "columns": {
            "Exploitation v1.1.0": "exploitation",
            "Automatable v2.0.0": "automatable",
            "Technical Impact v1.0.0": "technical_impact",
            "Mission and Well-Being Impact v1.0.0": "mission_wellbeing",
        },
        "labels": {"track": "Track", "track*": "Track*", "attend": "Attend", "act": "Act"},
    },
}

# Mirrors scripts/generate_ssvc_rules.py VALUE_MAP.
_VALUE_MAP = {"public poc": "poc", "super effective": "super_effective", "very high": "very_high"}


def _sym(value: str) -> str:
    return _VALUE_MAP.get(value, value.replace(" ", "_"))


def _load_pinned_hashes(sums_path: Path) -> dict[str, str]:
    """Parse a SHA256SUMS file into {filename: hex digest}."""
    pins: dict[str, str] = {}
    for raw_line in sums_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Format: "<hex>  <filename>" (two spaces per coreutils convention).
        parts = line.split(None, 1)
        if len(parts) == 2:
            pins[parts[1].strip()] = parts[0]
    return pins


def _load_branches(tree: str) -> list[dict[str, str]]:
    with open(REFERENCES_DIR / f"branches-{tree}.yaml") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, list) and data, f"branches-{tree}.yaml must be a non-empty list"
    return data


def _branches_from_csv(tree: str) -> list[dict[str, str]]:
    spec = TREES[tree]
    branches = []
    with open(REFERENCES_DIR / "csv" / spec["csv"], newline="") as f:
        for row in csv.DictReader(f):
            branch = {slot: _sym(row[col]) for col, slot in spec["columns"].items()}
            label = row[[c for c in row if c not in spec["columns"] and c != "row"][0]]
            branch["decision"] = spec["labels"].get(label, label)
            branches.append(branch)
    return branches


# ---------------------------------------------------------------------------
# Reference pinning
# ---------------------------------------------------------------------------


def test_reference_sha256s() -> None:
    """Every archived reference must match its pin, and every file is pinned."""
    pins = _load_pinned_hashes(SHA256SUMS_PATH)
    on_disk = {
        str(p.relative_to(REFERENCES_DIR)): p
        for p in sorted(REFERENCES_DIR.rglob("*"))
        if p.is_file() and p.suffix in (".pdf", ".csv")
    }
    assert set(pins) == set(on_disk), (
        f"SHA256SUMS out of sync: pinned={sorted(pins)} on_disk={sorted(on_disk)}"
    )
    for name, path in on_disk.items():
        computed = hashlib.sha256(path.read_bytes()).hexdigest()
        assert computed == pins[name], (
            f"{name} sha256 drift: computed={computed} pinned={pins[name]}"
        )


# ---------------------------------------------------------------------------
# Branch lists: load-bearing counts + CSV consistency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tree", sorted(TREES))
def test_branch_count(tree: str) -> None:
    """Each tree's branch list covers its full published decision space."""
    assert len(_load_branches(tree)) == TREES[tree]["count"]


@pytest.mark.parametrize("tree", sorted(TREES))
def test_branches_match_pinned_csv(tree: str) -> None:
    """Committed branches-<tree>.yaml must equal the pinned CSV row for row."""
    assert _load_branches(tree) == _branches_from_csv(tree)


# ---------------------------------------------------------------------------
# All-branches parametrized evaluation, one test per published branch
# ---------------------------------------------------------------------------


def _branch_params() -> list:
    params = []
    for tree in TREES:
        for i, branch in enumerate(_load_branches(tree)):
            inputs = "-".join(v for k, v in branch.items() if k != "decision")
            params.append(
                pytest.param(branch, id=f"{tree}-{i + 1:02d}-{inputs}->{branch['decision']}")
            )
    return params


@pytest.mark.parametrize("branch", _branch_params())
def test_all_published_branches(branch: dict[str, str]) -> None:
    """Every published branch must yield its canonical decision label.

    For each branch, assert the tree's 4 input facts with the branch's
    values, evaluate the pack, and confirm the resulting decision metadata
    carries the published label (defer/scheduled/out-of-cycle/immediate for
    the CERT/CC trees, Track/Track*/Attend/Act for the CISA tree).
    """
    engine = Engine.from_rules(PACK_DIR)
    for slot, value in branch.items():
        if slot != "decision":
            engine.assert_fact(slot, {"value": value})

    result = engine.evaluate()

    assert result.decision == "route", (
        f"branch {branch!r}: expected action=route, got {result.decision!r}"
    )
    assert result.metadata.get("decision") == branch["decision"], (
        f"branch {branch!r}: expected metadata.decision={branch['decision']!r}, "
        f"got metadata={result.metadata!r}"
    )


# ---------------------------------------------------------------------------
# Provenance meta-facts persist through evaluation
# ---------------------------------------------------------------------------


def test_meta_facts_present() -> None:
    """`ssvc_meta` provenance facts must survive a full evaluate() round-trip.

    The ssvc_meta template carries three slots -- ``version``, ``source``,
    ``source_sha256`` -- which together anchor any decision this pack emits
    to a specific authoritative SSVC document. This test asserts them, runs
    a valid branch to quiescence, and then re-queries working memory to
    confirm the meta fact is still there with the canonical ``SSVC_META``
    values.
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
    branch = _load_branches("cisa")[0]
    for slot, value in branch.items():
        if slot != "decision":
            engine.assert_fact(slot, {"value": value})

    engine.evaluate()

    meta_facts = engine.query("ssvc_meta")
    assert len(meta_facts) == 1, (
        f"expected exactly one ssvc_meta fact post-eval, got {meta_facts!r}"
    )
    meta = meta_facts[0]
    assert meta["version"] == "2.0.3", f"ssvc_meta.version drift: got {meta['version']!r}"
    assert meta["source"] == SSVC_META["source"], f"ssvc_meta.source drift: got {meta['source']!r}"
    pinned_sha = _load_pinned_hashes(SHA256SUMS_PATH)[GUIDE_FILENAME]
    assert meta["source_sha256"] == pinned_sha, (
        f"ssvc_meta.source_sha256 drift: got {meta['source_sha256']!r} pinned={pinned_sha!r}"
    )
