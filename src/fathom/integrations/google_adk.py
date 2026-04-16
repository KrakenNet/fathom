"""Google ADK before-tool callback for Fathom policy enforcement.

Provides :func:`fathom_before_tool_callback` which returns a callback
that intercepts Google ADK tool calls, evaluates them against loaded
Fathom rules, and returns an error dict when a tool call is denied or
escalated.

Requires ``google-adk >= 1.0``.  Install via::

    pip install fathom-rules[google-adk]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

try:
    from google.adk import agents  # noqa: F401
except ImportError as _exc:
    raise ImportError(
        "google-adk is required for the Google ADK integration. "
        "Install it with: pip install fathom-rules[google-adk]"
    ) from _exc

if TYPE_CHECKING:
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
    arguments: dict[str, Any] | str,
    agent_id: str,
) -> dict[str, str]:
    """Build a ``tool_request`` fact dict from Google ADK callback args.

    Extracts the tool name, serialises *arguments* if needed, and
    returns a dict suitable for :meth:`Engine.assert_fact`.

    Args:
        tool_name: Name of the tool being invoked.
        arguments: Tool arguments as a dict or JSON string.
        agent_id: Identifier for the calling agent.

    Returns:
        Fact dict with ``tool_name``, ``arguments``, and ``agent_id``.
    """
    # Normalise arguments to a string representation
    if isinstance(arguments, dict):
        args_str = str(arguments)
    else:
        try:
            parsed = json.loads(arguments)
            args_str = str(parsed)
        except (json.JSONDecodeError, TypeError):
            args_str = str(arguments)

    return {
        "tool_name": str(tool_name),
        "arguments": args_str,
        "agent_id": agent_id,
    }


def _evaluate_tool_call(
    engine: Engine,
    agent_id: str,
    tool_name: str,
    arguments: dict[str, Any] | str,
) -> None:
    """Shared fact-mapping and evaluation logic for the ADK callback.

    Uses :func:`_build_tool_request_facts` to construct the fact dict,
    asserts it into the engine, runs evaluation, and raises
    :class:`PolicyViolation` on ``deny`` or ``escalate``.

    Args:
        engine: Configured Fathom engine.
        agent_id: Identifier for the calling agent.
        tool_name: Name of the tool being invoked.
        arguments: Tool arguments as a dict or JSON string.
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


def fathom_before_tool_callback(
    engine: Engine,
    agent_id: str,
) -> Any:
    """Factory that returns a Google ADK ``before_tool_callback``.

    The returned callable has the signature
    ``(tool, args, tool_context) -> Optional[dict]`` expected by
    Google ADK.  It returns ``None`` when the tool call is allowed
    (letting ADK proceed), or a dict ``{"error": "Policy violation: …"}``
    when the decision is ``deny`` or ``escalate``.

    Args:
        engine: A configured :class:`~fathom.engine.Engine` instance with
            rules and templates loaded.
        agent_id: Identifier for the agent making tool calls.

    Returns:
        A callback function compatible with Google ADK's
        ``before_tool_callback`` parameter.
    """

    def _callback(
        tool: Any,
        args: dict[str, Any],
        tool_context: Any,
    ) -> dict[str, str] | None:
        tool_name = getattr(tool, "name", "unknown")
        try:
            _evaluate_tool_call(engine, agent_id, tool_name, args)
        except PolicyViolation as exc:
            return {"error": f"Policy violation: {exc.reason}"}
        return None

    return _callback
