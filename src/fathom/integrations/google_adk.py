"""Google ADK before-tool callback for Fathom policy enforcement.

Provides :func:`fathom_before_tool_callback` which returns a callback
that intercepts Google ADK tool calls, evaluates them against loaded
Fathom rules, and returns an error dict unless the decision is
``allow``.

Requires ``google-adk >= 1.0``.  Install via::

    pip install fathom-rules[google-adk]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

# Re-exported: `from fathom.integrations.<adapter> import PolicyViolation`
# was the only import path before this class was shared.
from fathom.integrations import PolicyViolation as PolicyViolation

try:
    from google.adk import agents  # noqa: F401
except ImportError as _exc:
    raise ImportError(
        "google-adk is required for the Google ADK integration. "
        "Install it with: pip install fathom-rules[google-adk]"
    ) from _exc

if TYPE_CHECKING:
    from fathom.engine import Engine


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
    asserts it into the engine, runs evaluation, retracts the fact, and
    raises :class:`PolicyViolation` unless the decision is ``allow``.

    Args:
        engine: Configured Fathom engine.
        agent_id: Identifier for the calling agent.
        tool_name: Name of the tool being invoked.
        arguments: Tool arguments as a dict or JSON string.
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


def fathom_before_tool_callback(
    engine: Engine,
    agent_id: str,
) -> Any:
    """Factory that returns a Google ADK ``before_tool_callback``.

    The returned callable has the signature
    ``(tool, args, tool_context) -> Optional[dict]`` expected by
    Google ADK.  It returns ``None`` when the tool call is allowed
    (letting ADK proceed), or a dict ``{"error": "Policy violation: …"}``
    for every other decision.

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
