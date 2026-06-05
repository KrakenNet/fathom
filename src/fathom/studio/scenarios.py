"""Seed loaders for the bundled Fathom examples (01–05).

Each :data:`SCENARIOS` entry turns one ``examples/0N-*`` directory into a
one-click seed button (AC-7.4 / AC-5.1). Seeding loads that example's
``templates/`` + ``modules/`` + ``functions/`` + ``rules/`` (via the REST
``/v1/evaluate`` endpoint's ``Engine.from_rules`` subdirectory convention),
pre-asserts a representative set of facts into a fresh session, runs the
evaluation, and returns the real decision payload (``decision``, ``reason``,
``rule_trace``, ``module_trace``, ``duration_us``) — never fabricated output.

The seed calls the production REST app **in-process** over an
:class:`httpx.ASGITransport` (the same mechanism the Playground ``/eval``
panel uses), so seeded working memory lives in the REST module's shared
``SessionStore`` and is consistent with the rest of the Studio.

The fact sets are chosen so each scenario fires a named rule rather than the
fail-closed default deny: 01 read-up deny, 02 RBAC confidential deny, 03 BLP
no-read-up, 04 brute-force temporal deny (five rapid failed logins), 05
LangChain shell-tool guardrail deny. Example 05 seeds **without** invoking any
LLM — the guardrail ruleset is evaluated against a canned ``tool_request``
(the live LangChain toggle is a separate panel concern).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from httpx import ASGITransport

from fathom.integrations.rest import app as rest_app

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


#: A single fact to assert before evaluation: ``(template, data)``.
Fact = tuple[str, dict[str, Any]]


@dataclass(frozen=True)
class Scenario:
    """Descriptor for one seedable example."""

    id: str
    title: str
    description: str
    #: Ruleset path relative to ``FATHOM_RULESET_ROOT`` (the example dir name).
    ruleset: str
    #: Builds the facts asserted before evaluation (called per seed).
    facts: Callable[[], list[Fact]] = field(repr=False)


def _now_logins(
    user: str,
    ip: str,
    outcome: str,
    count: int,
) -> list[Fact]:
    """Build *count* ``login_attempt`` facts spaced just under one second apart.

    Timestamps anchor to the current clock so example 04's ``rate_exceeds``
    window (30s) and ``distinct_count`` operators match at seed time.
    """
    base = time.time()
    return [
        (
            "login_attempt",
            {"user": user, "ip": ip, "outcome": outcome, "ts": base + i * 0.1},
        )
        for i in range(count)
    ]


#: The five seedable scenarios, one per ``examples/0N-*`` directory.
SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="01-hello-allow-deny",
        title="01 · Hello allow/deny",
        description=(
            "Clearance vs classification: a confidential agent requesting "
            "secret data is denied (fail-closed)."
        ),
        ruleset="01-hello-allow-deny",
        facts=lambda: [
            ("agent", {"id": "carol", "clearance": "confidential"}),
            (
                "data_request",
                {
                    "agent_id": "carol",
                    "classification": "secret",
                    "resource": "hr_records",
                },
            ),
        ],
    ),
    Scenario(
        id="02-rbac-modules",
        title="02 · RBAC with modules",
        description=(
            "Deny-first module ordering: a non-admin editor reading a "
            "confidential resource is stopped in deny_checks."
        ),
        ruleset="02-rbac-modules",
        facts=lambda: [
            ("user", {"id": "erin", "role": "editor"}),
            (
                "action",
                {
                    "user_id": "erin",
                    "verb": "read",
                    "resource": "salary_sheet",
                    "sensitivity": "confidential",
                },
            ),
        ],
    ),
    Scenario(
        id="03-classification-blp",
        title="03 · Bell-LaPadula",
        description=(
            "No read up: a confidential subject reading a secret object is "
            "denied by the BLP simple-security property (dominates())."
        ),
        ruleset="03-classification-blp",
        facts=lambda: [
            ("subject", {"id": "bob", "clearance": "confidential", "compartments": ""}),
            (
                "resource",
                {"id": "intel-01", "classification": "secret", "compartments": ""},
            ),
            (
                "access_request",
                {"subject_id": "bob", "object_id": "intel-01", "mode": "read"},
            ),
        ],
    ),
    Scenario(
        id="04-temporal-anomaly",
        title="04 · Temporal anomaly",
        description=(
            "Brute-force detection over working memory: five failed logins "
            "in under 30s trips rate_exceeds and is denied."
        ),
        ruleset="04-temporal-anomaly",
        facts=lambda: _now_logins("alice", "10.0.0.1", "failure", 5),
    ),
    Scenario(
        id="05-langchain-guardrails",
        title="05 · LangChain guardrails",
        description=(
            "Tool-call guardrail (no LLM): a shell_exec tool_request is "
            "hard-blocked for every trust tier."
        ),
        ruleset="05-langchain-guardrails",
        facts=lambda: [
            ("agent", {"id": "agent-admin", "trust_tier": "admin"}),
            (
                "tool_request",
                {
                    "agent_id": "agent-admin",
                    "tool_name": "shell_exec",
                    "arguments": "rm -rf /",
                },
            ),
        ],
    ),
)

#: Index for O(1) lookup by scenario id (used by the seed route).
_BY_ID: dict[str, Scenario] = {s.id: s for s in SCENARIOS}


def get_scenario(scenario_id: str) -> Scenario | None:
    """Return the scenario with *scenario_id*, or ``None`` if unknown."""
    return _BY_ID.get(scenario_id)


async def seed(
    scenario: Scenario,
    *,
    token: str,
    sid: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Seed *scenario* and return ``(decision_payload, error)``.

    Loads the scenario's ruleset into a fresh session, asserts its facts, and
    evaluates — all via ``POST /v1/evaluate`` on the mounted REST app
    in-process. *token* is the REST bearer token (``FATHOM_API_TOKEN``).
    When *sid* is omitted a unique session id is minted so each seed starts
    from clean working memory.

    Returns the raw ``EvaluateResponse`` payload on success, otherwise a
    human-readable error string.
    """
    session_id = sid or f"seed-{scenario.id}-{uuid.uuid4().hex}"
    facts: Sequence[Fact] = scenario.facts()
    body = {
        "facts": [{"template": tmpl, "data": data} for tmpl, data in facts],
        "ruleset": scenario.ruleset,
        "session_id": session_id,
    }
    transport = ASGITransport(app=rest_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://studio.internal"
    ) as client:
        try:
            response = await client.post(
                "/v1/evaluate",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Session-Id": session_id,
                },
            )
        except httpx.HTTPError as exc:  # pragma: no cover - defensive
            return None, f"Seed request failed: {exc}"

    if response.status_code != 200:
        return None, _error_detail(response)
    return response.json(), None


def _error_detail(response: httpx.Response) -> str:
    """Extract a human-readable error message from a non-200 seed response."""
    prefix = f"Seed failed ({response.status_code}): "
    try:
        payload = response.json()
    except ValueError:
        return prefix + (response.text or response.reason_phrase)
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error")
        if isinstance(detail, str):
            return prefix + detail
    return prefix + (response.text or response.reason_phrase)
