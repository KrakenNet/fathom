"""What ``Evaluate`` puts on the wire: metadata, attestation, unset fields.

The RPC response used to carry less than the REST one — no rule metadata, no
attestation token, and no way to tell "no rule decided" from a decision of
``""``. These tests pin the aligned shape.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from fathom.attestation import AttestationService, verify_token
from fathom.engine import Engine
from fathom.integrations.grpc_server import FathomServicer

if TYPE_CHECKING:  # pragma: no cover - annotation-only import
    from pathlib import Path

_TEMPLATES = """
templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
"""

_MODULES = """
modules:
  - name: governance
focus_order:
  - governance
"""

_RULES = """
module: governance
rules:
  - name: tag-known-agent
    when:
      - template: agent
        conditions:
          - slot: id
            expression: "equals(a1)"
    then:
      action: allow
      reason: "known agent"
      metadata:
        policy: clearance-v1
        control: AC-3
"""


class _FakeContext:
    """Minimal ServicerContext double: ``abort`` records and raises."""

    def __init__(self) -> None:
        self.metadata: tuple[tuple[str, str], ...] = (("authorization", "Bearer testtok"),)
        self.aborted: tuple[object, str] | None = None

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self.metadata

    def abort(self, code: object, detail: str) -> None:
        self.aborted = (code, detail)
        raise RuntimeError(f"aborted: {detail}")


@pytest.fixture
def ruleset_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A jail root holding one ruleset whose rule writes metadata."""
    pack = tmp_path / "tagged"
    for subdir, name, body in (
        ("templates", "agent.yaml", _TEMPLATES),
        ("modules", "modules.yaml", _MODULES),
        ("rules", "tagged.yaml", _RULES),
    ):
        (pack / subdir).mkdir(parents=True)
        (pack / subdir / name).write_text(body, encoding="utf-8")

    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
    return tmp_path


def _evaluate(svc: FathomServicer, ctx: _FakeContext, fact_id: str = "a1") -> Any:
    return svc.Evaluate(
        SimpleNamespace(
            session_id="S",
            ruleset="tagged",
            facts=[SimpleNamespace(template="agent", data_json=f'{{"id": "{fact_id}"}}')],
        ),
        ctx,
    )


class TestEvaluateResponseShape:
    def test_rule_metadata_reaches_the_client(self, ruleset_root: Path) -> None:
        response = _evaluate(FathomServicer(), _FakeContext())
        assert response.decision == "allow"
        assert dict(response.metadata) == {"policy": "clearance-v1", "control": "AC-3"}

    def test_no_decision_leaves_the_field_unset(self, ruleset_root: Path) -> None:
        """``optional`` is what separates "unset" from a decision of ``""``.

        An engine built without a default decision is the case that produces
        one: no rule fires, nothing is decided, and the client must be able
        to see that rather than read an empty string as a verdict.
        """
        svc = FathomServicer(default_engine=Engine(default_decision=None))
        response = svc.Evaluate(
            SimpleNamespace(session_id="", ruleset="", facts=[]),
            _FakeContext(),
        )
        assert response.rule_trace == []
        assert not response.HasField("decision")
        assert not response.HasField("reason")
        assert response.decision == ""

    def test_token_is_unset_without_an_attestation_service(self, ruleset_root: Path) -> None:
        response = _evaluate(FathomServicer(), _FakeContext())
        assert not response.HasField("attestation_token")

    def test_configured_service_signs_the_evaluation(self, ruleset_root: Path) -> None:
        service = AttestationService.generate_keypair()
        response = _evaluate(FathomServicer(attestation=service), _FakeContext())

        assert response.HasField("attestation_token")
        claims = verify_token(response.attestation_token, service.public_key)
        assert claims["decision"] == "allow"
        assert claims["rule_trace"] == list(response.rule_trace)
