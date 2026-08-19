"""Negative tests for the hot-reload Ed25519 ruleset signature verifier.

``verify_ruleset_signature`` is the only control gating forged rule YAML
from being hot-loaded into a running policy engine, so each of its four
rejection branches gets an explicit test.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from fathom.integrations.ruleset_sig import (
    RulesetSignatureError,
    verify_ruleset_signature,
)

PAYLOAD = b"rules:\n  - name: allow-everything\n"


def _keypair() -> tuple[ed25519.Ed25519PrivateKey, bytes]:
    private = ed25519.Ed25519PrivateKey.generate()
    pem = private.public_key().public_bytes(
        Encoding.PEM,
        PublicFormat.SubjectPublicKeyInfo,
    )
    return private, pem


def test_valid_signature_passes() -> None:
    private, pem = _keypair()
    verify_ruleset_signature(PAYLOAD, private.sign(PAYLOAD), pem)


def test_tampered_payload_is_rejected() -> None:
    """A genuine signature does not carry over to modified YAML."""
    private, pem = _keypair()
    signature = private.sign(PAYLOAD)
    with pytest.raises(RulesetSignatureError, match="verification failed"):
        verify_ruleset_signature(PAYLOAD + b"  action: allow\n", signature, pem)


def test_signature_from_another_key_is_rejected() -> None:
    _, pem = _keypair()
    attacker = ed25519.Ed25519PrivateKey.generate()
    with pytest.raises(RulesetSignatureError, match="verification failed"):
        verify_ruleset_signature(PAYLOAD, attacker.sign(PAYLOAD), pem)


@pytest.mark.parametrize("signature", [b"", b"\x00" * 64, b"short"])
def test_malformed_signature_is_rejected(signature: bytes) -> None:
    _, pem = _keypair()
    with pytest.raises(RulesetSignatureError, match="verification failed"):
        verify_ruleset_signature(PAYLOAD, signature, pem)


def test_rsa_public_key_is_rejected() -> None:
    """Algorithm substitution: an RSA key must not be accepted as Ed25519."""
    rsa_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    private, _ = _keypair()
    with pytest.raises(RulesetSignatureError, match="expected Ed25519 public key"):
        verify_ruleset_signature(PAYLOAD, private.sign(PAYLOAD), rsa_pem)


@pytest.mark.parametrize(
    "pubkey",
    [
        b"",
        b"not a pem at all",
        b"-----BEGIN PUBLIC KEY-----\nZm9v\n-----END PUBLIC KEY-----\n",
    ],
)
def test_malformed_pem_is_rejected(pubkey: bytes) -> None:
    private, _ = _keypair()
    with pytest.raises(RulesetSignatureError, match="invalid PEM public key"):
        verify_ruleset_signature(PAYLOAD, private.sign(PAYLOAD), pubkey)
