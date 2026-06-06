"""Ed25519 signature verification for hot-reloaded ruleset YAML (design D8).

Accepts raw bytes — no file I/O, no minisign parsing. Operators supply a PEM
Ed25519 public key and a raw 64-byte detached signature over the YAML payload.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key


class RulesetSignatureError(Exception):
    """Raised on any Ed25519 verification or pubkey parse failure."""


def verify_ruleset_signature(yaml_bytes: bytes, sig_bytes: bytes, pubkey_bytes: bytes) -> None:
    """Verify `yaml_bytes` against `sig_bytes` using PEM `pubkey_bytes`.

    Raises `RulesetSignatureError` on malformed pubkey, non-Ed25519 key, or
    signature mismatch.
    """
    try:
        pubkey = load_pem_public_key(pubkey_bytes)
    except (ValueError, TypeError) as e:
        raise RulesetSignatureError(f"invalid PEM public key: {e}") from e
    if not isinstance(pubkey, Ed25519PublicKey):
        raise RulesetSignatureError(f"expected Ed25519 public key, got {type(pubkey).__name__}")
    try:
        pubkey.verify(sig_bytes, yaml_bytes)
    except InvalidSignature as e:
        raise RulesetSignatureError("ruleset signature verification failed") from e
