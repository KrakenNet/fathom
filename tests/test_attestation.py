"""Ed25519 attestation tests -- keypair, sign, verify, engine integration."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from fathom.attestation import AttestationService, verify_token
from fathom.errors import AttestationError
from fathom.models import EvaluationResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def svc() -> AttestationService:
    return AttestationService.generate_keypair()


@pytest.fixture
def sample_result() -> EvaluationResult:
    return EvaluationResult(
        decision="deny",
        reason="test reason",
        rule_trace=["governance::deny-rule"],
        module_trace=["governance"],
        duration_us=100,
    )


def _make_result(**kwargs: Any) -> EvaluationResult:
    defaults: dict[str, Any] = {
        "decision": "deny",
        "reason": "test",
        "rule_trace": ["r1"],
        "module_trace": ["m1"],
        "duration_us": 50,
    }
    defaults.update(kwargs)
    return EvaluationResult(**defaults)


# ---------------------------------------------------------------------------
# Keypair generation
# ---------------------------------------------------------------------------


class TestKeypairGeneration:
    def test_generate_creates_service(self) -> None:
        svc = AttestationService.generate_keypair()
        assert svc is not None

    def test_generate_returns_attestation_service(self) -> None:
        svc = AttestationService.generate_keypair()
        assert isinstance(svc, AttestationService)

    def test_public_key_accessible(self, svc: AttestationService) -> None:
        assert svc.public_key is not None

    def test_public_key_is_ed25519(self, svc: AttestationService) -> None:
        assert isinstance(svc.public_key, Ed25519PublicKey)

    def test_public_key_pem_format(self, svc: AttestationService) -> None:
        pem = svc.public_key_pem()
        assert b"BEGIN PUBLIC KEY" in pem
        assert b"END PUBLIC KEY" in pem

    def test_two_keypairs_are_different(self) -> None:
        svc1 = AttestationService.generate_keypair()
        svc2 = AttestationService.generate_keypair()
        assert svc1.public_key_pem() != svc2.public_key_pem()


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


class TestSign:
    def test_sign_returns_string(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token = svc.sign(sample_result, "session-1", input_facts=[])
        assert isinstance(token, str)

    def test_sign_returns_nonempty(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token = svc.sign(sample_result, "session-1", input_facts=[])
        assert len(token) > 0

    def test_sign_produces_valid_jwt(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token = svc.sign(sample_result, "session-1", input_facts=[])
        payload = verify_token(token, svc.public_key)
        assert payload["decision"] == "deny"

    def test_sign_with_input_facts(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        facts = [{"template": "agent", "data": {"name": "bot1"}}]
        token = svc.sign(sample_result, "session-1", input_facts=facts)
        payload = verify_token(token, svc.public_key)
        assert "input_hash" in payload
        assert len(payload["input_hash"]) == 64  # SHA-256 hex digest

    def test_sign_different_inputs_different_hash(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token_a = svc.sign(sample_result, "s1", input_facts=[{"a": 1}])
        token_b = svc.sign(sample_result, "s1", input_facts=[{"b": 2}])
        payload_a = verify_token(token_a, svc.public_key)
        payload_b = verify_token(token_b, svc.public_key)
        assert payload_a["input_hash"] != payload_b["input_hash"]

    def test_sign_refuses_missing_input_facts(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        """Signing without input_facts would bind nothing — refuse it."""
        with pytest.raises(AttestationError, match="requires input_facts"):
            svc.sign(sample_result, "s1")

    def test_sign_accepts_empty_input_facts(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        """An evaluation over empty working memory signs an explicit []."""
        token = svc.sign(sample_result, "s1", input_facts=[])
        payload = verify_token(token, svc.public_key)
        assert payload["input_hash"] == hashlib.sha256(b"[]").hexdigest()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


class TestVerify:
    def test_verify_correct_key(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token = svc.sign(sample_result, "session-1", input_facts=[])
        payload = verify_token(token, svc.public_key)
        assert payload["iss"] == "fathom"
        assert payload["session_id"] == "session-1"

    def test_verify_wrong_key_raises(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token = svc.sign(sample_result, "session-1", input_facts=[])
        other_svc = AttestationService.generate_keypair()
        with pytest.raises(AttestationError):
            verify_token(token, other_svc.public_key)

    def test_verify_tampered_token_raises(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token = svc.sign(sample_result, "session-1", input_facts=[])
        tampered = token[:-4] + "XXXX"
        with pytest.raises(AttestationError):
            verify_token(tampered, svc.public_key)

    def test_verify_garbage_token_raises(self, svc: AttestationService) -> None:
        with pytest.raises(AttestationError):
            verify_token("not.a.jwt", svc.public_key)

    def test_verify_empty_token_raises(self, svc: AttestationService) -> None:
        with pytest.raises(AttestationError):
            verify_token("", svc.public_key)


# ---------------------------------------------------------------------------
# JWT payload fields
# ---------------------------------------------------------------------------


class TestPayload:
    REQUIRED_FIELDS = ["iss", "iat", "decision", "rule_trace", "input_hash", "session_id"]

    def test_payload_has_all_required_fields(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token = svc.sign(sample_result, "session-1", input_facts=[])
        payload = verify_token(token, svc.public_key)
        for field in self.REQUIRED_FIELDS:
            assert field in payload, f"Missing field: {field}"

    def test_iss_is_fathom(self, svc: AttestationService, sample_result: EvaluationResult) -> None:
        token = svc.sign(sample_result, "session-1", input_facts=[])
        payload = verify_token(token, svc.public_key)
        assert payload["iss"] == "fathom"

    def test_iat_is_recent_timestamp(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        before = int(time.time())
        token = svc.sign(sample_result, "session-1", input_facts=[])
        after = int(time.time())
        payload = verify_token(token, svc.public_key)
        assert before <= payload["iat"] <= after

    def test_decision_matches_result(self, svc: AttestationService) -> None:
        for decision in ("allow", "deny", "escalate"):
            result = _make_result(decision=decision)
            token = svc.sign(result, "s1", input_facts=[])
            payload = verify_token(token, svc.public_key)
            assert payload["decision"] == decision

    def test_rule_trace_preserved(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token = svc.sign(sample_result, "session-1", input_facts=[])
        payload = verify_token(token, svc.public_key)
        assert payload["rule_trace"] == ["governance::deny-rule"]

    def test_session_id_preserved(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token = svc.sign(sample_result, "session-99", input_facts=[])
        payload = verify_token(token, svc.public_key)
        assert payload["session_id"] == "session-99"


# ---------------------------------------------------------------------------
# Algorithm enforcement
# ---------------------------------------------------------------------------


class TestAlgorithm:
    def test_token_uses_eddsa(
        self, svc: AttestationService, sample_result: EvaluationResult
    ) -> None:
        token = svc.sign(sample_result, "session-1", input_facts=[])
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "EdDSA"

    def test_verify_rejects_non_eddsa_algorithm(self, svc: AttestationService) -> None:
        """A token forged with HS256 must be rejected."""
        payload = {"iss": "fathom", "iat": int(time.time()), "decision": "allow"}
        forged = jwt.encode(payload, "secret", algorithm="HS256")
        with pytest.raises(AttestationError):
            verify_token(forged, svc.public_key)


# ---------------------------------------------------------------------------
# Engine integration
# ---------------------------------------------------------------------------


class TestEngineIntegration:
    def test_engine_with_attestation(self, svc: AttestationService) -> None:
        from fathom.engine import Engine

        e = Engine(attestation_service=svc)
        result = e.evaluate()
        assert result.attestation_token is not None
        payload = verify_token(result.attestation_token, svc.public_key)
        assert payload["decision"] == "deny"  # default fail-closed

    def test_engine_without_attestation_no_token(self) -> None:
        from fathom.engine import Engine

        e = Engine()
        result = e.evaluate()
        assert result.attestation_token is None


class TestEngineBindsInputFacts:
    """S1: every engine-issued token used to carry the constant sha256("[]")."""

    RULES = "examples/01-hello-allow-deny"

    def _evaluate(
        self, svc: AttestationService, clearance: str, classification: str, resource: str
    ) -> dict[str, Any]:
        from fathom.engine import Engine

        e = Engine.from_rules(self.RULES, attestation_service=svc)
        e.assert_fact("agent", {"id": "alice", "clearance": clearance})
        e.assert_fact(
            "data_request",
            {"agent_id": "alice", "classification": classification, "resource": resource},
        )
        result = e.evaluate()
        assert result.attestation_token is not None
        return verify_token(result.attestation_token, svc.public_key)

    def test_same_decision_different_facts_yield_different_hashes(
        self, svc: AttestationService
    ) -> None:
        benign = self._evaluate(svc, "top-secret", "secret", "quarterly-report")
        sensitive = self._evaluate(svc, "top-secret", "top-secret", "nuclear-codes")
        assert benign["decision"] == sensitive["decision"] == "allow"
        assert benign["rule_trace"] == sensitive["rule_trace"]
        assert benign["input_hash"] != sensitive["input_hash"]

    def test_input_hash_is_not_the_empty_list_digest(self, svc: AttestationService) -> None:
        payload = self._evaluate(svc, "secret", "top-secret", "x")
        assert payload["input_hash"] != hashlib.sha256(b"[]").hexdigest()

    def test_input_hash_is_reproducible_by_a_verifier(self, svc: AttestationService) -> None:
        """The documented verifier procedure: rebuild the hash from the facts you have."""
        import json

        payload = self._evaluate(svc, "secret", "secret", "doc1")
        expected_facts = [
            {"template": "agent", "slots": {"id": "alice", "clearance": "secret"}},
            {
                "template": "data_request",
                "slots": {
                    "agent_id": "alice",
                    "classification": "secret",
                    "resource": "doc1",
                },
            },
        ]
        expected = hashlib.sha256(
            json.dumps(expected_facts, sort_keys=True).encode()
        ).hexdigest()
        assert payload["input_hash"] == expected

    def test_input_hash_binds_the_template_not_just_the_slots(
        self, svc: AttestationService, tmp_path: Any
    ) -> None:
        """Two templates with identical slot names must not collide.

        `_snapshot_input_facts` used to emit bare slot dicts, dropping the
        template each fact came from. A token attesting a decision over
        `low_risk_asset(id=x)` therefore verified byte-for-byte against
        `high_risk_asset(id=x)` — the docs' "swap the facts and the hash
        stops matching" guarantee was falsifiable.
        """
        from fathom.engine import Engine

        pack = tmp_path / "pack"
        (pack / "templates").mkdir(parents=True)
        (pack / "rules").mkdir()
        (pack / "modules").mkdir()
        (pack / "modules" / "m.yaml").write_text(
            "modules:\n  - name: m\n\nfocus_order:\n  - m\n"
        )
        (pack / "templates" / "t.yaml").write_text(
            "templates:\n"
            "  - name: trigger\n"
            "    slots:\n"
            "      - {name: go, type: string}\n"
            "  - name: low_risk_asset\n"
            "    slots:\n"
            "      - {name: id, type: string}\n"
            "  - name: high_risk_asset\n"
            "    slots:\n"
            "      - {name: id, type: string}\n"
        )
        (pack / "rules" / "r.yaml").write_text(
            "module: m\n"
            "ruleset: collide\n"
            "rules:\n"
            "  - name: approve\n"
            "    when:\n"
            "      - template: trigger\n"
            "        conditions:\n"
            "          - slot: go\n"
            "            expression: \"equals(yes)\"\n"
            "    then:\n"
            "      action: allow\n"
            "      reason: ok\n"
        )

        def run(asset_template: str) -> str:
            e = Engine.from_rules(str(pack), attestation_service=svc)
            e.assert_fact("trigger", {"go": "yes"})
            e.assert_fact(asset_template, {"id": "asset1"})
            result = e.evaluate()
            assert result.attestation_token is not None
            payload = verify_token(result.attestation_token, svc.public_key)
            assert payload["decision"] == "allow"
            return str(payload["input_hash"])

        assert run("low_risk_asset") != run("high_risk_asset")

    def test_empty_working_memory_still_signs(self, svc: AttestationService) -> None:
        from fathom.engine import Engine

        e = Engine.from_rules(self.RULES, attestation_service=svc)
        result = e.evaluate()
        assert result.attestation_token is not None
        payload = verify_token(result.attestation_token, svc.public_key)
        assert payload["input_hash"] == hashlib.sha256(b"[]").hexdigest()
