"""Pure-Python minisign signature verifier for Fathom release artifacts.

Parses the minisign `.minisig` file format and verifies the detached Ed25519
signature against the artifact bytes using a committed public key. Zero
network calls; no `minisign` binary required on the consumer host.

Minisign file layout (both `.pub` and `.minisig`):
    line 1: untrusted comment: ...
    line 2: base64(sig_algorithm[2] + key_id[8] + payload)
            payload is 32 bytes (pubkey) or 64 bytes (signature).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

if TYPE_CHECKING:
    from pathlib import Path

_ALGO_LEGACY = b"Ed"  # Ed25519 over raw file bytes
_ALGO_PREHASH = b"ED"  # Ed25519 over BLAKE2b-512(file) — minisign CLI default


class ReleaseSigError(Exception):
    """Raised on any minisign parse or Ed25519 verification failure."""


def _decode_line2(path: Path, expected_len: int) -> tuple[bytes, bytes, bytes]:
    """Return (sig_algorithm, key_id, payload) from line 2 of a minisign file."""
    try:
        lines = path.read_text().splitlines()
    except OSError as e:
        raise ReleaseSigError(f"cannot read {path}: {e}") from e
    if len(lines) < 2 or not lines[0].startswith("untrusted comment:"):
        raise ReleaseSigError(f"malformed minisign file: {path}")
    try:
        raw = base64.b64decode(lines[1], validate=True)
    except (ValueError, binascii.Error) as e:
        raise ReleaseSigError(f"base64 decode failed for {path}: {e}") from e
    if len(raw) != 2 + 8 + expected_len:
        raise ReleaseSigError(
            f"unexpected payload length in {path}: got {len(raw)}, want {10 + expected_len}"
        )
    return raw[:2], raw[2:10], raw[10:]


def parse_minisign_pubkey(path: Path) -> tuple[bytes, bytes]:
    """Return (key_id, 32-byte Ed25519 pubkey) from a minisign `.pub` file."""
    _algo, key_id, pubkey = _decode_line2(path, 32)
    return key_id, pubkey


def parse_minisign_sig(path: Path) -> bytes:
    """Return the raw 64-byte Ed25519 signature from a `.minisig` file."""
    _algo, _key_id, sig = _decode_line2(path, 64)
    return sig


def verify_artifact(artifact: Path, sig: Path, pubkey: Path) -> None:
    """Verify `artifact` bytes against `sig` using `pubkey`. Raises on failure."""
    pub_key_id, pub_bytes = parse_minisign_pubkey(pubkey)
    sig_algo, sig_key_id, sig_bytes = _decode_line2(sig, 64)
    if sig_key_id != pub_key_id:
        raise ReleaseSigError(
            f"key id mismatch: sig {sig_key_id.hex()} vs pubkey {pub_key_id.hex()}"
        )
    try:
        artifact_bytes = artifact.read_bytes()
    except OSError as e:
        raise ReleaseSigError(f"cannot read artifact {artifact}: {e}") from e
    if sig_algo == _ALGO_PREHASH:
        signed = hashlib.blake2b(artifact_bytes).digest()  # 64-byte default
    elif sig_algo == _ALGO_LEGACY:
        signed = artifact_bytes
    else:
        raise ReleaseSigError(f"unsupported sig algorithm: {sig_algo!r}")
    try:
        Ed25519PublicKey.from_public_bytes(pub_bytes).verify(sig_bytes, signed)
    except InvalidSignature as e:
        raise ReleaseSigError(f"signature verification failed for {artifact}") from e
