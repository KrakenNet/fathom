"""A shipped pack's deny must not depend on how the bad value is spelled.

The packs denied on one exact spelling of the bad value: HIPAA transmission
security fired on `encrypted="FALSE"` and let `"false"`, `"no"` and
`"unencrypted"` through, and rejected a Python bool outright. A blank-check
rule fired on `""` and let `"   "` through; a destination rule fired on
`external-s3` and not `External-S3`. Under the default `deny` decision this is
masked; it bypasses as soon as the host adds any allow rule, so every case runs
under an allow default.
"""

from __future__ import annotations

import pytest

from fathom.engine import Engine
from fathom.errors import ValidationError


def _decide(pack: str, template: str, data: dict) -> tuple[str | None, list[str]]:
    engine = Engine(default_decision="allow")
    engine.load_pack(pack)
    engine.assert_fact(template, data)
    result = engine.evaluate()
    return result.decision, result.rule_trace


_TRANSFER = {"source": "ehr", "destination": "partner"}


@pytest.mark.parametrize(
    "encrypted", ["FALSE", "false", "False", "no", "0", "unencrypted", " TRUE x"]
)
def test_hipaa_transmission_security_denies_anything_but_true(encrypted: object) -> None:
    decision, trace = _decide("hipaa", "data_transfer", {**_TRANSFER, "encrypted": encrypted})
    assert decision == "deny"
    assert trace == ["hipaa::transmission-security"]


@pytest.mark.parametrize("encrypted", ["TRUE", "true", "True"])
def test_hipaa_transmission_security_allows_true_in_any_case(encrypted: object) -> None:
    assert _decide("hipaa", "data_transfer", {**_TRANSFER, "encrypted": encrypted})[1] == []


@pytest.mark.parametrize("encrypted", [True, False])
def test_hipaa_encrypted_refuses_a_bool(encrypted: bool) -> None:
    # `encrypted` is a string slot; a bool is refused, never stored as "True".
    with pytest.raises(ValidationError, match="expects string"):
        _decide("hipaa", "data_transfer", {**_TRANSFER, "encrypted": encrypted})


def test_hipaa_phi_is_phi_in_any_case() -> None:
    data = {**_TRANSFER, "data_type": "PHI", "encrypted": "no"}
    assert _decide("hipaa", "data_transfer", data)[0] == "deny"


@pytest.mark.parametrize(
    ("pack", "template", "data", "slot", "rule"),
    [
        (
            "hipaa",
            "phi_policy",
            {"resource": "chart", "role": "nurse", "ts": 1.0},
            "justification",
            "hipaa::minimum-necessary",
        ),
        (
            "cmmc",
            "cui_policy",
            {"subject": "u", "resource": "r", "action": "read", "ts": 1.0},
            "justification",
            "cmmc::ac-l2-authorized-access",
        ),
        (
            "nist-800-53",
            "access_request",
            {"subject": "u", "resource": "r", "action": "admin"},
            "context",
            "nist::least-privilege",
        ),
        (
            "nist-800-53",
            "audit_event",
            {"event_type": "login", "outcome": "success", "ts": 1.0},
            "subject",
            "nist::audit-content",
        ),
    ],
)
@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_field_counts_as_missing(
    pack: str, template: str, data: dict, slot: str, rule: str, blank: str
) -> None:
    decision, trace = _decide(pack, template, {**data, slot: blank})
    assert decision == "deny"
    assert rule in trace


@pytest.mark.parametrize("destination", ["External-S3", "PUBLIC_BUCKET"])
@pytest.mark.parametrize(
    ("pack", "data", "rule"),
    [
        (
            "nist-800-53",
            {"classification": "secret", "protocol": "https"},
            "nist::info-flow-enforcement",
        ),
        (
            "nist-800-53",
            {"classification": "unclassified", "protocol": "ftp"},
            "nist::boundary-protection",
        ),
    ],
)
def test_a_destination_deny_ignores_case(
    pack: str, data: dict, rule: str, destination: str
) -> None:
    decision, trace = _decide(
        pack, "data_transfer", {"source": "a", "destination": destination, **data}
    )
    assert decision == "deny"
    assert rule in trace


@pytest.mark.parametrize("tool", ["Shell", "EXEC"])
def test_owasp_exec_deny_ignores_case(tool: str) -> None:
    decision, trace = _decide(
        "owasp-agentic", "tool_request", {"tool_name": tool, "agent_id": "a"}
    )
    assert decision == "deny"
    assert trace == ["owasp::deny-excessive-agency-exec"]


@pytest.mark.parametrize(
    ("pack", "template", "data", "slot", "bad"),
    [
        ("nist-800-53", "data_transfer", {"source": "a", "destination": "b"}, "protocol", "FTP"),
        ("nist-800-53", "data_transfer", {"source": "a", "destination": "b"}, "protocol", "http"),
        (
            "nist-800-53",
            "data_transfer",
            {"source": "a", "destination": "b"},
            "classification",
            "Secret",
        ),
        ("nist-800-53", "access_request", {"subject": "u", "resource": "r"}, "action", "Admin"),
        (
            "nist-800-53",
            "access_request",
            {"subject": "u", "resource": "r", "action": "read"},
            "clearance",
            "Unclassified",
        ),
        ("nist-800-53", "audit_event", {"subject": "u", "ts": 1.0}, "event_type", "Delete"),
        (
            "nist-800-53",
            "audit_event",
            {"subject": "u", "event_type": "login", "ts": 1.0},
            "outcome",
            "FAILED",
        ),
        ("cmmc", "cui_policy", {"subject": "u", "resource": "r", "ts": 1.0}, "action", "Admin"),
        (
            "hipaa",
            "phi_policy",
            {"resource": "chart", "role": "nurse", "ts": 1.0},
            "access_level",
            "Read",
        ),
    ],
)
def test_an_enum_slot_a_deny_reads_refuses_an_unknown_spelling(
    pack: str, template: str, data: dict, slot: str, bad: str
) -> None:
    """A wrong-case or unknown value would match none of the rule's set and
    pass; refusing it at assert fails closed, as the ssvc pack does."""
    engine = Engine(default_decision="allow")
    if pack == "cmmc":
        engine.load_pack("nist-800-53")
    engine.load_pack(pack)
    with pytest.raises(ValidationError, match="not in allowed values"):
        engine.assert_fact(template, {**data, slot: bad})
