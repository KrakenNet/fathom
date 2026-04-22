"""Request-shape + happy-path tests for ``POST /v1/rules/reload`` (C5, AC-5.1).

Validates the exactly-one-of ``ruleset_path`` / ``ruleset_yaml`` contract on
``RulesetReloadRequest`` plus the 3-field happy-path response shape
(``hash_before`` / ``hash_after`` / ``attestation_token``).

The shape-tests fixture runs against ``build_app(require_signature=False)``
with the dev-escape env var set (``FATHOM_ALLOW_UNSIGNED_RULESETS=1``).
A second fixture (``signed_client``) runs with ``require_signature=True``
and a fixture-owned Ed25519 keypair for T-3.8 (signed reload + audit
emission, AC-5.4).
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from fathom.attestation import AttestationService, verify_token
from fathom.engine import Engine
from fathom.integrations.rest import build_app

if TYPE_CHECKING:
    from collections.abc import Iterator


def _ruleset_yaml(rule_name: str, subject: str) -> str:
    """Build a self-contained ruleset YAML payload for /v1/rules/reload."""
    return yaml.safe_dump(
        {
            "ruleset": f"rs-{rule_name}",
            "module": "gov",
            "rules": [
                {
                    "name": rule_name,
                    "when": [
                        {
                            "template": "agent",
                            "conditions": [
                                {"slot": "id", "expression": f"equals({subject})"},
                            ],
                        },
                    ],
                    "then": {"action": "allow", "reason": f"{rule_name} ok"},
                },
            ],
        }
    )


def _seed_engine(tmp_path: Path) -> Engine:
    """Engine with the templates + modules the reload ruleset references."""
    (tmp_path / "templates.yaml").write_text(
        "templates:\n"
        "  - name: agent\n"
        "    slots:\n"
        "      - name: id\n"
        "        type: symbol\n"
    )
    (tmp_path / "modules.yaml").write_text(
        "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"
    )
    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    engine.load_modules(str(tmp_path / "modules.yaml"))
    # Seed an initial ruleset so ``hash_before`` is non-sentinel and differs
    # from ``hash_after``. Not strictly required by the shape tests, but it
    # gives realistic hash trajectories in the happy-path assertions.
    initial = _ruleset_yaml("rule-seed", "seed")
    (tmp_path / "rules-seed.yaml").write_text(initial)
    engine.load_rules(str(tmp_path / "rules-seed.yaml"))
    return engine


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> "Iterator[TestClient]":
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
    # Path-jail root (unused by ruleset_yaml cases but harmless).
    rules_root = tmp_path / "rules"
    rules_root.mkdir()
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(rules_root))

    app = build_app(require_signature=False)
    app.state.engine = _seed_engine(tmp_path)
    app.state.attestation = AttestationService.generate_keypair()
    app.state.audit_sink = None

    with TestClient(app) as tc:
        yield tc


AUTH = {"Authorization": "Bearer testtok"}


def test_shape_valid_ruleset_yaml(client: TestClient) -> None:
    """Happy path: ``ruleset_yaml`` alone → 200 with 3-field response.

    AC-5.1: response exposes ``hash_before`` / ``hash_after`` /
    ``attestation_token`` and nothing else material.
    """
    body = {"ruleset_yaml": _ruleset_yaml("rule-new", "alice")}
    resp = client.post("/v1/rules/reload", json=body, headers=AUTH)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Exactly the three documented fields must be present.
    assert set(data.keys()) == {"hash_before", "hash_after", "attestation_token"}
    assert data["hash_before"].startswith("sha256:")
    assert data["hash_after"].startswith("sha256:")
    assert data["hash_before"] != data["hash_after"]
    assert isinstance(data["attestation_token"], str) and data["attestation_token"]


def test_shape_both_sources_rejected(client: TestClient) -> None:
    """Both ``ruleset_path`` and ``ruleset_yaml`` → 400 ``invalid_request``."""
    body = {
        "ruleset_path": "some/path.yaml",
        "ruleset_yaml": _ruleset_yaml("rule-dup", "dup"),
    }
    resp = client.post("/v1/rules/reload", json=body, headers=AUTH)
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "invalid_request"


def test_shape_neither_source_rejected(client: TestClient) -> None:
    """Neither source supplied → 400 ``invalid_request``."""
    resp = client.post("/v1/rules/reload", json={}, headers=AUTH)
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "invalid_request"


class _ListAuditSink:
    """Duck-typed in-memory sink collecting ``write()`` records into a list."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)


@pytest.fixture
def signed_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> "Iterator[tuple[TestClient, Ed25519PrivateKey, _ListAuditSink, AttestationService]]":
    """Build app with ``require_signature=True`` + fixture-owned Ed25519 keypair.

    Yields ``(client, private_key, audit_sink, attestation_service)`` so tests
    can sign payloads, assert audit records, and verify attestation tokens.
    """
    # Generate ruleset-signing keypair and persist pubkey PEM for build_app.
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )
    pubkey_path = tmp_path / "ruleset-pub.pem"
    pubkey_path.write_bytes(pub_pem)

    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_RULESET_PUBKEY_PATH", str(pubkey_path))
    # Ensure dev-escape isn't silently active in this fail-closed path.
    monkeypatch.delenv("FATHOM_ALLOW_UNSIGNED_RULESETS", raising=False)
    rules_root = tmp_path / "rules"
    rules_root.mkdir()
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(rules_root))

    app = build_app(require_signature=True)
    # Confirm build_app loaded our pubkey (fail-closed bootstrap).
    assert app.state.ruleset_pubkey == pub_pem

    app.state.engine = _seed_engine(tmp_path)
    attestation = AttestationService.generate_keypair()
    app.state.attestation = attestation
    sink = _ListAuditSink()
    app.state.audit_sink = sink

    with TestClient(app) as tc:
        yield tc, priv, sink, attestation


def test_signed_reload_audit_emission(
    signed_client: tuple[TestClient, Ed25519PrivateKey, _ListAuditSink, AttestationService],
) -> None:
    """Signed reload → 200 with verifiable attestation + 1 audit record.

    AC-5.4 / FR-17: a successful signed reload emits exactly one
    ``event_type=ruleset_reloaded`` audit record carrying
    ``ruleset_hash_before`` / ``ruleset_hash_after`` / ``actor`` / ``timestamp``,
    and the response's ``attestation_token`` is a valid JWT with the same 4
    fields.
    """
    client, priv, sink, attestation = signed_client

    yaml_str = _ruleset_yaml("rule-signed", "bob")
    yaml_bytes = yaml_str.encode("utf-8")
    sig = priv.sign(yaml_bytes)
    body = {
        "ruleset_yaml": yaml_str,
        "signature": base64.b64encode(sig).decode("ascii"),
    }

    resp = client.post("/v1/rules/reload", json=body, headers=AUTH)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == {"hash_before", "hash_after", "attestation_token"}
    assert data["hash_before"].startswith("sha256:")
    assert data["hash_after"].startswith("sha256:")
    assert data["hash_before"] != data["hash_after"]

    # Attestation token: EdDSA JWT signed by the runtime key — decode with its pubkey.
    claims = verify_token(data["attestation_token"], attestation.public_key)
    assert claims["iss"] == "fathom"
    assert isinstance(claims["iat"], int)
    assert claims["ruleset_hash_before"] == data["hash_before"]
    assert claims["ruleset_hash_after"] == data["hash_after"]
    assert claims["actor"] == "bearer-token"
    assert isinstance(claims["timestamp"], str) and claims["timestamp"]

    # Audit sink: exactly one ruleset_reloaded record carrying the 4 fields.
    reloaded = [r for r in sink.records if r.get("event_type") == "ruleset_reloaded"]
    assert len(reloaded) == 1, sink.records
    rec = reloaded[0]
    assert rec["ruleset_hash_before"] == data["hash_before"]
    assert rec["ruleset_hash_after"] == data["hash_after"]
    assert rec["actor"] == "bearer-token"
    assert rec["timestamp"] == claims["timestamp"]


def test_unsigned_reload_rejected_by_default(
    signed_client: tuple[TestClient, Ed25519PrivateKey, _ListAuditSink, AttestationService],
) -> None:
    """Unsigned reload on fail-closed app → 400 ``unsigned_ruleset`` + audit.

    AC-5.5 / FR-18: with ``require_signature=True`` and no dev-escape env,
    POSTing a ruleset without ``signature`` must be rejected with HTTP 400
    and ``error="unsigned_ruleset"``, and an audit record with
    ``event_type="ruleset_reload_rejected"`` must be emitted.
    """
    client, _priv, sink, _attestation = signed_client

    body = {"ruleset_yaml": _ruleset_yaml("rule-unsigned", "carol")}
    resp = client.post("/v1/rules/reload", json=body, headers=AUTH)

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "unsigned_ruleset"

    rejected = [
        r for r in sink.records if r.get("event_type") == "ruleset_reload_rejected"
    ]
    assert len(rejected) == 1, sink.records


def _write_pubkey(tmp_path: Path) -> tuple[Path, Ed25519PrivateKey, bytes]:
    """Mint an Ed25519 keypair and write the PEM pubkey under ``tmp_path``."""
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )
    pubkey_path = tmp_path / "ruleset-pub.pem"
    pubkey_path.write_bytes(pub_pem)
    return pubkey_path, priv, pub_pem


def test_dev_escape_needs_both_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Dev-escape requires BOTH ``require_signature=False`` AND the env var.

    AC-5.6 / FR-19: a single-flag configuration is still fail-closed. Only
    the explicit belt-and-suspenders combination
    (``require_signature=False`` + ``FATHOM_ALLOW_UNSIGNED_RULESETS=1``)
    allows unsigned reloads, and the boot emits a WARN log when active.

    Three sub-cases:
      (a) env set, require_signature=True (default) → signature still
          required; unsigned POST → 400 ``unsigned_ruleset``.
      (b) require_signature=False with env unset → ``build_app`` raises
          ``RuntimeError`` at startup (dev-escape not active, pubkey
          absent).
      (c) both flags set → build succeeds with a WARN log; unsigned
          POST → 200.
    """
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    rules_root = tmp_path / "rules"
    rules_root.mkdir()
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(rules_root))

    # -----------------------------------------------------------------
    # (a) Only env set — require_signature=True (default) + pubkey path.
    #     The env flag alone does NOT enable dev-escape: app boots with
    #     signature enforcement and the pubkey loaded from disk.
    # -----------------------------------------------------------------
    pubkey_path, _priv_a, pub_pem_a = _write_pubkey(tmp_path)
    monkeypatch.setenv("FATHOM_RULESET_PUBKEY_PATH", str(pubkey_path))
    monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")

    app_a = build_app(require_signature=True)
    assert app_a.state.require_signature is True
    assert app_a.state.ruleset_pubkey == pub_pem_a, (
        "pubkey must still be loaded — env flag alone does not skip bootstrap"
    )
    app_a.state.engine = _seed_engine(tmp_path)
    app_a.state.attestation = AttestationService.generate_keypair()
    app_a.state.audit_sink = None

    with TestClient(app_a) as tc_a:
        body = {"ruleset_yaml": _ruleset_yaml("rule-env-only", "alice")}
        resp = tc_a.post("/v1/rules/reload", json=body, headers=AUTH)
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "unsigned_ruleset"

    # -----------------------------------------------------------------
    # (b) Only config false — env unset. Dev-escape is not triggered;
    #     build_app fails-closed because the pubkey is absent.
    # -----------------------------------------------------------------
    monkeypatch.delenv("FATHOM_ALLOW_UNSIGNED_RULESETS", raising=False)
    monkeypatch.delenv("FATHOM_RULESET_PUBKEY_PATH", raising=False)
    with pytest.raises(RuntimeError, match="ruleset pubkey unreadable or missing"):
        build_app(require_signature=False)

    # -----------------------------------------------------------------
    # (c) Both flags set — dev-escape active. WARN logged, pubkey is
    #     None, and unsigned POST returns 200.
    # -----------------------------------------------------------------
    monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
    with caplog.at_level(logging.WARNING, logger="fathom.integrations.rest"):
        app_c = build_app(require_signature=False)
    assert app_c.state.require_signature is False
    assert app_c.state.ruleset_pubkey is None
    warn_msgs = [
        r.message
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "ruleset signature verification disabled" in r.message
    ]
    assert len(warn_msgs) == 1, caplog.records

    app_c.state.engine = _seed_engine(tmp_path)
    app_c.state.attestation = AttestationService.generate_keypair()
    app_c.state.audit_sink = None

    with TestClient(app_c) as tc_c:
        body = {"ruleset_yaml": _ruleset_yaml("rule-both-flags", "carol")}
        resp = tc_c.post("/v1/rules/reload", json=body, headers=AUTH)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == {"hash_before", "hash_after", "attestation_token"}
