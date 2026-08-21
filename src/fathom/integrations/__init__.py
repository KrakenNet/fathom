"""Framework adapters, and the exception every one of them raises."""

from __future__ import annotations

__all__ = ["PolicyViolation"]


class PolicyViolation(Exception):  # noqa: N818 — name per design spec
    """Raised when Fathom does not explicitly allow a tool call.

    Every shipped adapter is allowlist-only -- it permits the call when, and
    only when, the decision is exactly ``"allow"`` -- and every one raises
    this. It lives here rather than in each adapter so that a caller guarding
    two frameworks needs one ``except``, and so that importing it does not
    drag in any adapter's optional dependency. Each adapter re-exports it, so
    ``from fathom.integrations.langchain import PolicyViolation`` still works.

    It deliberately does not inherit :class:`fathom.errors.FathomError`: that
    hierarchy is for failures of the engine itself, and a policy that says no
    is the engine working.

    Attributes:
        decision: The evaluation decision — any value other than ``"allow"``
            (e.g. ``"deny"``, ``"escalate"``, ``"route"``, ``"scope"``), or
            ``None`` when no rule fired and no default decision is configured.
        reason: Human-readable reason from the matching rule.
        rule_trace: Ordered list of rules that fired during evaluation.
    """

    def __init__(
        self,
        decision: str | None,
        reason: str | None,
        rule_trace: list[str],
    ) -> None:
        self.decision = decision
        self.reason = reason
        self.rule_trace = rule_trace
        super().__init__(f"Policy violation: {decision} — {reason}")
