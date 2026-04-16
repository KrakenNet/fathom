"""Verification harness for Example 05.

Asserts that every (trust_tier, tool_name) combination produces the
expected decision through the real ``FathomCallbackHandler.on_tool_start``
code path — the same method LangChain calls before each tool invocation.

This does NOT call an LLM. It proves the integration glue is wired up
correctly so that when a real agent is plugged in (see ``agent_demo.py``)
the policy decisions will fire as designed.

Run:
    uv run python examples/05-langchain-guardrails/verify.py
Exits 0 on success, 1 on any mismatch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fathom import Engine
from fathom.integrations.langchain import (
    FathomCallbackHandler,
    PolicyViolation,
)

HERE = Path(__file__).parent

# (trust_tier, tool_name) -> expected decision, where:
#   "allow"    => no PolicyViolation raised
#   "deny"     => PolicyViolation with decision == "deny"
#   "escalate" => PolicyViolation with decision == "escalate"
EXPECTED: dict[tuple[str, str], str] = {
    # untrusted -> nothing allowed
    ("untrusted", "web_search"): "deny",
    ("untrusted", "calculator"): "deny",
    ("untrusted", "send_email"): "deny",
    ("untrusted", "write_file"): "deny",
    ("untrusted", "delete_record"): "deny",
    ("untrusted", "shell_exec"): "deny",
    # basic
    ("basic", "web_search"): "allow",
    ("basic", "calculator"): "allow",
    ("basic", "send_email"): "escalate",
    ("basic", "write_file"): "escalate",
    ("basic", "delete_record"): "deny",
    ("basic", "shell_exec"): "deny",
    # elevated
    ("elevated", "web_search"): "allow",
    ("elevated", "calculator"): "allow",
    ("elevated", "send_email"): "escalate",
    ("elevated", "write_file"): "escalate",
    ("elevated", "delete_record"): "deny",
    ("elevated", "shell_exec"): "deny",
    # admin
    ("admin", "web_search"): "allow",
    ("admin", "calculator"): "allow",
    ("admin", "send_email"): "allow",
    ("admin", "write_file"): "allow",
    ("admin", "delete_record"): "deny",
    ("admin", "shell_exec"): "deny",
}


def make_handler(agent_id: str, trust_tier: str) -> tuple[Engine, FathomCallbackHandler]:
    engine = Engine()
    engine.load_templates(str(HERE / "templates"))
    engine.load_modules(str(HERE / "modules"))
    engine.load_rules(str(HERE / "rules"))
    engine.assert_fact("agent", {"id": agent_id, "trust_tier": trust_tier})
    return engine, FathomCallbackHandler(engine, agent_id=agent_id)


def actual_decision(handler: FathomCallbackHandler, tool_name: str) -> str:
    """Invoke the real LangChain callback method and observe the outcome."""
    serialized = {"name": tool_name}
    input_str = json.dumps({"q": "demo"})
    try:
        handler.on_tool_start(serialized, input_str)
    except PolicyViolation as exc:
        return exc.decision  # "deny" or "escalate"
    return "allow"


def main() -> int:
    failures: list[str] = []
    passed = 0

    for (tier, tool), expected in EXPECTED.items():
        engine, handler = make_handler(f"agent-{tier}", tier)
        try:
            actual = actual_decision(handler, tool)
        finally:
            engine.retract("tool_request")

        status = "OK " if actual == expected else "FAIL"
        line = f"  [{status}] tier={tier:<10} tool={tool:<14} expected={expected:<8} got={actual}"
        print(line)
        if actual == expected:
            passed += 1
        else:
            failures.append(line)

    total = len(EXPECTED)
    print(f"\nResult: {passed}/{total} passed")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f)
        return 1
    print("\nIntegration glue verified. on_tool_start raises PolicyViolation")
    print("for every deny/escalate combination — the same path LangChain hits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
