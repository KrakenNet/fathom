"""CrewAI hook for Fathom policy enforcement.

Provides :func:`fathom_before_tool_call`, which returns a hook matching
CrewAI's ``before_tool_call`` protocol: it takes a single
:class:`~crewai.hooks.tool_hooks.ToolCallHookContext` and returns ``False``
to block the call.

Register the returned hook with CrewAI's global registry::

    from crewai.hooks import register_before_tool_call_hook

    register_before_tool_call_hook(fathom_before_tool_call(engine, "agent-1"))

Requires ``crewai >= 1.5`` — the release that introduced ``crewai.hooks``.
Install via::

    pip install fathom-rules[crewai]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

# Re-exported: `from fathom.integrations.<adapter> import PolicyViolation`
# was the only import path before this class was shared.
from fathom.integrations import PolicyViolation as PolicyViolation

try:
    # `crewai.hooks` landed in crewai 1.5.0. Importing it here — rather than
    # bare `crewai` — makes an older install fail loudly at import instead of
    # silently never invoking the hook, which would fail open.
    from crewai.hooks import register_before_tool_call_hook as _register  # noqa: F401
except ImportError as _exc:
    raise ImportError(
        "crewai >= 1.5 is required for the CrewAI integration "
        "(crewai.hooks was added in 1.5.0). "
        "Install it with: pip install fathom-rules[crewai]"
    ) from _exc

if TYPE_CHECKING:
    from collections.abc import Callable

    from crewai.hooks.tool_hooks import ToolCallHookContext

    from fathom.engine import Engine


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


def fathom_before_tool_call(
    engine: Engine,
    agent_id: str,
) -> Callable[[ToolCallHookContext], bool | None]:
    """Factory that returns a CrewAI ``before_tool_call`` hook.

    The returned hook receives a single ``ToolCallHookContext``, asserts a
    ``tool_request`` fact into the Fathom engine, evaluates rules, and
    returns ``False`` — CrewAI's block signal — unless the decision is
    ``allow``.

    Blocking is a *return value*, not an exception: CrewAI wraps the whole
    before-hook loop in ``try/except`` and logs anything raised, then runs
    the tool anyway. A hook that raises fails open.

    Args:
        engine: A configured :class:`~fathom.engine.Engine` instance with
            rules and templates loaded.
        agent_id: Identifier for the agent making tool calls.

    Returns:
        A callable matching CrewAI's
        :class:`~crewai.hooks.types.BeforeToolCallHook` protocol.
    """

    def _hook(context: ToolCallHookContext) -> bool | None:
        tool_input = context.tool_input
        arguments = tool_input if isinstance(tool_input, str) else json.dumps(tool_input)
        try:
            _evaluate_tool_call(engine, agent_id, context.tool_name, arguments)
        except PolicyViolation:
            return False
        return None

    return _hook
