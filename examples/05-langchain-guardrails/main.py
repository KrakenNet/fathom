"""Example 05 — LangChain Tool-Call Guardrails.

Wires Fathom into a LangChain agent as a callback handler so that every
tool call is gated by deterministic rules.  The handler asserts a
``tool_request`` fact, evaluates the engine, and raises
:class:`PolicyViolation` on ``deny`` or ``escalate``.

This example does NOT call any LLM — it simulates the LangChain callback
contract directly so it runs offline. The integration code path
(``FathomCallbackHandler.on_tool_start``) is the same one a real agent
would hit when invoking a tool, so this is a faithful demonstration.

Demonstrates:
- ``FathomCallbackHandler`` lifecycle and ``PolicyViolation`` semantics
- Per-agent trust tiers passed in as facts before each tool call
- ``allow`` / ``deny`` / ``escalate`` decisions in the same policy graph
- Cross-fact references between ``tool_request`` and ``agent`` facts

Run:
    uv run python examples/05-langchain-guardrails/main.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fathom import Engine
from fathom.integrations.langchain import (
    FathomCallbackHandler,
    PolicyViolation,
)

HERE = Path(__file__).parent


def make_engine() -> Engine:
    """Build the policy engine with the guardrails ruleset."""
    engine = Engine()
    engine.load_templates(str(HERE / "templates"))
    engine.load_modules(str(HERE / "modules"))
    engine.load_rules(str(HERE / "rules"))
    return engine


def assert_agent(engine: Engine, agent_id: str, trust_tier: str) -> None:
    """Register the agent's trust tier as a fact."""
    engine.assert_fact("agent", {"id": agent_id, "trust_tier": trust_tier})


def simulate_tool_call(
    handler: FathomCallbackHandler,
    tool_name: str,
    arguments: dict[str, Any] | str,
) -> str:
    """Mimic LangChain's on_tool_start callback contract.

    A real LangChain Agent invokes ``handler.on_tool_start(serialized,
    input_str)`` before running each tool; here we call the same method
    directly. Fathom raises :class:`PolicyViolation` when the rule
    decision is ``deny`` or ``escalate``.
    """
    serialized = {"name": tool_name}
    input_str = json.dumps(arguments) if not isinstance(arguments, str) else arguments
    try:
        handler.on_tool_start(serialized, input_str)
    except PolicyViolation as exc:
        return f"BLOCKED ({exc.decision}): {exc.reason}"
    return "ALLOWED"


def run_agent(agent_id: str, trust_tier: str, calls: list[tuple[str, Any]]) -> None:
    print(f"\n--- Agent {agent_id!r} (trust={trust_tier}) ---")

    # Build a fresh engine per agent and seed the agent fact.  In a real
    # deployment you'd retain the Engine across calls and re-assert the
    # tool_request each turn — Fathom's working memory is reusable.
    engine = make_engine()
    assert_agent(engine, agent_id, trust_tier)
    handler = FathomCallbackHandler(engine, agent_id=agent_id)

    for tool, args in calls:
        outcome = simulate_tool_call(handler, tool, args)
        print(f"  {tool:<18} args={args!s:<40} -> {outcome}")
        # Each evaluate() leaves the tool_request fact in working memory;
        # retract it so the next call starts clean.
        engine.retract("tool_request")


def main() -> None:
    print("Fathom — Example 05: LangChain Tool-Call Guardrails")

    common_calls: list[tuple[str, Any]] = [
        ("web_search", {"q": "site:wikipedia.org NIST 800-53"}),
        ("calculator", "2 + 2"),
        ("send_email", {"to": "ops@example.com", "body": "..."}),
        ("write_file", {"path": "/tmp/report.txt", "data": "..."}),
        ("delete_record", {"table": "users", "id": 7}),
        ("shell_exec", "rm -rf /"),
    ]

    run_agent("agent-untrusted", "untrusted", common_calls)
    run_agent("agent-basic", "basic", common_calls)
    run_agent("agent-elevated", "elevated", common_calls)
    run_agent("agent-admin", "admin", common_calls)

    print("\nNotes:")
    print("  - PolicyViolation is raised for both 'deny' and 'escalate'. The")
    print("    agent runtime decides whether to fail the chain or hand off to")
    print("    a human approval queue based on exc.decision.")
    print("  - All decisions also flow into the audit log when an AuditSink")
    print("    is configured on the Engine.")


if __name__ == "__main__":
    main()
