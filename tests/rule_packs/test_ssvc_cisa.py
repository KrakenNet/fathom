"""Tests for the CISA SSVC v2.0.3 rule pack.

These tests pin the authoritative CISA SSVC PDF (see C4, FR-11, AC-4.3) so that
any silent edit to the archived reference fails loudly.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

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
