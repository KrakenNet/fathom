"""Every way a framework can dispatch a guarded tool, held to the same rule.

Structural check D from the audit post-mortem. The shipped regression suite
drives each adapter through the framework's own tool-execution path -- which is
what makes it worth anything -- but it drives each adapter through *one* path.
LangChain has six: two handler classes, a tool that is sync or async, and
``invoke`` or ``ainvoke``. The suite covered one of the six, and it was one of
the five that work.

The cell it missed: ``StructuredTool.ainvoke`` on a tool with no ``coroutine=``
-- every plain ``@tool``-decorated function -- falls back to
``run_in_executor(config, self.invoke, ...)``, which routes an async handler
through the *sync* callback manager. That manager collects the returned
coroutine and runs it in ``_run_coros``, which catches every exception, logs
``"Error in callback coroutine: %s"``, and never consults ``raise_error``. A
denied tool ran, and the only trace was a log line.

Two more cells nothing covered, and both were also broken:

- **the engine itself failing.** An adapter that catches only
  :class:`PolicyViolation` lets everything else -- a ``ValidationError`` from a
  pack whose template is named differently, a ``ScopeError``, an
  ``EvaluationLimitError`` -- escape. Under CrewAI, which logs whatever a hook
  raises and then runs the tool, that is a fail-open.
- **more than one agent.** CrewAI's hook registry is process-global and every
  registered hook runs on every call, so a hook holding an ``agent_id`` frozen
  at construction labels every crew member's calls with one identity.

Each driver returns the tool bodies that actually ran. That is the only
observable that matters: a correct decision the framework discards is a
fail-open.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from agents import Agent as OpenAIAgent
from agents.tool_context import ToolContext
from agents.tool_guardrails import ToolInputGuardrailData
from crewai.agents.parser import AgentAction
from crewai.hooks import clear_before_tool_call_hooks, register_before_tool_call_hook
from crewai.hooks.tool_hooks import ToolCallHookContext
from crewai.tools.structured_tool import CrewStructuredTool
from crewai.utilities.i18n import I18N
from crewai.utilities.tool_utils import execute_tool_and_check_finality
from langchain_core.tools import StructuredTool

from fathom.engine import Engine
from fathom.errors import ValidationError
from fathom.integrations import crewai as crewai_adapter
from fathom.integrations import google_adk as adk_adapter
from fathom.integrations import langchain as langchain_adapter
from fathom.integrations import openai_agents as openai_adapter

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

AGENT_ID = "agent-007"
DENIED = "shell_exec"
ALLOWED = "web_search"

_TEMPLATES = """
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
"""

_MODULES = """
modules:
  - name: guard
focus_order:
  - guard
"""

_RULES = """
module: guard
ruleset: adapter-dispatch
version: "1.0"

rules:
  - name: allow-web-search
    salience: 100
    when:
      - template: tool_request
        conditions:
          - slot: tool_name
            expression: "equals(web_search)"
    then:
      action: allow
      reason: "read-only tool"

  - name: deny-shell
    salience: 10
    when:
      - template: tool_request
        conditions:
          - slot: tool_name
            expression: "equals(shell_exec)"
    then:
      action: deny
      reason: "shell execution is blocked"
"""


@pytest.fixture(scope="module")
def pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("adapter_dispatch")
    for subdir, body in (("templates", _TEMPLATES), ("modules", _MODULES), ("rules", _RULES)):
        (root / subdir).mkdir()
        (root / subdir / f"{subdir}.yaml").write_text(body, encoding="utf-8")
    return root


@pytest.fixture
def engine(pack: Path) -> Engine:
    return Engine.from_rules(str(pack))


class _RaisingEngine:
    """An engine that cannot reach a decision, for every reason but a deny.

    A pack whose tool-call template is spelled differently is the realistic
    one: `Engine.evaluate_once` raises ``ValidationError`` on the first call
    and the adapter never sees a decision at all.
    """

    def evaluate_once(self, facts: list[tuple[str, dict[str, Any]]]) -> Any:
        raise ValidationError(f"Unknown template {facts[0][0]!r}")


# ---------------------------------------------------------------------------
# Drivers. Each returns the tool bodies that ran, block signal absorbed.
# ---------------------------------------------------------------------------


def _langchain(
    *, handler_is_async: bool, tool_is_async: bool, call_is_async: bool
) -> Callable[[Any, str], list[str]]:
    def _run(engine: Any, tool_name: str) -> list[str]:
        ran: list[str] = []

        async def _abody() -> str:
            ran.append(tool_name)
            return "ok"

        def _body() -> str:
            ran.append(tool_name)
            return "ok"

        tool = StructuredTool.from_function(
            func=None if tool_is_async else _body,
            coroutine=_abody if tool_is_async else None,
            name=tool_name,
            description="dispatch matrix tool",
        )
        cls = (
            langchain_adapter.FathomAsyncCallbackHandler
            if handler_is_async
            else langchain_adapter.FathomCallbackHandler
        )
        handler = cls(engine=engine, agent_id=AGENT_ID)
        config = {"callbacks": [handler]}

        try:
            if call_is_async:
                asyncio.run(tool.ainvoke({}, config=config))
            else:
                tool.invoke({}, config=config)
        except Exception:  # noqa: BLE001 - anything escaping means the tool did not run
            pass
        return ran

    return _run


def _crewai(engine: Any, tool_name: str, agent: Any = None) -> list[str]:
    """CrewAI's own execution path — the loop that swallows what a hook raises."""
    ran: list[str] = []
    tool = CrewStructuredTool.from_function(
        func=lambda: ran.append(tool_name) or "ok",
        name=tool_name,
        description="dispatch matrix tool",
    )

    clear_before_tool_call_hooks()
    register_before_tool_call_hook(crewai_adapter.fathom_before_tool_call(engine, AGENT_ID))
    try:
        execute_tool_and_check_finality(
            agent_action=AgentAction(
                thought="", tool=tool_name, tool_input="{}", text=f"{tool_name}{{}}"
            ),
            tools=[tool],
            i18n=I18N(),
            agent=agent,
        )
    finally:
        clear_before_tool_call_hooks()
    return ran


def _openai(engine: Any, tool_name: str) -> list[str]:
    ran: list[str] = []
    guardrail = openai_adapter.fathom_tool_guardrail(engine, AGENT_ID)

    async def _drive() -> Any:
        return await guardrail.run(
            ToolInputGuardrailData(
                context=ToolContext(
                    context=None,
                    tool_name=tool_name,
                    tool_call_id="call-1",
                    tool_arguments="{}",
                ),
                agent=OpenAIAgent(name="dispatch-agent"),
            )
        )

    try:
        outcome = asyncio.run(_drive())
    except Exception:  # noqa: BLE001 - the runner never reaches the tool
        return ran
    # The runner reads `behavior`; anything but "allow" stops the call.
    if outcome.behavior["type"] == "allow":
        ran.append(tool_name)
    return ran


def _adk(engine: Any, tool_name: str) -> list[str]:
    ran: list[str] = []
    callback = adk_adapter.fathom_before_tool_callback(engine, AGENT_ID)
    tool = type("_Tool", (), {"name": tool_name})()

    try:
        outcome = callback(tool, {}, None)
    except Exception:  # noqa: BLE001 - ADK never reaches the tool
        return ran
    # ADK runs the tool when the callback returns None.
    if outcome is None:
        ran.append(tool_name)
    return ran


#: Every dispatch path a framework can take into a guarded tool.
DISPATCH: dict[str, Callable[[Any, str], list[str]]] = {
    "langchain sync-handler sync-tool invoke": _langchain(
        handler_is_async=False, tool_is_async=False, call_is_async=False
    ),
    "langchain sync-handler sync-tool ainvoke": _langchain(
        handler_is_async=False, tool_is_async=False, call_is_async=True
    ),
    "langchain sync-handler async-tool ainvoke": _langchain(
        handler_is_async=False, tool_is_async=True, call_is_async=True
    ),
    "langchain async-handler sync-tool invoke": _langchain(
        handler_is_async=True, tool_is_async=False, call_is_async=False
    ),
    "langchain async-handler sync-tool ainvoke": _langchain(
        handler_is_async=True, tool_is_async=False, call_is_async=True
    ),
    "langchain async-handler async-tool ainvoke": _langchain(
        handler_is_async=True, tool_is_async=True, call_is_async=True
    ),
    "crewai before_tool_call": _crewai,
    "openai-agents tool guardrail": _openai,
    "google-adk before_tool_callback": _adk,
}


@pytest.mark.parametrize("dispatch", list(DISPATCH), ids=list(DISPATCH))
def test_a_denied_tool_body_never_runs(dispatch: str, engine: Engine) -> None:
    ran = DISPATCH[dispatch](engine, DENIED)

    assert ran == [], f"{dispatch} ran a denied tool: {ran}"


@pytest.mark.parametrize("dispatch", list(DISPATCH), ids=list(DISPATCH))
def test_an_allowed_tool_body_still_runs(dispatch: str, engine: Engine) -> None:
    """The other half: a matrix that blocks everything proves nothing."""
    ran = DISPATCH[dispatch](engine, ALLOWED)

    assert ran == [ALLOWED], f"{dispatch} blocked an allowed tool: {ran}"


@pytest.mark.parametrize("dispatch", list(DISPATCH), ids=list(DISPATCH))
def test_an_engine_that_cannot_decide_blocks_the_call(dispatch: str) -> None:
    """No decision is not an allow. Catching only PolicyViolation lets it be one."""
    ran = DISPATCH[dispatch](_RaisingEngine(), ALLOWED)

    assert ran == [], f"{dispatch} ran a tool the engine never decided on: {ran}"


def test_the_fact_carries_the_agent_that_made_the_call(engine: Engine) -> None:
    """CrewAI's hook registry is global: one hook serves the whole crew.

    Every registered hook runs on every call and any ``False`` blocks, so one
    hook per crew member is not a workaround — it makes each member's allowed
    calls blocked by everyone else's hook. The identity has to come off the
    context CrewAI hands the hook.
    """
    seen: list[str] = []

    class _Recorder:
        def evaluate_once(self, facts: list[tuple[str, dict[str, Any]]]) -> Any:
            seen.append(facts[0][1]["agent_id"])
            return engine.evaluate_once(facts)

        def __getattr__(self, name: str) -> Any:
            return getattr(engine, name)

    hook = crewai_adapter.fathom_before_tool_call(_Recorder(), "factory-default")
    tool = CrewStructuredTool.from_function(
        func=lambda: "ok", name=ALLOWED, description="dispatch matrix tool"
    )
    for role in ("ops-001", "intern-002"):
        hook(
            ToolCallHookContext(
                tool_name=ALLOWED,
                tool_input={},
                tool=tool,
                agent=_FakeAgent(role),
            )
        )

    assert seen == ["ops-001", "intern-002"], (
        f"the hook labelled both calls {seen} — a policy keyed on agent_id "
        "cannot tell one crew member from another"
    )


def test_the_factory_identity_is_used_when_the_framework_supplies_none() -> None:
    """`agent=None` is a documented case on `ToolCallHookContext`."""
    seen: list[str] = []

    class _Recorder:
        def evaluate_once(self, facts: list[tuple[str, dict[str, Any]]]) -> Any:
            seen.append(facts[0][1]["agent_id"])
            raise ValidationError("stop here — the fact is what is under test")

    hook = crewai_adapter.fathom_before_tool_call(_Recorder(), "factory-default")
    tool = CrewStructuredTool.from_function(
        func=lambda: "ok", name=ALLOWED, description="dispatch matrix tool"
    )
    hook(ToolCallHookContext(tool_name=ALLOWED, tool_input={}, tool=tool, agent=None))

    assert seen == ["factory-default"]


class _FakeAgent:
    """The two attributes an identity can be read from, as CrewAI defines them."""

    def __init__(self, role: str) -> None:
        self.role = role
        self.id = f"uuid-of-{role}"
