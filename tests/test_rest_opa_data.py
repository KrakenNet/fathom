"""OPA-compatible Data API on the REST server.

The point of `POST /v1/data/<path>` is that an existing OPA caller keeps
working, so the fixtures here are a real Rego policy put through
`fathom convert rego` and then served -- if the two halves ever disagree
about how `input.user.role` becomes a slot, these fail.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from fastapi.testclient import TestClient

from fathom.integrations.rest import app
from fathom.rego import convert_ast, flatten_input

if TYPE_CHECKING:
    from collections.abc import Iterator

FIXTURES = Path(__file__).parent / "fixtures" / "rego"


def _write_converted_pack(root: Path, fixture: str) -> None:
    """Convert a Rego fixture and write it as a ruleset under *root*."""
    result = convert_ast(json.loads((FIXTURES / f"{fixture}.json").read_text(encoding="utf-8")))
    payloads = {
        "templates": {"templates": result.templates},
        "modules": {"modules": result.modules, "focus_order": [result.module]},
        "rules": {"module": result.module, "ruleset": result.module, "rules": result.rules},
    }
    for kind, payload in payloads.items():
        (root / kind).mkdir(parents=True, exist_ok=True)
        (root / kind / "converted.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )


@pytest.fixture
def ruleset_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A jail root holding the converted `authz.basic` policy at authz/basic."""
    _write_converted_pack(tmp_path / "authz" / "basic", "basic")
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
    yield tmp_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": "Bearer testtok"}


_ADMIN_READ = {"user": {"role": "admin", "suspended": False}, "action": "read"}
_ADMIN_DELETE = {"user": {"role": "admin", "suspended": False}, "action": "delete"}
_SUSPENDED = {"user": {"role": "admin", "suspended": True}, "action": "read"}


# ---------------------------------------------------------------------------
# The OPA envelope
# ---------------------------------------------------------------------------


class TestDecisionDocument:
    def test_allow_answers_a_bare_boolean(self, ruleset_root, client, auth) -> None:
        response = client.post(
            "/v1/data/authz/basic/allow", json={"input": _ADMIN_READ}, headers=auth
        )
        assert response.status_code == 200
        assert response.json() == {"result": True}

    def test_the_same_input_is_false_for_the_deny_document(
        self, ruleset_root, client, auth
    ) -> None:
        response = client.post(
            "/v1/data/authz/basic/deny", json={"input": _ADMIN_READ}, headers=auth
        )
        assert response.json() == {"result": False}

    def test_a_denied_input_flips_both_documents(self, ruleset_root, client, auth) -> None:
        allow = client.post("/v1/data/authz/basic/allow", json={"input": _SUSPENDED}, headers=auth)
        deny = client.post("/v1/data/authz/basic/deny", json={"input": _SUSPENDED}, headers=auth)
        assert allow.json() == {"result": False}
        assert deny.json() == {"result": True}

    def test_a_rule_that_does_not_fire_falls_to_the_default_decision(
        self, ruleset_root, client, auth
    ) -> None:
        """No rule matches `delete`; the engine's default deny still answers."""
        response = client.post(
            "/v1/data/authz/basic/allow", json={"input": _ADMIN_DELETE}, headers=auth
        )
        assert response.json() == {"result": False}

    def test_an_empty_input_is_accepted(self, ruleset_root, client, auth) -> None:
        response = client.post("/v1/data/authz/basic/allow", json={}, headers=auth)
        assert response.status_code == 200
        assert response.json() == {"result": False}


class TestPackageDocument:
    def test_dropping_the_trailing_rule_returns_the_whole_decision(
        self, ruleset_root, client, auth
    ) -> None:
        response = client.post("/v1/data/authz/basic", json={"input": _ADMIN_READ}, headers=auth)
        body = response.json()["result"]
        assert body["allow"] is True
        assert body["deny"] is False
        assert body["decision"] == "allow"
        assert body["rule_trace"]

    def test_the_reason_survives_the_round_trip(self, ruleset_root, client, auth) -> None:
        """OPA has nowhere to put a reason; the package document does."""
        response = client.post("/v1/data/authz/basic", json={"input": _ADMIN_READ}, headers=auth)
        assert response.json()["result"]["reason"] is not None


# ---------------------------------------------------------------------------
# Input mapping
# ---------------------------------------------------------------------------


class TestInputMapping:
    def test_nested_input_reaches_the_flattened_slot(self, ruleset_root, client, auth) -> None:
        """`input.user.role` is slot `user_role`; a wrong role must not allow."""
        wrong = {"user": {"role": "guest", "suspended": False}, "action": "read"}
        response = client.post("/v1/data/authz/basic/allow", json={"input": wrong}, headers=auth)
        assert response.json() == {"result": False}

    def test_fields_no_slot_declares_are_dropped_not_rejected(
        self, ruleset_root, client, auth
    ) -> None:
        """An OPA caller sends its whole input; unread fields must not 500."""
        noisy = dict(_ADMIN_READ, tags=["a", "b"], trace=None, nested={"deep": {"x": 1}})
        response = client.post("/v1/data/authz/basic/allow", json={"input": noisy}, headers=auth)
        assert response.json() == {"result": True}

    def test_booleans_become_the_symbols_the_converter_emits(self) -> None:
        """The bridge and the converter have to agree, or nothing matches."""
        assert flatten_input({"a": True, "b": False}) == {"a": "true", "b": "false"}


# ---------------------------------------------------------------------------
# The GET form
# ---------------------------------------------------------------------------


class TestGetForm:
    def test_input_as_a_query_parameter(self, ruleset_root, client, auth) -> None:
        query = urllib.parse.urlencode({"input": json.dumps(_ADMIN_READ)})
        response = client.get(f"/v1/data/authz/basic/allow?{query}", headers=auth)
        assert response.json() == {"result": True}

    def test_no_input_at_all_is_an_empty_document(self, ruleset_root, client, auth) -> None:
        assert client.get("/v1/data/authz/basic/allow", headers=auth).json() == {"result": False}

    def test_malformed_json_says_so(self, ruleset_root, client, auth) -> None:
        response = client.get("/v1/data/authz/basic/allow?input=not-json", headers=auth)
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_parameter"

    def test_a_json_scalar_is_not_an_input_document(self, ruleset_root, client, auth) -> None:
        response = client.get("/v1/data/authz/basic/allow?input=42", headers=auth)
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Errors, in OPA's envelope
# ---------------------------------------------------------------------------


class TestErrors:
    def test_errors_use_opas_shape_not_fathoms(self, ruleset_root, client, auth) -> None:
        """A client written against OPA parses code/message, not error/detail."""
        response = client.post("/v1/data/nope/allow", json={"input": {}}, headers=auth)
        assert response.status_code == 400
        assert set(response.json()) == {"code", "message"}

    def test_the_whole_data_document_is_not_addressable(self, ruleset_root, client, auth) -> None:
        response = client.post("/v1/data/", json={"input": {}}, headers=auth)
        assert response.status_code == 400
        assert "name a ruleset" in response.json()["message"]

    def test_an_unknown_template_lists_the_ones_that_exist(
        self, ruleset_root, client, auth
    ) -> None:
        response = client.post(
            "/v1/data/authz/basic/allow?template=request", json={"input": {}}, headers=auth
        )
        assert response.status_code == 400
        assert "'input'" in response.json()["message"]

    def test_path_traversal_out_of_the_jail_is_refused(self, ruleset_root, client, auth) -> None:
        response = client.post("/v1/data/..%2F..%2Fetc/allow", json={"input": {}}, headers=auth)
        assert response.status_code == 400

    def test_the_surface_is_authenticated_unlike_opas(self, ruleset_root, client) -> None:
        """OPA's data API is open by default. Adopting that here would put an
        authentication hole next to endpoints that do not have one."""
        assert client.post("/v1/data/authz/basic/allow", json={"input": {}}).status_code == 401
        assert client.get("/v1/data/authz/basic/allow").status_code == 401


# ---------------------------------------------------------------------------
# Addressing
# ---------------------------------------------------------------------------


class TestAddressing:
    def test_a_single_segment_path_addresses_the_jail_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client, auth
    ) -> None:
        """`/v1/data/allow` is the root ruleset, mirroring package-less Rego."""
        _write_converted_pack(tmp_path, "basic")
        monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
        monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
        response = client.post("/v1/data/allow", json={"input": _ADMIN_READ}, headers=auth)
        assert response.json() == {"result": True}

    def test_the_route_is_in_the_openapi_document(self) -> None:
        """The exported schema is what SDK generators read; a route missing
        from it is a route nobody downstream knows exists."""
        paths = app.openapi()["paths"]["/v1/data/{path}"]
        assert set(paths) >= {"get", "post"}
