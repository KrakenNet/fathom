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
from fathom.errors import AttestationError


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

    claims = verify_token(token, svc.public_key, typ="fathom.event")

    assert claims["iss"] == "fathom"
    assert isinstance(claims["iat"], int)
    assert before - 5 <= claims["iat"] <= after + 5
    assert claims["k"] == "v"


def test_sign_event_reserved_claims_cannot_be_overridden(svc: AttestationService) -> None:
    """Reserved claims merge last, so a payload cannot pass itself off as another kind."""
    token = svc.sign_event({"iss": "custom", "typ": "fathom.evaluation", "iat": 1, "k": "v"})
    claims = verify_token(token, svc.public_key, typ="fathom.event")

    assert claims["iss"] == "fathom"
    assert claims["typ"] == "fathom.event"
    assert claims["iat"] != 1
    assert claims["k"] == "v"


def test_event_token_is_not_an_evaluation_attestation(svc: AttestationService) -> None:
    token = svc.sign_event({"decision": "allow", "k": "v"})
    with pytest.raises(AttestationError, match="typ"):
        verify_token(token, svc.public_key)
