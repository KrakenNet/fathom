"""CrewAI hook for Fathom policy enforcement.

Provides :func:`fathom_before_tool_call` which returns a callable that
intercepts CrewAI tool calls, evaluates them against loaded Fathom rules,
and raises :class:`PolicyViolation` when a tool call is denied or escalated.

Requires ``crewai >= 0.80``.  Install via::

    pip install fathom-rules[crewai]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

try:
    import crewai as _crewai  # noqa: F401
except ImportError as _exc:
    raise ImportError(
        "crewai is required for the CrewAI integration. "
        "Install it with: pip install fathom-rules[crewai]"
    ) from _exc

if TYPE_CHECKING:
    from collections.abc import Callable

    from fathom.engine import Engine


class PolicyViolation(Exception):  # noqa: N818 — name per design spec
    """Raised when Fathom denies or escalates a tool call.

    Attributes:
        decision: The evaluation decision (``"deny"`` or ``"escalate"``).
        reason: Human-readable reason from the matching rule.
        rule_trace: Ordered list of rules that fired during evaluation.
    """

    def __init__(
        self,
        decision: str,
        reason: str | None,
        rule_trace: list[str],
    ) -> None:
        self.decision = decision
        self.reason = reason
        self.rule_trace = rule_trace
        super().__init__(f"Policy violation: {decision} — {reason}")


def _build_tool_request_facts(
    tool_name: str,
    arguments: str,
    agent_id: str,
) -> dict[str, str]:
    """Build a ``tool_request`` fact dict from CrewAI tool call args.

    Extracts the tool name, parses *arguments* as JSON (falling back to
    plain text), and returns a dict suitable for
    :meth:`Engine.assert_fact`.

    Args:
        tool_name: Name of the tool being called.
        arguments: Tool input arguments as a string.
        agent_id: Identifier for the calling agent.

    Returns:
        Fact dict with ``tool_name``, ``arguments``, and ``agent_id``.
    """
    resolved_name = tool_name if tool_name else "unknown"

    # Parse arguments — may be JSON or plain text
    try:
        parsed = json.loads(arguments)
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
    arguments: str,
) -> None:
    """Shared fact-mapping and evaluation logic for the CrewAI hook.

    Uses :func:`_build_tool_request_facts` to construct the fact dict,
    asserts it into the engine, runs evaluation, and raises
    :class:`PolicyViolation` on ``deny`` or ``escalate``.

    Args:
        engine: Configured Fathom engine.
        agent_id: Identifier for the calling agent.
        tool_name: Name of the tool being called.
        arguments: Tool input arguments as a string.
    """
    facts = _build_tool_request_facts(tool_name, arguments, agent_id)

    # Assert tool_request fact into working memory
    engine.assert_fact("tool_request", facts)

    # Evaluate rules
    result = engine.evaluate()

    # Raise on deny or escalate
    if result.decision in ("deny", "escalate"):
        raise PolicyViolation(
            decision=result.decision,
            reason=result.reason,
            rule_trace=result.rule_trace,
        )


def fathom_before_tool_call(
    engine: Engine,
    agent_id: str,
) -> Callable[[str, str], None]:
    """Factory that returns a CrewAI ``before_tool_call`` hook.

    The returned callable receives the tool name and arguments string,
    asserts a ``tool_request`` fact into the Fathom engine, evaluates
    rules, and raises :class:`PolicyViolation` when the decision is
    ``deny`` or ``escalate``.

    Args:
        engine: A configured :class:`~fathom.engine.Engine` instance with
            rules and templates loaded.
        agent_id: Identifier for the agent making tool calls.

    Returns:
        A callable matching CrewAI's ``before_tool_call`` signature
        ``(tool_name: str, arguments: str) -> None``.
    """

    def _hook(tool_name: str, arguments: str) -> None:
        _evaluate_tool_call(engine, agent_id, tool_name, arguments)

    return _hook
