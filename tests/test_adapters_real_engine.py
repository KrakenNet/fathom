"""Real-engine regression tests for the four framework adapters.

These tests drive the shipped adapters against a real :class:`Engine`
loaded from an on-disk rule pack rather than a ``MagicMock``, which is why
they catch the two adapter bugs the mock-based suites missed:

* the ``tool_request`` fact was never retracted, so call *N+1* was decided
  on call *N*'s working memory (issue #137);
* the guard blocked on a denylist of two decisions, so ``route`` and
  ``scope`` — and a missing decision — permitted the tool call.

Every driver below dispatches through the framework's own tool-execution
path and asserts on the *tool body's side effect*, never by calling the
adapter's handler directly. Calling the handler directly is what let three
adapters ship with signatures no framework ever calls: the engine was real,
the rules were real, the decision was right, and the tool ran anyway. A
correct decision that the framework discards is a fail-open, and only a real
dispatch can see it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from agents import Agent as OpenAIAgent
from agents.tool_context import ToolContext
from agents.tool_guardrails import ToolInputGuardrailData
from crewai.agents.parser import AgentAction
from crewai.hooks import (
    clear_before_tool_call_hooks,
    register_before_tool_call_hook,
)
from crewai.tools.structured_tool import CrewStructuredTool
from crewai.utilities.i18n import I18N
from crewai.utilities.tool_utils import execute_tool_and_check_finality
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.flows.llm_flows.functions import handle_function_call_list_async
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.sessions.session import Session
from google.adk.tools.function_tool import FunctionTool
from google.genai import types
from langchain_core.tools import StructuredTool

from fathom.engine import Engine
from fathom.integrations import crewai as crewai_adapter
from fathom.integrations import google_adk as adk_adapter
from fathom.integrations import langchain as langchain_adapter
from fathom.integrations import openai_agents as openai_adapter

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

AGENT_ID = "agent-007"

TEMPLATES_YAML = """
templates:
  - name: tool_request
    slots:
      - name: agent_id
        type: string
        required: true
      - name: tool_name
        type: symbol
        required: true
      - name: arguments
        type: string
        default: ""
  - name: agent
    slots:
      - name: id
        type: string
        required: true
      - name: trust_tier
        type: symbol
        allowed_values: [basic, admin]
        required: true
"""

MODULES_YAML = """
modules:
  - name: guard
    description: "Adapter regression guardrails"
focus_order:
  - guard
"""

RULES_YAML = """
module: guard
ruleset: adapter-regression
version: "1.0"

rules:
  - name: block-shell
    salience: 5
    when:
      - template: tool_request
        conditions:
          - slot: tool_name
            expression: "equals(shell_exec)"
    then:
      action: deny
      reason: "Shell execution tools are blocked"

  - name: route-exec
    salience: 5
    when:
      - template: tool_request
        conditions:
          - slot: tool_name
            expression: "equals(exec)"
    then:
      action: route
      reason: "route dangerous tool to sandbox"

  - name: escalate-email
    salience: 20
    when:
      - template: tool_request
        alias: $req
        conditions:
          - slot: agent_id
            expression: "matches(.+)"
          - slot: tool_name
            expression: "equals(send_email)"
      - template: agent
        conditions:
          - slot: id
            expression: "equals($req.agent_id)"
          - slot: trust_tier
            expression: "equals(basic)"
    then:
      action: escalate
      reason: "send_email requires human approval for non-admin agents"

  - name: allow-readonly
    salience: 100
    when:
      - template: tool_request
        alias: $req
        conditions:
          - slot: agent_id
            expression: "matches(.+)"
          - slot: tool_name
            expression: "equals(web_search)"
      - template: agent
        conditions:
          - slot: id
            expression: "equals($req.agent_id)"
          - slot: trust_tier
            expression: "in([basic, admin])"
    then:
      action: allow
      reason: "Read-only tools permitted"

  - name: allow-admin-email
    salience: 100
    when:
      - template: tool_request
        alias: $req
        conditions:
          - slot: agent_id
            expression: "matches(.+)"
          - slot: tool_name
            expression: "equals(send_email)"
      - template: agent
        conditions:
          - slot: id
            expression: "equals($req.agent_id)"
          - slot: trust_tier
            expression: "equals(admin)"
    then:
      action: allow
      reason: "Admin tier may send email"
"""


# ---------------------------------------------------------------------------
# Fixtures and adapter drivers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rule_pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Write the guardrail rule pack to disk once per module."""
    root = tmp_path_factory.mktemp("adapter_rules")
    for subdir, content in (
        ("templates", TEMPLATES_YAML),
        ("modules", MODULES_YAML),
        ("rules", RULES_YAML),
    ):
        (root / subdir).mkdir()
        (root / subdir / f"{subdir}.yaml").write_text(content)
    return root


class _RecordingEngine:
    """Engine proxy that remembers the last decision, for block messages.

    CrewAI's block signal is a bare ``False`` and its rejection string
    carries no rule reason, so the reason the assertions check has to be
    read back off the engine. The framework still decides whether the tool
    body runs — that is what the drivers assert on.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.last: Any = None

    def evaluate_once(self, facts: list[tuple[str, dict[str, Any]]]) -> Any:
        self.last = self._inner.evaluate_once(facts)
        return self.last

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _langchain_call(engine: Engine, tool_name: str) -> None:
    """Invoke a real LangChain tool with the handler attached."""
    ran: list[str] = []
    tool = StructuredTool.from_function(
        func=lambda: ran.append(tool_name) or "ok",
        name=tool_name,
        description="regression tool",
    )
    handler = langchain_adapter.FathomCallbackHandler(engine=engine, agent_id=AGENT_ID)

    try:
        tool.invoke({}, config={"callbacks": [handler]})
    except langchain_adapter.PolicyViolation:
        assert ran == [], f"LangChain ran {tool_name} despite a policy violation"
        raise
    assert ran == [tool_name], f"LangChain skipped {tool_name} on an allow decision"


def _langchain_async_call(engine: Engine, tool_name: str) -> None:
    """Invoke a real async LangChain tool with the async handler attached."""
    ran: list[str] = []

    async def _body() -> str:
        ran.append(tool_name)
        return "ok"

    tool = StructuredTool.from_function(
        func=lambda: ran.append(tool_name) or "ok",
        coroutine=_body,
        name=tool_name,
        description="regression tool",
    )
    handler = langchain_adapter.FathomAsyncCallbackHandler(engine=engine, agent_id=AGENT_ID)

    try:
        asyncio.run(tool.ainvoke({}, config={"callbacks": [handler]}))
    except langchain_adapter.PolicyViolation:
        assert ran == [], f"LangChain ran {tool_name} despite a policy violation"
        raise
    assert ran == [tool_name], f"LangChain skipped {tool_name} on an allow decision"


def _crewai_call(engine: Engine, tool_name: str) -> None:
    """Run a real CrewAI tool call through the registered before-hook."""
    ran: list[str] = []
    recorder = _RecordingEngine(engine)
    tool = CrewStructuredTool.from_function(
        func=lambda: ran.append(tool_name) or "ok",
        name=tool_name,
        description="regression tool",
    )

    clear_before_tool_call_hooks()
    register_before_tool_call_hook(crewai_adapter.fathom_before_tool_call(recorder, AGENT_ID))
    try:
        execute_tool_and_check_finality(
            agent_action=AgentAction(
                thought="", tool=tool_name, tool_input="{}", text=f"{tool_name}{{}}"
            ),
            tools=[tool],
            i18n=I18N(),
        )
    finally:
        clear_before_tool_call_hooks()

    if not ran:
        result = recorder.last
        raise crewai_adapter.PolicyViolation(
            decision=result.decision,
            reason=result.reason,
            rule_trace=result.rule_trace,
        )


def _openai_call(engine: Engine, tool_name: str) -> None:
    """Run the guardrail exactly as the Agents SDK runner runs it."""
    guardrail = openai_adapter.fathom_tool_guardrail(engine, AGENT_ID)
    outcome = asyncio.run(
        guardrail.run(
            ToolInputGuardrailData(
                context=ToolContext(
                    context=None,
                    tool_name=tool_name,
                    tool_call_id="call-1",
                    tool_arguments="{}",
                ),
                agent=OpenAIAgent(name="regression-agent"),
            )
        )
    )

    # The runner reads `behavior`; anything other than "allow" stops the call.
    if outcome.behavior["type"] != "allow":
        raise outcome.output_info


def _adk_call(engine: Engine, tool_name: str) -> None:
    """Run a real ADK function call through the agent's before-tool callback.

    ADK reports a violation by returning ``{"error": ...}`` rather than
    raising, so the shared assertions below get a raise-shaped driver.
    """
    ran: list[str] = []

    def _body() -> str:
        """Regression tool."""
        ran.append(tool_name)
        return "ok"

    _body.__name__ = tool_name
    agent = LlmAgent(
        name="regression_agent",
        before_tool_callback=adk_adapter.fathom_before_tool_callback(engine, AGENT_ID),
    )
    context = InvocationContext(
        session_service=InMemorySessionService(),
        invocation_id="invocation-1",
        session=Session(id="session-1", app_name="regression", user_id="user-1"),
        agent=agent,
    )

    event = asyncio.run(
        handle_function_call_list_async(
            context,
            [types.FunctionCall(name=tool_name, args={}, id="call-1")],
            {tool_name: FunctionTool(_body)},
        )
    )
    response = event.content.parts[0].function_response.response

    if "error" in response:
        assert ran == [], f"ADK ran {tool_name} despite a policy violation"
        raise adk_adapter.PolicyViolation(
            decision="blocked",
            reason=response["error"],
            rule_trace=[],
        )
    assert ran == [tool_name], f"ADK skipped {tool_name} on an allow decision"


ADAPTERS: list[tuple[str, Callable[[Engine, str], None], type[Exception]]] = [
    ("langchain", _langchain_call, langchain_adapter.PolicyViolation),
    ("langchain-async", _langchain_async_call, langchain_adapter.PolicyViolation),
    ("crewai", _crewai_call, crewai_adapter.PolicyViolation),
    ("openai-agents", _openai_call, openai_adapter.PolicyViolation),
    ("google-adk", _adk_call, adk_adapter.PolicyViolation),
]

_ADAPTER_PARAMS = [pytest.param(call, exc, id=name) for name, call, exc in ADAPTERS]


# ---------------------------------------------------------------------------
# 1. Stale tool_request fact (issue #137)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("call", "violation"), _ADAPTER_PARAMS)
def test_repeat_identical_call_is_blocked_again(
    rule_pack: Path,
    call: Callable[[Engine, str], None],
    violation: type[Exception],
) -> None:
    """Two identical consecutive denied calls must both be blocked.

    Before the fix the first call left its ``tool_request`` fact in working
    memory; CLIPS then refused the duplicate assert and refracted the
    already-fired rule, so the second call fell through to the engine
    default and the blocked tool was permitted on retry.
    """
    engine = Engine.from_rules(str(rule_pack), default_decision="allow")

    for _ in range(2):
        with pytest.raises(violation) as exc_info:
            call(engine, "shell_exec")
        assert "Shell execution tools are blocked" in str(exc_info.value.args[0])

    assert engine.query("tool_request") == []


@pytest.mark.parametrize(("call", "violation"), _ADAPTER_PARAMS)
def test_read_only_call_not_judged_on_previous_call(
    rule_pack: Path,
    call: Callable[[Engine, str], None],
    violation: type[Exception],
) -> None:
    """A read-only call must not inherit the previous call's tool_request.

    Before the fix the stale ``send_email`` fact re-activated the escalate
    rule when the agent's trust tier changed, so the unrelated read-only
    ``web_search`` call was escalated.
    """
    engine = Engine.from_rules(str(rule_pack))
    engine.assert_fact("agent", {"id": AGENT_ID, "trust_tier": "admin"})

    call(engine, "send_email")

    engine.retract("agent")
    engine.assert_fact("agent", {"id": AGENT_ID, "trust_tier": "basic"})

    call(engine, "web_search")

    assert engine.query("tool_request") == []


@pytest.mark.parametrize(("call", "violation"), _ADAPTER_PARAMS)
def test_working_memory_not_leaked_on_violation(
    rule_pack: Path,
    call: Callable[[Engine, str], None],
    violation: type[Exception],
) -> None:
    """The tool_request fact is retracted even when the call is blocked."""
    engine = Engine.from_rules(str(rule_pack))

    with pytest.raises(violation):
        call(engine, "shell_exec")

    assert engine.query("tool_request") == []


# ---------------------------------------------------------------------------
# 2. Allowlist: only "allow" permits the call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("call", "violation"), _ADAPTER_PARAMS)
def test_route_decision_does_not_permit_call(
    rule_pack: Path,
    call: Callable[[Engine, str], None],
    violation: type[Exception],
) -> None:
    """A rule with ``action: route`` must not let the tool call through."""
    engine = Engine.from_rules(str(rule_pack))

    with pytest.raises(violation) as exc_info:
        call(engine, "exec")
    assert "route dangerous tool to sandbox" in str(exc_info.value.args[0])


@pytest.mark.parametrize(("call", "violation"), _ADAPTER_PARAMS)
def test_absent_decision_does_not_permit_call(
    rule_pack: Path,
    call: Callable[[Engine, str], None],
    violation: type[Exception],
) -> None:
    """``decision is None`` (no rule fired, no default) must fail closed."""
    engine = Engine.from_rules(str(rule_pack), default_decision=None)

    with pytest.raises(violation):
        call(engine, "unmodelled_tool")


@pytest.mark.parametrize(("call", "violation"), _ADAPTER_PARAMS)
def test_allow_decision_permits_call(
    rule_pack: Path,
    call: Callable[[Engine, str], None],
    violation: type[Exception],
) -> None:
    """An explicit ``allow`` still permits the call and leaves no fact."""
    engine = Engine.from_rules(str(rule_pack))
    engine.assert_fact("agent", {"id": AGENT_ID, "trust_tier": "basic"})

    call(engine, "web_search")

    assert engine.query("tool_request") == []


class _UnrecognisedDecisionEngine:
    """Minimal engine stand-in returning a decision no adapter knows.

    A rule cannot express an unrecognised action (the compiler validates
    :class:`~fathom.models.ActionType`), so a stand-in is the only way to
    cover a future or typo'd decision string reaching the guard.
    """

    def __init__(self, decision: str) -> None:
        self._decision = decision
        self.scoped: list[list[tuple[str, dict[str, Any]]]] = []

    def evaluate_once(self, facts: list[tuple[str, dict[str, Any]]]) -> SimpleNamespace:
        self.scoped.append(facts)
        return SimpleNamespace(decision=self._decision, reason="unknown action", rule_trace=[])


@pytest.mark.parametrize(("call", "violation"), _ADAPTER_PARAMS)
def test_unrecognised_decision_does_not_permit_call(
    call: Callable[[Engine, str], None],
    violation: type[Exception],
) -> None:
    """An unrecognised decision string must fail closed, not fall through."""
    engine = _UnrecognisedDecisionEngine("sandbox")

    with pytest.raises(violation):
        call(engine, "anything")  # type: ignore[arg-type]

    # The guard must go through the request-scoped boundary, which is what
    # withdraws the fact and resets refraction.
    assert engine.scoped == [
        [("tool_request", {"tool_name": "anything", "arguments": "{}", "agent_id": AGENT_ID})]
    ]


# ---------------------------------------------------------------------------
# 3. Google ADK reports violations as an error dict, not an exception
# ---------------------------------------------------------------------------


def test_adk_callback_returns_error_dict_for_route(rule_pack: Path) -> None:
    """The ADK callback blocks a ``route`` decision with its error dict."""
    engine = Engine.from_rules(str(rule_pack))
    callback = adk_adapter.fathom_before_tool_callback(engine, AGENT_ID)

    outcome = callback(SimpleNamespace(name="exec"), {}, None)

    assert outcome == {"error": "Policy violation: route dangerous tool to sandbox"}
    assert engine.query("tool_request") == []


# ---------------------------------------------------------------------------
# 4. fathom_guard LangGraph node
# ---------------------------------------------------------------------------


def test_fathom_guard_repeat_call_keeps_rule_decision(rule_pack: Path) -> None:
    """Repeated identical guard calls keep returning the rule's decision."""
    engine = Engine.from_rules(str(rule_pack), default_decision="allow")

    for _ in range(2):
        result = langchain_adapter.fathom_guard(
            {"tool_name": "shell_exec", "arguments": "{}"}, engine, AGENT_ID
        )
        assert result["fathom_decision"] == "deny"

    assert engine.query("tool_request") == []


def test_fathom_guard_reports_route_decision(rule_pack: Path) -> None:
    """A ``route`` decision is reported verbatim, not flattened to allow."""
    engine = Engine.from_rules(str(rule_pack))

    result = langchain_adapter.fathom_guard(
        {"tool_name": "exec", "arguments": "{}"}, engine, AGENT_ID
    )

    assert result["fathom_decision"] == "route"


def test_fathom_guard_absent_decision_fails_closed(rule_pack: Path) -> None:
    """No decision must be reported as ``deny``, never manufactured as allow."""
    engine = Engine.from_rules(str(rule_pack), default_decision=None)

    result = langchain_adapter.fathom_guard(
        {"tool_name": "unmodelled_tool", "arguments": "{}"}, engine, AGENT_ID
    )

    assert result == {"fathom_decision": "deny", "fathom_reason": ""}


# ---------------------------------------------------------------------------
# 5. Refraction fail-open: a deny rule keyed on long-lived facts
# ---------------------------------------------------------------------------
#
# Retracting the tool_request fact after each call is NOT sufficient. CLIPS
# refraction is per-activation: a rule that matched only long-lived working
# memory (an `agent` fact that never changes) fires once and stays refracted
# for every later call, while a higher-salience allow rule re-fires on the
# fresh tool_request. Under the shipped `default_decision="deny"` that turns
# a hard deny on call 1 into a permit on calls 2..N — a fail-open.
#
# This is not a hypothetical rule shape: the owasp_agentic, nist, hipaa and
# cmmc packs all ship deny rules whose LHS omits tool_request.

REFRACTION_RULES_YAML = """
module: guard
ruleset: adapter-refraction
version: "1.0"

rules:
  - name: allow-readonly
    salience: 100
    when:
      - template: tool_request
        conditions:
          - slot: tool_name
            expression: "equals(web_search)"
    then:
      action: allow
      reason: "Read-only tools permitted"

  - name: untrusted-agent-denied
    salience: 5
    when:
      - template: agent
        conditions:
          - slot: trust_tier
            expression: "equals(basic)"
    then:
      action: deny
      reason: "Untrusted agent is denied everything"
"""


@pytest.fixture(scope="module")
def refraction_pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("adapter_refraction")
    for subdir, content in (
        ("templates", TEMPLATES_YAML),
        ("modules", MODULES_YAML),
        ("rules", REFRACTION_RULES_YAML),
    ):
        (root / subdir).mkdir()
        (root / subdir / f"{subdir}.yaml").write_text(content)
    return root


@pytest.mark.parametrize(("call", "violation"), _ADAPTER_PARAMS)
def test_deny_rule_on_long_lived_facts_keeps_denying(
    refraction_pack: Path,
    call: Callable[[Engine, str], None],
    violation: type[Exception],
) -> None:
    """A deny rule that never re-matches must still block call 2 and call 3."""
    engine = Engine.from_rules(str(refraction_pack))
    engine.assert_fact("agent", {"id": AGENT_ID, "trust_tier": "basic"})

    for attempt in range(1, 4):
        with pytest.raises(violation):
            call(engine, "web_search")
            pytest.fail(f"call {attempt} was permitted — refraction fail-open")


@pytest.mark.parametrize(("call", "violation"), _ADAPTER_PARAMS)
def test_guard_does_not_delete_a_caller_owned_tool_request(
    rule_pack: Path,
    call: Callable[[Engine, str], None],
    violation: type[Exception],
) -> None:
    """CLIPS de-dups asserts; the guard must not withdraw the caller's own fact.

    A caller that holds its own identical ``tool_request`` fact used to have
    it silently deleted: the adapter's assert de-duplicated onto the existing
    fact, and the adapter's cleanup then retracted it.
    """
    engine = Engine.from_rules(str(rule_pack))
    engine.assert_fact("agent", {"id": AGENT_ID, "trust_tier": "basic"})
    caller_fact = {"agent_id": AGENT_ID, "tool_name": "shell_exec", "arguments": "{}"}
    engine.assert_fact("tool_request", caller_fact)
    assert engine.query("tool_request") == [caller_fact]

    with pytest.raises(violation):
        call(engine, "shell_exec")

    assert engine.query("tool_request") == [caller_fact], (
        "the adapter retracted a fact the caller owns"
    )


@pytest.mark.concurrency
def test_concurrent_identical_denied_calls_never_permit(rule_pack: Path) -> None:
    """Threads sharing one Engine must never slip a hard-denied tool through.

    The old adapter took the engine lock three separate times (assert,
    evaluate, retract). Because CLIPS de-duplicates identical facts, one
    thread's cleanup could retract the shared fact before another thread's
    evaluate ran, so that thread saw no ``tool_request`` at all and fell
    through to ``default_decision``. Measured 17 permits in 1600 calls.
    ``evaluate_once`` holds the lock across all three steps.
    """
    import threading

    engine = Engine.from_rules(str(rule_pack), default_decision="allow")
    engine.assert_fact("agent", {"id": AGENT_ID, "trust_tier": "basic"})
    handler = langchain_adapter.FathomCallbackHandler(engine=engine, agent_id=AGENT_ID)

    permitted: list[int] = []
    counter_lock = threading.Lock()

    def hammer() -> None:
        for _ in range(50):
            try:
                handler.on_tool_start({"name": "shell_exec"}, "{}")
            except langchain_adapter.PolicyViolation:
                continue
            with counter_lock:
                permitted.append(1)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert permitted == [], f"{len(permitted)} concurrent calls permitted a denied tool"
