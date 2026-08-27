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
import logging
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

_LOGGER = logging.getLogger(__name__)

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


def _calling_agent_id(context: ToolCallHookContext, fallback: str) -> str:
    """Identify the agent that made *this* call, not the one at registration.

    CrewAI's hook registry is process-global and every registered hook runs on
    every tool call, so a hook holding one identity labels the whole crew with
    it -- and registering one hook per member is not a workaround, because any
    hook returning ``False`` blocks the call, so each member's *allowed* calls
    get blocked by everybody else's hook. The identity has to come off the
    context CrewAI hands in.

    ``role`` first: it is the human-authored name a policy author writes into
    ``tool_request.agent_id``. ``id`` is a UUID, useful only as a last resort.
    *fallback* is used when CrewAI supplies no agent, which its own
    ``ToolCallHookContext`` documents as possible.
    """
    agent = getattr(context, "agent", None)
    if agent is None:
        return fallback
    return str(getattr(agent, "role", "") or getattr(agent, "id", "") or fallback)


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
    the tool anyway. A hook that raises fails open. That applies to every
    exception, not only :class:`PolicyViolation` — a pack whose tool-call
    template is spelled differently raises ``ValidationError`` and never
    produces a decision at all, which CrewAI logged and then ran the tool
    over. No decision is not an allow, so anything raised on the way to one
    blocks.

    Args:
        engine: A configured :class:`~fathom.engine.Engine` instance with
            rules and templates loaded.
        agent_id: Fallback identity, used only when CrewAI supplies no agent
            on the hook context. The agent that actually made the call is
            read from ``context.agent`` — see :func:`_calling_agent_id`.

    Returns:
        A callable matching CrewAI's
        :class:`~crewai.hooks.types.BeforeToolCallHook` protocol.
    """

    def _hook(context: ToolCallHookContext) -> bool | None:
        tool_input = context.tool_input
        arguments = tool_input if isinstance(tool_input, str) else json.dumps(tool_input)
        try:
            _evaluate_tool_call(
                engine,
                _calling_agent_id(context, agent_id),
                context.tool_name,
                arguments,
            )
        except PolicyViolation:
            return False
        except Exception:
            # Fail closed. Every other failure -- ValidationError, ScopeError,
            # EvaluationLimitError, a CLIPS fault -- means no decision was
            # reached, and CrewAI runs the tool for anything this hook lets
            # escape. Logged rather than swallowed silently: a policy that
            # cannot be evaluated is an operational problem, not a deny.
            _LOGGER.exception(
                "fathom: blocking %s — the policy engine could not reach a decision",
                context.tool_name,
            )
            return False
        return None

    return _hook
