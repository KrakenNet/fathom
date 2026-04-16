"""Real-LLM demo for Example 05 — opt-in.

Drives an actual LangChain agent through the ``FathomCallbackHandler``
against a live LLM. The agent has access to four tools; the policy
engine intercepts each tool call before it executes.

This script is **opt-in** because it requires extra dependencies and a
paid API key. The rest of the example (``main.py``, ``verify.py``) runs
fully offline against the same integration code path.

Required dependencies (not installed by default)::

    uv pip install langchain langchain-anthropic

Required environment variable::

    export ANTHROPIC_API_KEY=sk-ant-...

(Or use ``langchain-openai`` + ``OPENAI_API_KEY`` — switch the import
and the model factory at the top of ``build_agent()``.)

Run::

    uv run python examples/05-langchain-guardrails/agent_demo.py

What you should see
-------------------
The agent attempts a multi-step task that requires both an allowed tool
(``web_search``) and a forbidden one (``shell_exec``). When the agent
decides to call ``shell_exec``, ``FathomCallbackHandler.on_tool_start``
raises :class:`PolicyViolation` *before* the tool body runs, and the
agent loop terminates with the policy reason in the traceback.

For ``basic`` trust tier you'll also see ``send_email`` get escalated
(``PolicyViolation`` with ``decision == "escalate"``) — a real
deployment would catch this and route to a human approval queue
instead of failing the chain.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fathom import Engine
from fathom.integrations.langchain import (
    FathomCallbackHandler,
    PolicyViolation,
)

HERE = Path(__file__).parent


def _require_deps() -> None:
    missing: list[str] = []
    try:
        import langchain  # noqa: F401
    except ImportError:
        missing.append("langchain")
    try:
        import langchain_anthropic  # noqa: F401
    except ImportError:
        missing.append("langchain-anthropic")
    if missing:
        print("ERROR: missing optional dependencies:", ", ".join(missing))
        print()
        print("Install them with:")
        print("    uv pip install " + " ".join(missing))
        print()
        print("Then set ANTHROPIC_API_KEY in your environment.")
        sys.exit(2)
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        print("Get a key at https://console.anthropic.com/ and export it:")
        print("    export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(2)


def build_engine(agent_id: str, trust_tier: str) -> Engine:
    engine = Engine()
    engine.load_templates(str(HERE / "templates"))
    engine.load_modules(str(HERE / "modules"))
    engine.load_rules(str(HERE / "rules"))
    engine.assert_fact("agent", {"id": agent_id, "trust_tier": trust_tier})
    return engine


def build_agent(handler: FathomCallbackHandler):
    """Construct a real LangChain agent with four tools wired in."""
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_anthropic import ChatAnthropic
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.tools import tool

    @tool
    def web_search(query: str) -> str:
        """Search the public web for a query and return a summary."""
        return f"[stub] Top result for {query!r}: lorem ipsum dolor sit amet."

    @tool
    def calculator(expression: str) -> str:
        """Evaluate a basic arithmetic expression."""
        # Demo only — never eval untrusted input in production.
        try:
            return str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"

    @tool
    def send_email(to: str, body: str) -> str:
        """Send an email. Side-effecting; non-admins should be escalated."""
        return f"[stub] Sent email to {to}: {body[:40]}..."

    @tool
    def shell_exec(command: str) -> str:
        """Run a shell command. Hard-blocked by the policy."""
        return f"[stub] Would have run: {command}"

    tools = [web_search, calculator, send_email, shell_exec]

    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are an autonomous research agent. Use your tools to "
                "answer the user. Do not refuse — if a tool errors, try "
                "another approach.",
            ),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )
    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        callbacks=[handler],
        verbose=True,
        max_iterations=4,
        handle_parsing_errors=True,
    )


def run_scenario(
    label: str,
    agent_id: str,
    trust_tier: str,
    user_input: str,
) -> None:
    print("\n=========================================================")
    print(f"  Scenario: {label}")
    print(f"  Agent:    {agent_id} (tier={trust_tier})")
    print(f"  Task:     {user_input}")
    print("=========================================================")

    engine = build_engine(agent_id, trust_tier)
    handler = FathomCallbackHandler(engine, agent_id=agent_id)
    executor = build_agent(handler)

    try:
        result = executor.invoke({"input": user_input})
        print(f"\n[completed] {result.get('output', '')[:200]}")
    except PolicyViolation as exc:
        print(f"\n[GUARDRAIL FIRED] decision={exc.decision}")
        print(f"  reason: {exc.reason}")
        print(f"  trace:  {' -> '.join(exc.rule_trace)}")
        if exc.decision == "escalate":
            print("  (in production: route to human approval queue)")
        else:
            print("  (in production: fail closed and log to SIEM)")


def main() -> int:
    _require_deps()

    # 1. Admin agent doing safe research — should succeed end-to-end.
    run_scenario(
        label="admin doing safe web research",
        agent_id="agent-admin-1",
        trust_tier="admin",
        user_input="What is 17 * 23? Use the calculator tool.",
    )

    # 2. Basic agent that the LLM will likely try to send email for —
    #    Fathom escalates instead of allowing.
    run_scenario(
        label="basic agent attempting side-effect",
        agent_id="agent-basic-1",
        trust_tier="basic",
        user_input=(
            "Send an email to ops@example.com with the body 'system check'. "
            "Use the send_email tool."
        ),
    )

    # 3. Any agent attempting shell exec — hard-blocked at salience 200.
    run_scenario(
        label="admin attempting shell exec (still blocked)",
        agent_id="agent-admin-2",
        trust_tier="admin",
        user_input=(
            "List files in the current directory by running 'ls -la' with "
            "the shell_exec tool."
        ),
    )

    print("\nDone. Three scenarios exercised the real LangChain agent loop")
    print("through FathomCallbackHandler.on_tool_start — the same code")
    print("path verify.py asserts against, but driven by a real LLM.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
