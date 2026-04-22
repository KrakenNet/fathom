"""Request-shape + happy-path tests for ``POST /v1/rules/reload`` (C5, AC-5.1).

Validates the exactly-one-of ``ruleset_path`` / ``ruleset_yaml`` contract on
``RulesetReloadRequest`` plus the 3-field happy-path response shape
(``hash_before`` / ``hash_after`` / ``attestation_token``).

The fixture here runs against ``build_app(require_signature=False)`` with the
dev-escape env var set (``FATHOM_ALLOW_UNSIGNED_RULESETS=1``) — signature
verification is covered by the sibling T-3.8 / T-3.9 tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from fastapi.testclient import TestClient

from fathom.attestation import AttestationService
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
