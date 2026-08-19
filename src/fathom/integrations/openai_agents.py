"""OpenAI Agents SDK adapter for Fathom policy enforcement.

Provides :func:`fathom_tool_guardrail` which creates an async tool input
guardrail that evaluates tool calls against loaded Fathom rules and raises
:class:`PolicyViolation` unless the decision is ``allow``.

Requires ``openai-agents >= 0.1``.  Install via::

    pip install fathom-rules[openai-agents]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

try:
    import agents  # noqa: F401
except ImportError as _exc:
    raise ImportError(
        "openai-agents is required for the OpenAI Agents SDK integration. "
        "Install it with: pip install fathom-rules[openai-agents]"
    ) from _exc

if TYPE_CHECKING:
    from fathom.engine import Engine


class PolicyViolation(Exception):  # noqa: N818 -- name per design spec
    """Raised when Fathom does not explicitly allow a tool call.

    Attributes:
        decision: The evaluation decision — any value other than ``"allow"``
            (e.g. ``"deny"``, ``"escalate"``, ``"route"``, ``"scope"``), or
            ``None`` when no rule fired and no default decision is configured.
        reason: Human-readable reason from the matching rule.
        rule_trace: Ordered list of rules that fired during evaluation.
    """

    def __init__(
        self,
        decision: str | None,
        reason: str | None,
        rule_trace: list[str],
    ) -> None:
        self.decision = decision
        self.reason = reason
        self.rule_trace = rule_trace
        super().__init__(f"Policy violation: {decision} — {reason}")


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
) -> Any:
    """Factory that returns an async tool input guardrail for OpenAI Agents SDK.

    The returned callable accepts ``tool_name`` and ``arguments`` parameters,
    evaluates them against the Fathom policy engine, and raises
    :class:`PolicyViolation` unless the decision is ``allow``.

    Args:
        engine: A configured :class:`~fathom.engine.Engine` instance with
            rules and templates loaded.
        agent_id: Identifier for the agent making tool calls.

    Returns:
        An async callable suitable for use as a tool input guardrail.
    """

    async def _guardrail(
        tool_name: str,
        arguments: str | None = None,
    ) -> None:
        """Evaluate a tool call against Fathom policy rules.

        The underlying CLIPS engine is synchronous, so this delegates
        to the shared helper directly.

        Args:
            tool_name: Name of the tool being called.
            arguments: Tool input arguments as a string.
        """
        _evaluate_tool_call(engine, agent_id, tool_name, arguments)

    return _guardrail
