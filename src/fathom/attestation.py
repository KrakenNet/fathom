"""Ed25519 attestation service for signed evaluation results."""

from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from fathom.errors import AttestationError

if TYPE_CHECKING:
    from fathom.models import EvaluationResult


class AttestationService:
    """Signs evaluation results using Ed25519 JWT tokens."""

    def __init__(self, private_key: Ed25519PrivateKey, public_key: Ed25519PublicKey) -> None:
        self._private_key = private_key
        self._public_key = public_key

    @classmethod
    def generate_keypair(cls) -> AttestationService:
        """Generate a new Ed25519 keypair and return an AttestationService."""
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        return cls(private_key, public_key)

    @classmethod
    def from_private_key_bytes(cls, key_bytes: bytes) -> AttestationService:
        """Create from serialized private key bytes (PEM)."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        private_key = load_pem_private_key(key_bytes, password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise AttestationError("Key is not Ed25519")
        return cls(private_key, private_key.public_key())

    def sign(
        self,
        result: EvaluationResult,
        session_id: str,
        input_facts: list[dict[str, Any]] | None = None,
    ) -> str:
        """Sign an evaluation result and return a JWT token."""
        # SHA-256 hash of input facts for integrity
        input_hash = hashlib.sha256(
            json.dumps(input_facts or [], sort_keys=True).encode()
        ).hexdigest()

        payload = {
            "iss": "fathom",
            "iat": int(time.time()),
            "decision": result.decision,
            "rule_trace": result.rule_trace,
            "input_hash": input_hash,
            "session_id": session_id,
        }

        try:
            return jwt.encode(payload, self._private_key, algorithm="EdDSA")
        except Exception as exc:
            raise AttestationError(f"Signing failed: {exc}") from exc

    def sign_event(self, payload: dict[str, Any]) -> str:
        """Sign an arbitrary JSON payload and return a JWT token.

        Wraps payload as ``{"iss": "fathom", "iat": <unix ts>, **payload}`` and
        signs with the runtime Ed25519 key. Intended for audit events (e.g.
        hot-reload) that are not shaped like an EvaluationResult.
        """
        claims: dict[str, Any] = {
            "iss": "fathom",
            "iat": int(time.time()),
            **payload,
        }

        try:
            return jwt.encode(claims, self._private_key, algorithm="EdDSA")
        except Exception as exc:
            raise AttestationError(f"Signing failed: {exc}") from exc

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._public_key

    def public_key_pem(self) -> bytes:
        return self._public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)


def verify_token(token: str, public_key: Ed25519PublicKey) -> dict[str, Any]:
    """Verify a JWT token and return the decoded payload.

    Raises AttestationError if verification fails.
    """
    try:
        return jwt.decode(token, public_key, algorithms=["EdDSA"])
    except jwt.InvalidTokenError as exc:
        raise AttestationError(f"Token verification failed: {exc}") from exc
