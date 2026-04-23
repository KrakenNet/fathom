"""Tests for ``GET /v1/status`` (C7, FR-20, AC-5.7).

Validates the 3-field status response shape and that ``ruleset_hash`` advances
after a successful ``POST /v1/rules/reload`` and stays in sync with
``engine.ruleset_hash``.

Uses the dev-escape combination (``require_signature=False`` +
``FATHOM_ALLOW_UNSIGNED_RULESETS=1``) so tests can focus on the status/reload
coupling without Ed25519 signing plumbing — signed-path coverage lives in
``test_rest_reload.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from fastapi.testclient import TestClient

from fathom import __version__ as _fathom_version
from fathom.attestation import AttestationService
from fathom.engine import Engine
from fathom.integrations.rest import build_app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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
        "templates:\n  - name: agent\n    slots:\n      - name: id\n        type: symbol\n"
    )
    (tmp_path / "modules.yaml").write_text(
        "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"
    )
    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    engine.load_modules(str(tmp_path / "modules.yaml"))
    initial = _ruleset_yaml("rule-seed", "seed")
    (tmp_path / "rules-seed.yaml").write_text(initial)
    engine.load_rules(str(tmp_path / "rules-seed.yaml"))
    return engine


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
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


def test_status_shape(client: TestClient) -> None:
    """``GET /v1/status`` → 200 with exactly ``{ruleset_hash, version, loaded_at}``.

    AC-5.7: status endpoint exposes the currently-loaded ruleset hash, the
    Fathom library version, and an ISO-formatted load timestamp. Unauthenticated
    (matches ``/health``).
    """
    resp = client.get("/v1/status")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Exactly the three documented fields.
    assert set(data.keys()) == {"ruleset_hash", "version", "loaded_at"}

    # ruleset_hash: non-null, sha256-prefixed (engine was seeded in fixture).
    assert isinstance(data["ruleset_hash"], str)
    assert data["ruleset_hash"].startswith("sha256:")

    # version: matches fathom.__version__.
    assert data["version"] == _fathom_version

    # loaded_at: ISO-8601 string (boot_time_iso until first reload).
    assert isinstance(data["loaded_at"], str)
    # Sanity: parseable as ISO-8601.
    from datetime import datetime

    datetime.fromisoformat(data["loaded_at"])


def test_status_hash_advances_after_reload(client: TestClient) -> None:
    """``ruleset_hash`` advances after reload and equals ``engine.ruleset_hash``.

    FR-20: successful reload advances the hash exposed by ``/v1/status``.
    AC-5.7: the exposed hash tracks ``engine.ruleset_hash`` (no drift).
    """
    # Initial snapshot.
    resp = client.get("/v1/status")
    assert resp.status_code == 200, resp.text
    before = resp.json()
    hash_before = before["ruleset_hash"]
    loaded_before = before["loaded_at"]

    # Reload with a new ruleset.
    body = {"ruleset_yaml": _ruleset_yaml("rule-new", "alice")}
    reload_resp = client.post("/v1/rules/reload", json=body, headers=AUTH)
    assert reload_resp.status_code == 200, reload_resp.text
    reload_data = reload_resp.json()
    assert reload_data["hash_before"] == hash_before
    assert reload_data["hash_after"] != hash_before

    # Post-reload status.
    resp = client.get("/v1/status")
    assert resp.status_code == 200, resp.text
    after = resp.json()

    # Hash advanced …
    assert after["ruleset_hash"] != hash_before
    assert after["ruleset_hash"] == reload_data["hash_after"]
    # … and equals the live engine's hash (no drift).
    assert after["ruleset_hash"] == client.app.state.engine.ruleset_hash

    # loaded_at updated to reload timestamp.
    assert after["loaded_at"] != loaded_before

    # Version unchanged.
    assert after["version"] == _fathom_version
