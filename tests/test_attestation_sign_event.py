"""Round-trip tests for AttestationService.sign_event (C6, FR-17).

sign_event wraps an arbitrary payload as
``{"iss": "fathom", "iat": <unix ts>, **payload}`` and signs it with the
service's Ed25519 key. Verifying with the same service's public key MUST
return those claims intact.
"""

from __future__ import annotations

import time

import pytest

from fathom.attestation import AttestationService, verify_token


@pytest.fixture
def svc() -> AttestationService:
    return AttestationService.generate_keypair()


def test_sign_event_round_trip(svc: AttestationService) -> None:
    """Happy path: sign + verify yields iss/iat/payload claims."""
    before = int(time.time())
    token = svc.sign_event({"k": "v"})
    after = int(time.time())

    # 3-part JWT (header.payload.signature)
    assert token.count(".") == 2

    claims = verify_token(token, svc.public_key)

    assert claims["iss"] == "fathom"
    assert isinstance(claims["iat"], int)
    assert before - 5 <= claims["iat"] <= after + 5
    assert claims["k"] == "v"


def test_sign_event_payload_iss_overrides_preset(svc: AttestationService) -> None:
    """`**payload` spreads last, so a caller-supplied `iss` overrides `fathom`.

    Documents current behaviour of sign_event (claims built as
    ``{"iss": "fathom", "iat": ..., **payload}``) -- callers can override
    `iss` by including it in the payload.
    """
    token = svc.sign_event({"iss": "custom", "k": "v"})
    claims = verify_token(token, svc.public_key)

    assert claims["iss"] == "custom"
    assert claims["k"] == "v"
    assert isinstance(claims["iat"], int)
