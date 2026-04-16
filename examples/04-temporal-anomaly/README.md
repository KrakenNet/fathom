# Example 04 — Temporal Anomaly Detection

**Complexity:** Advanced
**Concepts:** working memory, TTL, temporal operators, sliding windows,
multi-evaluation sessions, escalate decision

This is the kind of stateful reasoning that **stateless** policy engines
(OPA, Cedar) cannot do. Fathom keeps working memory between evaluations
within a session, so rules can match across many facts and across time.

## Detections

| Rule                          | Operator        | Pattern |
|-------------------------------|-----------------|---------|
| `brute-force-login`           | `rate_exceeds`  | >4 failed logins in 30s |
| `account-shared-across-ips`   | `distinct_count`| Same user, >2 distinct IPs |
| `session-velocity-burst`      | `rate_exceeds`  | >9 exports in 10s |

The `login_attempt` template uses `ttl: 60` — calling
`engine._fact_manager.cleanup_expired()` drops any login older than 60
seconds. In production this runs on a timer; here we keep facts for the
demo's lifetime.

## Decisions

In addition to `allow`/`deny`, this example uses the third Fathom
decision channel — `escalate` — for the multi-IP scenario, signalling that
the request needs human (or step-up) review rather than a hard deny.

## Run it

```bash
uv run python examples/04-temporal-anomaly/main.py
```

Watch the rules NOT fire on the first few facts, then snap into action
once the threshold is crossed:

```
Scenario A — Brute-force detection (5 failed logins in <30s):
  [after failure #1] deny     rules=[<none>]
  [after failure #2] deny     rules=[<none>]
  [after failure #3] deny     rules=[<none>]
  [after failure #4] deny     rules=[<none>]
  [after failure #5] deny     rules=[anomaly::brute-force-login]
```

## Layout

```
04-temporal-anomaly/
  templates/auth.yaml      login_attempt (ttl=60), session
  modules/anomaly.yaml     'anomaly' module
  rules/anomaly.yaml       3 detection rules
  main.py                  4 scenarios
```
