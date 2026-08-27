"""A standing deny must still deny on call 2, whichever door the call came in.

CLIPS refraction is per-activation: a rule whose LHS mentions only facts that
outlive one request matches once and stays refracted, while a higher-salience
allow rule re-fires on each fresh request fact. Under a decision that has to
be *rendered* by a rule, that turns a hard deny on call 1 into a permit on
calls 2..N. Every shipped rule pack -- owasp_agentic, nist-800-53, hipaa,
cmmc -- contains deny rules of exactly that shape.

The fix for this landed in :meth:`Engine.evaluate_once`, and the regression
test was parametrized over the five framework adapters, all of which funnel
into ``evaluate_once``. It was not parametrized over the entry points. The
re-audit then found the identical fail-open on ``Engine.evaluate``, on the MCP
``fathom.evaluate`` tool, and in the ``fathom repl`` -- three doors into the
same engine, none of them adapters.

So the invariant is stated once here and driven through every door, and
``test_no_entry_point_is_missing_from_the_contract`` reflects over the FastAPI
route table, the gRPC servicer and the MCP tool registry so a transport added
later cannot ship uncontracted.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from fathom.engine import Engine

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from fathom.integrations.mcp_server import FathomMCPServer

#: How many times the same standing policy is asked the same question.
TURNS = 3

AGENT_ID = "a-1"

_TEMPLATES = """
templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
  - name: quarantine
    slots:
      - name: agent_id
        type: string
        required: true
  - name: tool_call
    slots:
      - name: agent_id
        type: string
        required: true
      - name: tool
        type: symbol
        required: true
      - name: call_id
        type: string
        default: ""
"""

_MODULES = """
modules:
  - name: policy
focus_order:
  - policy
"""

# `deny-quarantined-agent` deliberately does not mention tool_call: a
# quarantine is a property of the agent, not of one call. That is what makes
# it refract after the first evaluation while `allow-read-tool` keeps firing.
_RULES = """
module: policy
ruleset: repeat-stability
version: "1.0"

rules:
  - name: allow-read-tool
    salience: 100
    when:
      - template: tool_call
        conditions:
          - slot: tool
            expression: "equals(read_file)"
    then:
      action: allow
      reason: "read_file is on the allowlist"

  - name: deny-quarantined-agent
    salience: 10
    when:
      - template: agent
        alias: $a
        conditions:
          - slot: id
            bind: "?aid"
      - template: quarantine
        conditions:
          - slot: agent_id
            expression: "equals($a.id)"
    then:
      action: deny
      reason: "agent {aid} is quarantined"
"""


@pytest.fixture(scope="module")
def pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("repeat_stability")
    for subdir, body in (("templates", _TEMPLATES), ("modules", _MODULES), ("rules", _RULES)):
        (root / subdir).mkdir()
        (root / subdir / f"{subdir}.yaml").write_text(body, encoding="utf-8")
    return root


def _request(turn: int) -> dict[str, Any]:
    """The per-call fact a real caller sends: a new tool call each turn."""
    return {"agent_id": AGENT_ID, "tool": "read_file", "call_id": f"c{turn}"}


def _seeded(pack: Path) -> Engine:
    """An engine holding the long-lived facts the deny rule joins."""
    engine = Engine.from_rules(str(pack), default_decision="allow")
    engine.assert_fact("agent", {"id": AGENT_ID})
    engine.assert_fact("quarantine", {"agent_id": AGENT_ID})
    return engine


# ---------------------------------------------------------------------------
# One driver per public entry point. Each returns TURNS decisions.
# ---------------------------------------------------------------------------


def _drive_sdk_evaluate(pack: Path) -> list[str | None]:
    """`Engine.evaluate` — the cumulative path the tutorials teach."""
    engine = _seeded(pack)
    decisions = []
    for turn in range(TURNS):
        engine.assert_fact("tool_call", _request(turn))
        decisions.append(engine.evaluate().decision)
    return decisions


def _drive_sdk_evaluate_once(pack: Path) -> list[str | None]:
    """`Engine.evaluate_once` — the request-scoped path REST and gRPC use."""
    engine = _seeded(pack)
    return [
        engine.evaluate_once([("tool_call", _request(turn))]).decision for turn in range(TURNS)
    ]


def _drive_rest(pack: Path) -> list[str | None]:
    """`POST /v1/evaluate` against a server that mounts its Engine."""
    from fastapi.testclient import TestClient

    from fathom.integrations.rest import build_app

    app = build_app(require_signature=False)
    app.state.engine = _seeded(pack)
    app.state.attestation = None

    decisions: list[str | None] = []
    with TestClient(app) as client:
        for turn in range(TURNS):
            response = client.post(
                "/v1/evaluate",
                headers={"Authorization": "Bearer testtok"},
                json={
                    "ruleset": "mounted",
                    "facts": [{"template": "tool_call", "data": _request(turn)}],
                },
            )
            assert response.status_code == 200, response.text
            decisions.append(response.json()["decision"])
    return decisions


def _drive_grpc(pack: Path) -> list[str | None]:
    """`FathomServicer.Evaluate` against a servicer holding a default Engine."""
    from types import SimpleNamespace

    from fathom.integrations.grpc_server import FathomServicer

    servicer = FathomServicer(default_engine=_seeded(pack))
    context = _FakeContext()

    decisions: list[str | None] = []
    for turn in range(TURNS):
        response = servicer.Evaluate(
            SimpleNamespace(
                session_id="",
                ruleset="",
                facts=[
                    SimpleNamespace(template="tool_call", data_json=json.dumps(_request(turn)))
                ],
            ),
            context,
        )
        decisions.append(response.decision if response.HasField("decision") else None)
    return decisions


def _drive_mcp(pack: Path) -> list[str | None]:
    """The `fathom.evaluate` MCP tool, driven through the methods it wraps."""
    from fathom.integrations.mcp_server import FathomMCPServer

    server = FathomMCPServer(rules_path=str(pack))
    server.assert_fact("agent", {"id": AGENT_ID})
    server.assert_fact("quarantine", {"agent_id": AGENT_ID})

    decisions: list[str | None] = []
    for turn in range(TURNS):
        server.assert_fact("tool_call", _request(turn))
        decisions.append(server.evaluate()["decision"])
    return decisions


def _drive_repl(pack: Path, capsys: pytest.CaptureFixture[str]) -> list[str | None]:
    """`fathom repl` — the shipped tool for poking a policy by hand."""
    import builtins

    from fathom.cli import _repl_loop

    engine = _seeded(pack)
    script = []
    for turn in range(TURNS):
        script.append("assert tool_call " + json.dumps(_request(turn)))
        script.append("evaluate")
    script.append("quit")

    lines = iter(script)
    original = builtins.input
    builtins.input = lambda *_: next(lines)  # type: ignore[assignment]
    try:
        _repl_loop(engine)
    finally:
        builtins.input = original

    out = capsys.readouterr().out
    decisions = [
        line.split(":", 1)[1].strip()
        for line in out.splitlines()
        if line.strip().startswith("decision:")
    ]
    assert len(decisions) == TURNS, f"expected {TURNS} decisions, parsed {decisions} from:\n{out}"
    return decisions


class _FakeContext:
    """Minimal gRPC ServicerContext double: auth passes, abort raises."""

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return (("authorization", "Bearer testtok"),)

    def abort(self, code: object, detail: str) -> None:
        raise AssertionError(f"Evaluate aborted: {code} {detail}")


#: Every public way to ask this engine for a decision.
#: The key is the surface it names; `test_no_entry_point_is_missing_from_the
#: _contract` checks this list against what the code actually exposes.
ENTRY_POINTS: dict[str, Callable[..., list[str | None]]] = {
    "Engine.evaluate": _drive_sdk_evaluate,
    "Engine.evaluate_once": _drive_sdk_evaluate_once,
    "POST /v1/evaluate": _drive_rest,
    "grpc FathomServicer.Evaluate": _drive_grpc,
    "mcp fathom.evaluate": _drive_mcp,
    "cli repl evaluate": _drive_repl,
}


@pytest.fixture(autouse=True)
def _server_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """What the REST and gRPC servers refuse to start without."""
    from fathom.integrations.rest import session_store

    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
    session_store.clear()
    yield
    session_store.clear()


@pytest.mark.parametrize("entry_point", list(ENTRY_POINTS), ids=list(ENTRY_POINTS))
def test_a_standing_deny_keeps_denying(
    entry_point: str,
    pack: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Same policy, same standing facts, a new request each turn."""
    driver = ENTRY_POINTS[entry_point]
    decisions = (
        driver(pack, capsys) if driver is _drive_repl else driver(pack)  # type: ignore[call-arg]
    )

    assert decisions == ["deny"] * TURNS, (
        f"{entry_point} stopped applying a standing deny: {decisions}. "
        "The quarantine fact is unchanged and present on every turn."
    )


def test_no_entry_point_is_missing_from_the_contract() -> None:
    """A transport added later must not ship without this contract.

    Reflects over what each surface actually registers rather than a list
    written by hand, which is the sample-of-one failure this file exists to
    end.
    """
    from fathom.integrations.grpc_server import FathomServicer
    from fathom.integrations.mcp_server import FathomMCPServer
    from fathom.integrations.rest import app as rest_app

    exposed = {
        f"{method} {route.path}"
        for route in rest_app.routes
        for method in getattr(route, "methods", ())
        if "evaluate" in route.path
    }
    exposed |= {
        f"grpc FathomServicer.{name}"
        for name in dir(FathomServicer)
        if name[:1].isupper() and "Evaluate" in name
    }
    exposed |= {
        f"mcp {name}"
        for name in _mcp_tool_names(FathomMCPServer())
        if name.rsplit(".", 1)[-1].startswith("evaluate")
    }
    exposed |= {
        f"Engine.{name}"
        for name in dir(Engine)
        if name.startswith("evaluate") and callable(getattr(Engine, name))
    }

    missing = exposed - set(ENTRY_POINTS)
    assert not missing, (
        f"these evaluation entry points are not held to the repeat-stability "
        f"contract: {sorted(missing)}. Add a driver to ENTRY_POINTS."
    )


def _mcp_tool_names(server: FathomMCPServer) -> list[str]:
    """Tool names the MCP app registered, read off the registry."""
    import asyncio

    return [tool.name for tool in asyncio.run(server._mcp.list_tools())]


# ---------------------------------------------------------------------------
# The other way an earlier call changes a later one: what the RULES asserted.
# ---------------------------------------------------------------------------

_GRANT_TEMPLATES = """
templates:
  - name: tool_call
    slots:
      - name: agent_id
        type: string
        required: true
      - name: tool
        type: symbol
        required: true
  - name: grant
    slots:
      - name: agent_id
        type: string
        required: true
"""

_GRANT_RULES = """
module: policy
ruleset: derived-grant
version: "1.0"

rules:
  - name: derive-grant-on-elevate
    salience: 100
    when:
      - template: tool_call
        conditions:
          - slot: tool
            expression: "equals(elevate)"
          - slot: agent_id
            bind: "?aid"
    then:
      action: allow
      reason: "elevation granted"
      assert:
        - template: grant
          slots:
            agent_id: "?aid"

  - name: allow-read-with-grant
    salience: 50
    when:
      - template: tool_call
        alias: $c
        conditions:
          - slot: tool
            expression: "equals(read_file)"
      - template: grant
        conditions:
          - slot: agent_id
            expression: "equals($c.agent_id)"
    then:
      action: allow
      reason: "granted agent may read"
"""


@pytest.fixture(scope="module")
def grant_pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("derived_grant")
    for subdir, body in (
        ("templates", _GRANT_TEMPLATES),
        ("modules", _MODULES),
        ("rules", _GRANT_RULES),
    ):
        (root / subdir).mkdir()
        (root / subdir / f"{subdir}.yaml").write_text(body, encoding="utf-8")
    return root


def test_a_request_scoped_call_does_not_inherit_an_earlier_calls_grant(
    grant_pack: Path,
) -> None:
    """`evaluate_once` promises the same facts give the same decision.

    It withdrew the facts the *caller* supplied and left every fact the rules
    derived, so one elevation request permanently re-decided every later read
    on that engine -- and a REST/gRPC server is one engine serving everybody.
    """
    engine = Engine.from_rules(str(grant_pack), default_decision="deny")
    read = [("tool_call", {"agent_id": AGENT_ID, "tool": "read_file"})]

    before = engine.evaluate_once(read).decision
    engine.evaluate_once([("tool_call", {"agent_id": AGENT_ID, "tool": "elevate"})])
    after = engine.evaluate_once(read).decision

    assert (before, after) == ("deny", "deny")
