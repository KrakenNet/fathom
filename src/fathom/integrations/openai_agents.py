"""OpenAI Agents SDK adapter for Fathom policy enforcement.

Provides :func:`fathom_tool_guardrail`, which builds a
:class:`~agents.tool_guardrails.ToolInputGuardrail` that evaluates tool calls
against loaded Fathom rules and halts the run unless the decision is
``allow``.

Attach it to the tools it should guard::

    from agents import function_tool

    guardrail = fathom_tool_guardrail(engine, "agent-1")

    @function_tool(tool_input_guardrails=[guardrail])
    def wipe_prod(target: str) -> str: ...

Requires ``openai-agents >= 0.4`` — the release that introduced
``agents.tool_guardrails``. Install via::

    pip install fathom-rules[openai-agents]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

# Re-exported: `from fathom.integrations.<adapter> import PolicyViolation`
# was the only import path before this class was shared.
from fathom.integrations import PolicyViolation as PolicyViolation

try:
    # `agents.tool_guardrails` landed in openai-agents 0.4.0. Importing it here
    # — rather than bare `agents` — makes an older install fail loudly at
    # import instead of silently never guarding a tool, which would fail open.
    from agents.tool_guardrails import (
        ToolGuardrailFunctionOutput,
        ToolInputGuardrail,
    )
except ImportError as _exc:
    raise ImportError(
        "openai-agents >= 0.4 is required for the OpenAI Agents SDK "
        "integration (agents.tool_guardrails was added in 0.4.0). "
        "Install it with: pip install fathom-rules[openai-agents]"
    ) from _exc

if TYPE_CHECKING:
    from agents.tool_guardrails import ToolInputGuardrailData

    from fathom.engine import Engine


def _build_tool_request_facts(
    tool_name: str,
    arguments: str | None,
    agent_id: str,
) -> dict[str, str]:
    """Build a ``tool_request`` fact dict from OpenAI Agents SDK tool call info.

    Extracts the tool name, parses *arguments* as JSON (falling back to
    plain text), and returns a dict suitable for :meth:`Engine.assert_fact`.

    Args:
        tool_name: Name of the tool being called.
        arguments: Tool input arguments as a string.
        agent_id: Identifier for the calling agent.

    Returns:
        Fact dict with ``tool_name``, ``arguments``, and ``agent_id``.
    """
    resolved_name = tool_name if tool_name else "unknown"

    # Parse arguments -- input may be JSON or plain text (or None)
    parsed: object
    try:
        parsed = json.loads(arguments) if arguments else arguments
    except (json.JSONDecodeError, TypeError):
        parsed = arguments

    return {
        "tool_name": str(resolved_name),
        "arguments": str(parsed),
        "agent_id": agent_id,
    }


def _evaluate_tool_call(
    engine: Engine,
    agent_id: str,
    tool_name: str,
    arguments: str | None,
) -> None:
    """Shared fact-mapping and evaluation logic for the guardrail.

    Uses :func:`_build_tool_request_facts` to construct the fact dict,
    asserts it into the engine, runs evaluation, retracts the fact, and
    raises :class:`PolicyViolation` unless the decision is ``allow``.

    Args:
        engine: Configured Fathom engine.
        agent_id: Identifier for the calling agent.
        tool_name: Name of the tool being called.
        arguments: Tool input arguments as a string.
    """
    facts = _build_tool_request_facts(tool_name, arguments, agent_id)

    # Assert tool_request fact into working memory
    # Request-scoped: assert, run, retract — all under one engine lock, with
    # CLIPS refraction reset afterwards.
    #
    # The hand-rolled assert/evaluate/retract this replaces had three holes.
    # (1) Retraction alone does not clear refraction, so a rule that matched
    # only long-lived facts (an `agent` fact, say) fired on call 1 and stayed
    # refracted for calls 2..N — a deny rule silently stopped denying, which
    # is a fail-open. (2) Taking the lock three separate times let a second
    # thread retract the (de-duplicated) fact before the first thread
    # evaluated, permitting hard-denied tools under concurrency. (3) The
    # retract-by-value matched a caller-owned identical fact and deleted it.
    # `evaluate_once` closes all three.
    result = engine.evaluate_once([("tool_request", facts)])

    # Fail closed: only an explicit allow permits the call
    if result.decision != "allow":
        raise PolicyViolation(
            decision=result.decision,
            reason=result.reason,
            rule_trace=result.rule_trace,
        )


def fathom_tool_guardrail(
    engine: Engine,
    agent_id: str,
) -> ToolInputGuardrail[Any]:
    """Factory that returns a tool input guardrail for the OpenAI Agents SDK.

    The guardrail reads the tool name and raw arguments off the
    ``ToolInputGuardrailData`` the SDK hands it, evaluates them against the
    Fathom policy engine, and returns a ``raise_exception`` outcome — which
    the runner turns into ``ToolInputGuardrailTripwireTriggered`` — unless
    the decision is ``allow``. The triggering :class:`PolicyViolation` is
    carried on the outcome's ``output_info``.

    Blocking is a *return value*, not an exception: the SDK inspects
    ``ToolGuardrailFunctionOutput.behavior`` to decide what to do.

    Args:
        engine: A configured :class:`~fathom.engine.Engine` instance with
            rules and templates loaded.
        agent_id: Identifier for the agent making tool calls.

    Returns:
        A :class:`~agents.tool_guardrails.ToolInputGuardrail` ready to pass
        to ``function_tool(tool_input_guardrails=[...])``.
    """

    async def _guardrail(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
        """Evaluate a tool call against Fathom policy rules.

        The underlying CLIPS engine is synchronous, so this delegates
        to the shared helper directly.

        Args:
            data: The SDK's guardrail payload, carrying the tool context.
        """
        context = data.context
        try:
            _evaluate_tool_call(
                engine,
                agent_id,
                context.tool_name,
                context.tool_arguments,
            )
        except PolicyViolation as exc:
            return ToolGuardrailFunctionOutput.raise_exception(output_info=exc)
        return ToolGuardrailFunctionOutput.allow()

    return ToolInputGuardrail(guardrail_function=_guardrail, name="fathom_tool_guardrail")
