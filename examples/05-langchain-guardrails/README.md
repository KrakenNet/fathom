# Example 05 — LangChain Tool-Call Guardrails

**Complexity:** Expert
**Concepts:** LangChain integration, callback handler, `PolicyViolation`,
trust tiers, multi-action decisions (`allow` / `deny` / `escalate`)

A complete agent governance setup: every tool call from a LangChain agent
runs through `FathomCallbackHandler.on_tool_start`, which asserts a
`tool_request` fact, evaluates the rule graph, and **raises
`PolicyViolation`** when the decision is `deny` or `escalate`.

This example does not call an LLM — it directly invokes the LangChain
callback contract so it runs offline. The code path exercised
(`on_tool_start`) is the exact one a real agent hits when invoking a tool,
so it's a faithful demo of the integration.

## Tier matrix

|                | shell_exec | delete_record | send_email / write_file | web_search / calculator |
|----------------|:----------:|:-------------:|:------------------------:|:------------------------:|
| **untrusted**  | deny       | deny          | deny                     | deny                     |
| **basic**      | deny       | deny          | escalate                 | allow                    |
| **elevated**   | deny       | deny          | escalate                 | allow                    |
| **admin**      | deny       | deny          | allow                    | allow                    |

## What to notice

- **`PolicyViolation` carries the decision.** Catch it in your agent loop
  and treat `decision == "deny"` as a hard failure, `decision == "escalate"`
  as "send to human approval queue."
- **Hard blocks short-circuit by salience.** `no-shell-tools` runs at
  salience 200 — even an admin can't shell out.
- **Cross-fact references** join the `tool_request` to the calling agent's
  trust tier (`equals($req.agent_id)`).

## Three ways to run this example

The example ships with three entry points so you can verify the
integration at the level of rigor you need — from a 30-second offline
demo to a live LLM driving the real LangChain agent loop.

### 1. Offline demo (no extra deps, no API key)

```bash
uv run python examples/05-langchain-guardrails/main.py
```

Mocks the LLM-side trigger (`agent decides to call a tool`) but exercises
the **real** `FathomCallbackHandler.on_tool_start` method — the exact
hook LangChain itself invokes. Four agents x six tool calls, decisions
printed inline.

### 2. Offline assertion harness (CI-friendly)

```bash
uv run python examples/05-langchain-guardrails/verify.py
```

Same code path as `main.py`, but with a 24-row truth table:
`(trust_tier, tool_name) -> expected_decision` covering every cell of
the matrix above. Exits `0` on success, `1` on any mismatch — drop into
CI to lock the policy graph against regressions. The integration test
suite (`tests/test_langchain.py`) covers the handler with formal
pytest assertions as well.

### 3. Real LLM agent (opt-in, requires deps + API key)

```bash
uv pip install langchain langchain-anthropic
export ANTHROPIC_API_KEY=sk-ant-...
uv run python examples/05-langchain-guardrails/agent_demo.py
```

Builds a real `AgentExecutor` with four `@tool`-decorated functions,
attaches `FathomCallbackHandler` as a callback, and runs three
scenarios against a live model:

1. **admin doing safe research** -> succeeds end-to-end
2. **basic agent attempting `send_email`** -> `PolicyViolation(decision="escalate")`
3. **admin attempting `shell_exec`** -> `PolicyViolation(decision="deny")` (hard block bypasses tier)

The script gates itself on missing deps / missing API key with a clear
error message, so it's safe to commit and discover.

## Layout

```
05-langchain-guardrails/
  templates/tools.yaml        tool_request, agent
  modules/guardrails.yaml     'guardrails' module
  rules/guardrails.yaml       6 rules: hard blocks, tier escalations, allows
  main.py                     [offline]   4 agents x 6 tool calls, mocked LLM
  verify.py                   [offline]   24-row assertion harness for CI
  agent_demo.py               [real LLM]  opt-in: real AgentExecutor + Claude
```

## Real LangChain wiring

In a real LangChain agent, attach the handler at chain construction time:

```python
from fathom import Engine
from fathom.integrations.langchain import FathomCallbackHandler, PolicyViolation
from langchain.agents import AgentExecutor

engine = Engine.from_rules("examples/05-langchain-guardrails/")
engine.assert_fact("agent", {"id": "agent-001", "trust_tier": "basic"})

handler = FathomCallbackHandler(engine, agent_id="agent-001")
executor = AgentExecutor(agent=my_agent, tools=tools, callbacks=[handler])

try:
    executor.invoke({"input": "..."})
except PolicyViolation as exc:
    if exc.decision == "escalate":
        send_to_approval_queue(exc.reason, exc.rule_trace)
    else:
        log_denied(exc.reason)
```

The `fathom_guard` LangGraph node (also in `fathom.integrations.langchain`)
provides the same gating as a graph node for conditional routing instead
of exception-based control flow.
