"""Tests for the creem Policy Studio JSON API (:mod:`fathom_studio.studio_api`).

These cover the *real*-engine surface the React/Babel SPA depends on, so the
hero flows can never silently fabricate a decision:

* ``GET /studio/api/scenarios`` / ``/rulesets`` / ``/ruleset/{id}`` expose the
  bundled scenarios and the real template / rule / module registries;
* ``POST /studio/api/evaluate`` returns a genuine ``Engine`` decision (deny
  *and* allow paths) with a non-empty ``rule_trace`` and a real
  ``duration_us``;
* every evaluation appends a hash-linked, Ed25519-signed audit record, and the
  chain's ``prev_hash`` links verify; ``POST /studio/api/audit/verify``
  cryptographically checks a minted signature;
* the SPA itself is served from ``/`` with its static creem assets;
* path-jail escapes are rejected (400) and malformed facts are 422;
* an anonymous caller gets 401 from every route — the JSON API is not a
  weaker door onto the engine than the REST app mounted beside it;
* rulesets resolve from packaged data, so an installed wheel works.

The audit chain is process-global module state, so it is reset before each
test via :func:`fathom_studio.studio_api._reset_audit_for_tests`.

Every route is gated on ``FATHOM_API_TOKEN``, so the client presents it as a
bearer header exactly as the SPA's same-origin ``fetch`` presents the cookie.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from fathom_studio import rulesets, studio_api
from fathom_studio.app import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator

#: A confidential agent reading secret data — the canonical fail-closed deny.
_DENY_FACTS = [
    {"template": "agent", "data": {"id": "carol", "clearance": "confidential"}},
    {
        "template": "data_request",
        "data": {"agent_id": "carol", "classification": "secret", "resource": "hr"},
    },
]

#: A top-secret agent reading secret data — clearance dominates, so allow.
_ALLOW_FACTS = [
    {"template": "agent", "data": {"id": "dana", "clearance": "top-secret"}},
    {
        "template": "data_request",
        "data": {"agent_id": "dana", "classification": "secret", "resource": "hr"},
    },
]


#: Bearer token the gated Studio routes require.
_TOKEN = "demo-token"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient with a clean audit chain and the Studio token presented."""
    monkeypatch.setenv("FATHOM_API_TOKEN", _TOKEN)
    monkeypatch.delenv("FATHOM_RULESET_ROOT", raising=False)
    studio_api._reset_audit_for_tests()
    with TestClient(create_app(), headers={"Authorization": f"Bearer {_TOKEN}"}) as c:
        yield c
    studio_api._reset_audit_for_tests()


@pytest.fixture
def anonymous_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient that presents no token."""
    monkeypatch.setenv("FATHOM_API_TOKEN", _TOKEN)
    monkeypatch.delenv("FATHOM_RULESET_ROOT", raising=False)
    studio_api._reset_audit_for_tests()
    with TestClient(create_app()) as c:
        yield c
    studio_api._reset_audit_for_tests()


# --------------------------------------------------------------------------
# Scenarios + ruleset registries
# --------------------------------------------------------------------------
def test_scenarios_expose_ruleset_and_facts(client: TestClient) -> None:
    """``/scenarios`` returns real scenarios, each tagged with its ruleset."""
    body = client.get("/studio/api/scenarios").json()
    items = body["items"]
    assert items, "expected at least one bundled scenario"
    by_id = {s["id"]: s for s in items}
    # The canonical deny demo is present and points at its example ruleset.
    hello = by_id["01-hello-allow-deny"]
    assert hello["ruleset"] == "01-hello-allow-deny"
    assert {f["template"] for f in hello["facts"]} == {"agent", "data_request"}


def test_rulesets_are_distinct(client: TestClient) -> None:
    """``/rulesets`` lists the distinct rulesets referenced by scenarios."""
    items = client.get("/studio/api/rulesets").json()["items"]
    ids = [r["id"] for r in items]
    assert "01-hello-allow-deny" in ids
    assert len(ids) == len(set(ids)), "ruleset ids must be distinct"


def test_ruleset_detail_dumps_real_registries(client: TestClient) -> None:
    """``/ruleset/{id}`` returns the real templates / rules / modules."""
    d = client.get("/studio/api/ruleset/01-hello-allow-deny").json()
    template_names = {t["name"] for t in d["templates"]}
    assert {"agent", "data_request"} <= template_names
    rule_names = {r["name"] for r in d["rules"]}
    assert "deny-secret-for-confidential" in rule_names
    # The deny rule's decision is the real ActionType, not a fabricated label.
    deny = next(r for r in d["rules"] if r["name"] == "deny-secret-for-confidential")
    assert deny["decision"] == "deny"
    # The rule's real ``when`` patterns survive — slot conditions, not just
    # template names — so the studio can render the actual matching logic.
    agent_pat = next(p for p in deny["when"] if p["template"] == "agent")
    assert any(
        c.get("slot") == "clearance" and "confidential" in (c.get("expression") or "")
        for c in agent_pat["conditions"]
    )
    # Symbol slots carry their allowed_values so the fact builder can offer a
    # constrained picker instead of free text.
    agent_tpl = next(t for t in d["templates"] if t["name"] == "agent")
    clearance = next(s for s in agent_tpl["slots"] if s["name"] == "clearance")
    assert clearance["allowed_values"] == [
        "unclassified",
        "confidential",
        "secret",
        "top-secret",
    ]


def test_ruleset_detail_unknown_is_404(client: TestClient) -> None:
    """An unknown ruleset surfaces as a 404, not an empty 200 or a 500."""
    assert client.get("/studio/api/ruleset/does-not-exist").status_code == 404


# --------------------------------------------------------------------------
# Evaluate — real decisions
# --------------------------------------------------------------------------
def test_evaluate_returns_real_deny(client: TestClient) -> None:
    """A confidential agent reading secret data is denied — with a real trace."""
    r = client.post(
        "/studio/api/evaluate",
        json={"ruleset": "01-hello-allow-deny", "facts": _DENY_FACTS},
    ).json()
    assert r["decision"] == "deny"
    assert "confidential" in r["reason"].lower()
    assert r["rule_trace"], "deny must carry a non-empty rule_trace"
    assert isinstance(r["duration_us"], int) and r["duration_us"] >= 0
    # The ruleset's rule registry rides along for trace rendering.
    assert any(rule["name"] == "deny-secret-for-confidential" for rule in r["rules"])


def test_evaluate_returns_real_allow(client: TestClient) -> None:
    """A top-secret agent reading secret data is allowed (clearance dominates)."""
    r = client.post(
        "/studio/api/evaluate",
        json={"ruleset": "01-hello-allow-deny", "facts": _ALLOW_FACTS},
    ).json()
    assert r["decision"] == "allow"
    assert r["rule_trace"], "allow path still fires a named rule"


def test_evaluate_rejects_path_escape(client: TestClient) -> None:
    """A ruleset that escapes the jail is a 400, never a filesystem read."""
    r = client.post(
        "/studio/api/evaluate",
        json={"ruleset": "../../../../etc", "facts": _DENY_FACTS},
    )
    assert r.status_code == 400


def test_evaluate_rejects_bad_fact(client: TestClient) -> None:
    """A fact that violates the template schema is a 422 client error."""
    r = client.post(
        "/studio/api/evaluate",
        json={
            "ruleset": "01-hello-allow-deny",
            "facts": [{"template": "agent", "data": {"id": "x", "clearance": "bogus"}}],
        },
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Signed, hash-linked audit chain
# --------------------------------------------------------------------------
def test_audit_chain_links_and_signs(client: TestClient) -> None:
    """Two evaluations produce a linked chain: seq increments, hashes link."""
    first = client.post(
        "/studio/api/evaluate",
        json={"ruleset": "01-hello-allow-deny", "facts": _DENY_FACTS},
    ).json()["audit"]
    second = client.post(
        "/studio/api/evaluate",
        json={"ruleset": "01-hello-allow-deny", "facts": _ALLOW_FACTS},
    ).json()["audit"]

    assert second["seq"] == first["seq"] + 1
    # The second record hash-links the first.
    assert second["prev_hash"] == first["hash"]
    assert first["prev_hash"] == "0" * 16  # genesis

    chain = client.get("/studio/api/audit").json()
    assert chain["count"] == 2
    # Newest first.
    assert chain["items"][0]["seq"] == second["seq"]


def test_audit_signature_verifies(client: TestClient) -> None:
    """A minted Ed25519 signature verifies via ``/audit/verify``."""
    rec = client.post(
        "/studio/api/evaluate",
        json={"ruleset": "01-hello-allow-deny", "facts": _DENY_FACTS},
    ).json()["audit"]
    if not rec["signature"]:
        pytest.skip("attestation extra not installed in this environment")
    out = client.post("/studio/api/audit/verify", json={"signature": rec["signature"]}).json()
    assert out["verified"] is True
    assert out["claims"]["hash"] == rec["hash"]
    assert out["claims"]["decision"] == "deny"


def test_audit_verify_rejects_garbage(client: TestClient) -> None:
    """A tampered / unparsable token does not verify."""
    out = client.post("/studio/api/audit/verify", json={"signature": "not.a.jwt"}).json()
    assert out["verified"] is False


# --------------------------------------------------------------------------
# SPA + static assets
# --------------------------------------------------------------------------
def test_home_serves_creem_spa(client: TestClient) -> None:
    """``/`` serves the creem single-page app shell."""
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="root"' in r.text
    assert "cs-app.jsx" in r.text


def test_creem_static_assets_served(client: TestClient) -> None:
    """The SPA's JS/JSX/CSS assets are reachable under ``/creem``."""
    for asset in ("api.js", "cs-bench.jsx", "creem-ds.css"):
        assert client.get(f"/creem/{asset}").status_code == 200


# --------------------------------------------------------------------------
# Token gate (studio-api-unauthenticated)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("method", "route", "body"),
    [
        ("get", "/studio/api/scenarios", None),
        ("get", "/studio/api/rulesets", None),
        ("get", "/studio/api/ruleset/01-hello-allow-deny", None),
        ("get", "/studio/api/audit", None),
        ("post", "/studio/api/evaluate", {"ruleset": "01-hello-allow-deny", "facts": []}),
        ("post", "/studio/api/audit/verify", {"signature": "x"}),
    ],
)
def test_every_route_requires_a_token(
    anonymous_client: TestClient,
    method: str,
    route: str,
    body: dict[str, object] | None,
) -> None:
    """No anonymous caller reads the rule registry or drives the engine."""
    kwargs = {"json": body} if body is not None else {}
    response = getattr(anonymous_client, method)(route, **kwargs)
    assert response.status_code == 401
    # The rule registry must not leak in the body of the rejection either.
    assert "deny-secret-for-confidential" not in response.text


def test_studio_closed_when_no_token_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unconfigured Studio (no ``FATHOM_API_TOKEN``) serves no engine route."""
    monkeypatch.delenv("FATHOM_API_TOKEN", raising=False)
    with TestClient(create_app(), headers={"Authorization": "Bearer anything"}) as c:
        assert c.get("/studio/api/rulesets").status_code == 401


# --------------------------------------------------------------------------
# Packaged rulesets (studio-examples-path-missing-in-wheel)
# --------------------------------------------------------------------------
def test_rulesets_are_package_data_not_a_repo_walk() -> None:
    """The demo rulesets live inside the package, so a wheel install works.

    The old ``Path(__file__).parents[3] / "examples"`` walk pointed outside the
    package; from site-packages it resolved to a directory that does not exist.
    """
    root = rulesets.packaged_root()
    assert root.is_dir()
    # It is inside the installed package, not a repo-root sibling of ``src/``.
    assert root.parent == Path(rulesets.__file__).resolve().parent
    for scenario_dir in ("01-hello-allow-deny", "05-langchain-guardrails"):
        assert (root / scenario_dir / "rules").is_dir()
        assert (root / scenario_dir / "templates").is_dir()


def test_evaluate_works_without_the_repo_examples_dir(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A real evaluation succeeds with the CWD moved away from the checkout.

    This is the installed-wheel shape: nothing above the package on disk is a
    Fathom repo, so only packaged data can satisfy the ruleset lookup.
    """
    monkeypatch.chdir(tmp_path)
    r = client.post(
        "/studio/api/evaluate",
        json={"ruleset": "01-hello-allow-deny", "facts": _DENY_FACTS},
    ).json()
    assert r["decision"] == "deny"


def test_packaged_rulesets_match_the_repo_examples() -> None:
    """The packaged copies stay byte-identical to ``examples/0N-*`` YAML.

    Skipped outside a source checkout. Guards against the bundled demo
    rulesets silently drifting from the examples they are copied from.
    """
    repo_examples = Path(__file__).resolve().parents[3] / "examples"
    if not repo_examples.is_dir():
        pytest.skip("not running from a source checkout")
    packaged = rulesets.packaged_root()
    for yaml_path in sorted(packaged.rglob("*.yaml")):
        origin = repo_examples / yaml_path.relative_to(packaged)
        assert origin.is_file(), f"packaged ruleset file has no origin: {origin}"
        assert yaml_path.read_bytes() == origin.read_bytes(), f"drifted: {origin}"


def test_missing_ruleset_root_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A misconfigured ``FATHOM_RULESET_ROOT`` says so instead of degrading."""
    monkeypatch.setenv("FATHOM_RULESET_ROOT", "/nonexistent/fathom/rulesets")
    with pytest.raises(rulesets.RulesetRootError, match="does not exist"):
        rulesets.ruleset_root()
