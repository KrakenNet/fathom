"""Every security switch, in every combination, against the operation it guards.

Structural check E from the audit post-mortem. Two of these switches are
documented as a *dual* control -- both must be lowered before a ruleset can
be reloaded unsigned -- and the suite tested only the two cells where they
moved together. The cell where one moved alone was the hole: a lone
``build_app(require_signature=False)`` turned signature verification off
while the operator still believed the env var was holding the floor.

The lesson generalises past that one pair. A switch is only understood in
combination with the other switches, so each matrix here is a full
``itertools.product`` and every cell is asserted on the operation the switch
guards -- not on an internal flag, and not on a mock.

Three matrices:

- **reload signature** -- ``require_signature`` x ``FATHOM_ALLOW_UNSIGNED_RULESETS``
  x what the request carries;
- **policy selection** -- mounted Engine x ``session_id`` x the ruleset the
  caller names, on ``POST /v1/evaluate``;
- **auth** -- ``FATHOM_API_TOKEN`` x ``FATHOM_ADMIN_TOKEN`` x the token
  presented, on a data-plane and an admin endpoint.
"""

from __future__ import annotations

import base64
import itertools
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from fathom.attestation import AttestationService
from fathom.engine import Engine
from fathom.integrations.rest import build_app, session_store

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

DELETE_FACTS = [{"template": "input", "data": {"user": "mallory", "action": "delete"}}]

_TEMPLATES = {
    "templates": [
        {
            "name": "input",
            "slots": [
                {"name": "user", "type": "string", "required": True},
                {"name": "action", "type": "string", "required": True},
            ],
        }
    ]
}
_MODULES = {"modules": [{"name": "policy", "description": "policy"}], "focus_order": ["policy"]}


def _rules(name: str, action: str, reason: str) -> dict[str, Any]:
    """A one-rule ruleset that answers every request the same way."""
    return {
        "module": "policy",
        "ruleset": name,
        "version": "1.0",
        "rules": [
            {
                "name": f"{name}-rule",
                "when": [
                    {
                        "template": "input",
                        "conditions": [{"slot": "action", "expression": "matches(.+)"}],
                    }
                ],
                "then": {"action": action, "reason": reason},
            }
        ],
    }


STRICT_REASON = "STRICT: denied"
LOOSE_REASON = "LOOSE: allowed"


def _write_ruleset(root: Path, name: str, action: str, reason: str) -> Path:
    directory = root / name
    (directory / "templates").mkdir(parents=True)
    (directory / "modules").mkdir()
    (directory / "rules").mkdir()
    (directory / "templates" / "t.yaml").write_text(yaml.safe_dump(_TEMPLATES))
    (directory / "modules" / "m.yaml").write_text(yaml.safe_dump(_MODULES))
    (directory / "rules" / "r.yaml").write_text(yaml.safe_dump(_rules(name, action, reason)))
    return directory


@pytest.fixture
def rulesets(tmp_path: Path) -> dict[str, Path]:
    """A ``strict`` ruleset that denies and a ``loose`` one that allows."""
    root = tmp_path / "rules"
    root.mkdir()
    return {
        "strict": _write_ruleset(root, "strict", "deny", STRICT_REASON),
        "loose": _write_ruleset(root, "loose", "allow", LOOSE_REASON),
    }


@pytest.fixture(autouse=True)
def _clean_sessions() -> Iterator[None]:
    """The session store is module state on the REST app; cells must not share it."""
    session_store.clear()
    yield
    session_store.clear()


@pytest.fixture
def keypair(tmp_path: Path) -> tuple[Ed25519PrivateKey, Path]:
    """A ruleset signing key and the PEM public half on disk."""
    private = Ed25519PrivateKey.generate()
    pubkey_path = tmp_path / "ruleset.pub"
    pubkey_path.write_bytes(
        private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    return private, pubkey_path


class _RecordingSink:
    """Collects audit records so a rejection can be asserted on, not assumed."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)


# ----------------------------------------------------------------------
# Matrix 1: the reload signature switches
# ----------------------------------------------------------------------

SIGNATURE_CELLS = list(
    itertools.product([True, False], [True, False], ["valid", "absent", "wrong"])
)


@pytest.mark.parametrize(("require_signature", "allow_unsigned", "signature"), SIGNATURE_CELLS)
def test_a_reload_is_verified_unless_both_switches_are_lowered(
    require_signature: bool,
    allow_unsigned: bool,
    signature: str,
    rulesets: dict[str, Path],
    keypair: tuple[Ed25519PrivateKey, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The dev escape needs both halves; one alone must not lower the floor."""
    private, pubkey_path = keypair
    monkeypatch.setenv("FATHOM_API_TOKEN", "tok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path / "rules"))
    monkeypatch.setenv("FATHOM_RULESET_PUBKEY_PATH", str(pubkey_path))
    if allow_unsigned:
        monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
    else:
        monkeypatch.delenv("FATHOM_ALLOW_UNSIGNED_RULESETS", raising=False)

    sink = _RecordingSink()
    app = build_app(require_signature=require_signature)
    app.state.engine = Engine.from_rules(str(rulesets["strict"]))
    app.state.attestation = AttestationService.generate_keypair()
    app.state.audit_sink = sink

    payload = yaml.safe_dump(_rules("swapped", "allow", LOOSE_REASON)).encode()
    body: dict[str, Any] = {"ruleset_yaml": payload.decode()}
    if signature == "valid":
        body["signature"] = base64.b64encode(private.sign(payload)).decode()
    elif signature == "wrong":
        body["signature"] = base64.b64encode(Ed25519PrivateKey.generate().sign(payload)).decode()

    with TestClient(app) as client:
        response = client.post(
            "/v1/rules/reload", json=body, headers={"Authorization": "Bearer tok"}
        )
        decision = client.post(
            "/v1/evaluate",
            json={"ruleset": "strict", "facts": DELETE_FACTS},
            headers={"Authorization": "Bearer tok"},
        ).json()

    dev_escape = not require_signature and allow_unsigned
    accepted = signature == "valid" or dev_escape

    if accepted:
        assert response.status_code == 200, response.text
        assert decision["reason"] == LOOSE_REASON, "an accepted reload must reach the data plane"
    else:
        assert response.status_code == 400, response.text
        assert response.json()["error"] == "unsigned_ruleset"
        assert decision["reason"] == STRICT_REASON, "a rejected reload must change nothing"
        assert [r["event_type"] for r in sink.records] == ["ruleset_reload_rejected"]


PUBKEY_CELLS = list(itertools.product([True, False], [True, False], [True, False]))


@pytest.mark.parametrize(("require_signature", "allow_unsigned", "pubkey_present"), PUBKEY_CELLS)
def test_a_server_that_cannot_verify_refuses_to_start(
    require_signature: bool,
    allow_unsigned: bool,
    pubkey_present: bool,
    keypair: tuple[Ed25519PrivateKey, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No pubkey and no full dev escape is a server that could never verify."""
    _private, pubkey_path = keypair
    if pubkey_present:
        monkeypatch.setenv("FATHOM_RULESET_PUBKEY_PATH", str(pubkey_path))
    else:
        monkeypatch.delenv("FATHOM_RULESET_PUBKEY_PATH", raising=False)
    if allow_unsigned:
        monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
    else:
        monkeypatch.delenv("FATHOM_ALLOW_UNSIGNED_RULESETS", raising=False)

    dev_escape = not require_signature and allow_unsigned
    if pubkey_present or dev_escape:
        app = build_app(require_signature=require_signature)
        assert (app.state.ruleset_pubkey is None) == dev_escape
    else:
        with pytest.raises(RuntimeError, match="ruleset pubkey"):
            build_app(require_signature=require_signature)


# ----------------------------------------------------------------------
# Matrix 2: who chooses the policy
# ----------------------------------------------------------------------

SELECTION_CELLS = list(itertools.product([True, False], [True, False], ["strict", "loose"]))


@pytest.mark.parametrize(("mounted", "sessioned", "named"), SELECTION_CELLS)
def test_the_data_plane_caller_never_chooses_the_policy_on_a_mounted_server(
    mounted: bool,
    sessioned: bool,
    named: str,
    rulesets: dict[str, Path],
    keypair: tuple[Ed25519PrivateKey, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``session_id`` is a request field, not a policy switch."""
    _private, pubkey_path = keypair
    monkeypatch.setenv("FATHOM_API_TOKEN", "tok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path / "rules"))
    monkeypatch.setenv("FATHOM_RULESET_PUBKEY_PATH", str(pubkey_path))
    monkeypatch.delenv("FATHOM_ALLOW_UNSIGNED_RULESETS", raising=False)

    app = build_app()
    app.state.engine = Engine.from_rules(str(rulesets["strict"])) if mounted else None
    app.state.attestation = AttestationService.generate_keypair()
    app.state.audit_sink = None

    body: dict[str, Any] = {"ruleset": named, "facts": DELETE_FACTS}
    if sessioned:
        body["session_id"] = "s1"

    with TestClient(app) as client:
        response = client.post("/v1/evaluate", json=body, headers={"Authorization": "Bearer tok"})

    if mounted and sessioned:
        # A session needs its own working memory, so it cannot be the mounted
        # Engine; and any other Engine is a policy the caller chose. Refused.
        assert response.status_code == 400, response.text
        assert response.json()["error"] == "sessions_unavailable"
        return

    assert response.status_code == 200, response.text
    by_name = {"strict": STRICT_REASON, "loose": LOOSE_REASON}
    expected = STRICT_REASON if mounted else by_name[named]
    assert response.json()["reason"] == expected


# ----------------------------------------------------------------------
# Matrix 3: the two tokens
# ----------------------------------------------------------------------

API_TOKEN = "data-plane-token"
ADMIN_TOKEN = "admin-token"
AUTH_CELLS = list(
    itertools.product(
        [True, False],
        [True, False],
        ["none", "api", "admin", "wrong"],
        ["/v1/evaluate", "/v1/rules/reload"],
    )
)


@pytest.mark.parametrize(("api_set", "admin_set", "presented", "endpoint"), AUTH_CELLS)
def test_each_endpoint_accepts_exactly_the_token_it_is_scoped_to(
    api_set: bool,
    admin_set: bool,
    presented: str,
    endpoint: str,
    rulesets: dict[str, Path],
    keypair: tuple[Ed25519PrivateKey, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An unset token is not an open door, and the data-plane token is not admin."""
    _private, pubkey_path = keypair
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path / "rules"))
    monkeypatch.setenv("FATHOM_RULESET_PUBKEY_PATH", str(pubkey_path))
    monkeypatch.delenv("FATHOM_ALLOW_UNSIGNED_RULESETS", raising=False)
    for name, wanted in (("FATHOM_API_TOKEN", api_set), ("FATHOM_ADMIN_TOKEN", admin_set)):
        value = API_TOKEN if name == "FATHOM_API_TOKEN" else ADMIN_TOKEN
        if wanted:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name, raising=False)

    app = build_app()
    app.state.engine = Engine.from_rules(str(rulesets["strict"]))
    app.state.attestation = AttestationService.generate_keypair()
    app.state.audit_sink = None

    headers = {
        "api": {"Authorization": f"Bearer {API_TOKEN}"},
        "admin": {"Authorization": f"Bearer {ADMIN_TOKEN}"},
        "wrong": {"Authorization": "Bearer not-a-token"},
        "none": {},
    }[presented]
    body = (
        {"ruleset": "strict", "facts": DELETE_FACTS}
        if endpoint == "/v1/evaluate"
        else {"ruleset_yaml": yaml.safe_dump(_rules("swapped", "allow", LOOSE_REASON))}
    )

    with TestClient(app) as client:
        response = client.post(endpoint, json=body, headers=headers)

    if endpoint == "/v1/evaluate":
        authorised = api_set and presented == "api"
    elif admin_set:
        authorised = presented == "admin"
    else:
        authorised = api_set and presented == "api"

    assert (response.status_code != 401) is authorised, response.text
