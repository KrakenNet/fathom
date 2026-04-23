"""gRPC ``Reload`` parity with ``POST /v1/rules/reload`` (C5, FR-15, AC-5.2).

Spins up the Python gRPC server on a free port in-process, registers a
fully-configured :class:`FathomServicer` (engine + attestation + ruleset
pubkey + audit sink), and drives it via a generated-stub client over an
``insecure_channel`` loopback.

Two subtests:

* ``test_grpc_reload_happy_path`` — signed ruleset → ``ReloadResponse``
  with populated ``ruleset_hash_before`` / ``ruleset_hash_after`` /
  ``attestation_token`` (3-field parity with REST).
* ``test_grpc_reload_fail_closed_invalid_signature`` — unsigned payload
  when ``require_signature=True`` → ``grpc.RpcError`` with
  ``StatusCode.INVALID_ARGUMENT`` (fail-closed parity).

Shared setup mirrors ``tests/integrations/test_rest_reload.py`` so both
protocol surfaces exercise the same engine / keypair / ruleset shape.
"""

from __future__ import annotations

import socket
from concurrent import futures
from typing import TYPE_CHECKING, Any

import grpc
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from fathom.attestation import AttestationService
from fathom.engine import Engine
from fathom.integrations.grpc_server import FathomServicer
from fathom.proto import fathom_pb2, fathom_pb2_grpc

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _ruleset_yaml(rule_name: str, subject: str) -> bytes:
    """Build a self-contained ruleset YAML payload for Reload."""
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
    ).encode("utf-8")


def _seed_engine(tmp_path: Path) -> Engine:
    """Engine with templates + modules + initial ruleset so hash_before is real."""
    (tmp_path / "templates.yaml").write_text(
        "templates:\n  - name: agent\n    slots:\n      - name: id\n        type: symbol\n"
    )
    (tmp_path / "modules.yaml").write_text(
        "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"
    )
    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    engine.load_modules(str(tmp_path / "modules.yaml"))
    (tmp_path / "rules-seed.yaml").write_bytes(_ruleset_yaml("rule-seed", "seed"))
    engine.load_rules(str(tmp_path / "rules-seed.yaml"))
    return engine


def _free_port() -> int:
    """Grab an ephemeral port, release it, and return the number.

    Small race with re-bind exists, but ``add_insecure_port`` binds
    immediately when the server starts so the window is sub-millisecond
    for loopback tests.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _ListAuditSink:
    """Duck-typed in-memory sink collecting ``write()`` records."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)


@pytest.fixture
def grpc_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[str, Ed25519PrivateKey, _ListAuditSink]]:
    """Spin up a FathomServicer on a free loopback port.

    Yields ``(target, private_key, audit_sink)`` so tests can build signed
    requests and assert on audit records. ``require_signature=True`` so
    fail-closed behaviour is exercisable without a config toggle.
    """
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))

    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    audit_sink = _ListAuditSink()
    servicer = FathomServicer(
        default_engine=_seed_engine(tmp_path),
        attestation=AttestationService.generate_keypair(),
        audit_sink=audit_sink,
        ruleset_pubkey=pub_pem,
        require_signature=True,
    )

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    fathom_pb2_grpc.add_FathomServiceServicer_to_server(servicer, server)
    port = _free_port()
    server.add_insecure_port(f"127.0.0.1:{port}")
    server.start()
    try:
        yield f"127.0.0.1:{port}", priv, audit_sink
    finally:
        server.stop(grace=None).wait(timeout=2.0)


_AUTH_META = (("authorization", "Bearer testtok"),)


def test_grpc_reload_happy_path(
    grpc_server: tuple[str, Ed25519PrivateKey, _ListAuditSink],
) -> None:
    """Signed Reload → 3-field ReloadResponse (parity with REST 200 body).

    AC-5.2: gRPC ``Reload`` returns ``ReloadResponse`` populated with
    ``ruleset_hash_before`` / ``ruleset_hash_after`` / ``attestation_token``.
    The two hashes differ (different YAML bytes than the seed ruleset) and
    the attestation token is a non-empty JWT.
    """
    target, priv, sink = grpc_server
    yaml_bytes = _ruleset_yaml("rule-grpc", "alice")
    sig = priv.sign(yaml_bytes)

    with grpc.insecure_channel(target) as channel:
        stub = fathom_pb2_grpc.FathomServiceStub(channel)
        req = fathom_pb2.ReloadRequest(
            ruleset_yaml=yaml_bytes.decode("utf-8"),
            signature=sig,
        )
        resp = stub.Reload(req, metadata=_AUTH_META, timeout=5.0)

    assert resp.ruleset_hash_before.startswith("sha256:")
    assert resp.ruleset_hash_after.startswith("sha256:")
    assert resp.ruleset_hash_before != resp.ruleset_hash_after
    assert resp.attestation_token  # non-empty JWT

    reloaded = [r for r in sink.records if r.get("event_type") == "ruleset_reloaded"]
    assert len(reloaded) == 1, sink.records
    assert reloaded[0]["ruleset_hash_before"] == resp.ruleset_hash_before
    assert reloaded[0]["ruleset_hash_after"] == resp.ruleset_hash_after


def test_grpc_reload_fail_closed_invalid_signature(
    grpc_server: tuple[str, Ed25519PrivateKey, _ListAuditSink],
) -> None:
    """Unsigned Reload on fail-closed server → INVALID_ARGUMENT (REST-400 parity).

    AC-5.5 / FR-15: with ``require_signature=True`` and no ``signature``
    field, the server rejects the call with ``grpc.StatusCode.INVALID_ARGUMENT``
    and emits one ``ruleset_reload_rejected`` audit record.
    """
    target, _priv, sink = grpc_server
    yaml_bytes = _ruleset_yaml("rule-unsigned", "bob")

    with grpc.insecure_channel(target) as channel:
        stub = fathom_pb2_grpc.FathomServiceStub(channel)
        req = fathom_pb2.ReloadRequest(ruleset_yaml=yaml_bytes.decode("utf-8"))
        with pytest.raises(grpc.RpcError) as excinfo:
            stub.Reload(req, metadata=_AUTH_META, timeout=5.0)

    assert excinfo.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "unsigned_ruleset" in excinfo.value.details()

    rejected = [r for r in sink.records if r.get("event_type") == "ruleset_reload_rejected"]
    assert len(rejected) == 1, sink.records
    assert rejected[0]["reason"] == "missing_signature"
