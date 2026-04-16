"""Example 02 — RBAC with Modules.

Role-based access control split across two modules:

- ``deny_checks`` — guardrails that fire first (higher focus priority)
- ``role_permits`` — role-based grants that run only if no deny fired

Demonstrates:
- Module-level focus order as a coarse execution phase
- Deny-first / fail-closed layering with salience inside each module
- Rule metadata for compliance traceability
- Rule trace and module trace on the evaluation result

Run:
    uv run python examples/02-rbac-modules/main.py
"""

from __future__ import annotations

from pathlib import Path

from fathom import Engine

HERE = Path(__file__).parent


def make_engine() -> Engine:
    engine = Engine()
    engine.load_templates(str(HERE / "templates"))
    engine.load_modules(str(HERE / "modules"))
    engine.load_rules(str(HERE / "rules"))
    return engine


def check(
    user_id: str,
    role: str,
    verb: str,
    resource: str,
    sensitivity: str = "internal",
) -> None:
    engine = make_engine()
    engine.assert_fact("user", {"id": user_id, "role": role})
    engine.assert_fact(
        "action",
        {
            "user_id": user_id,
            "verb": verb,
            "resource": resource,
            "sensitivity": sensitivity,
        },
    )
    result = engine.evaluate()
    trace = " -> ".join(result.rule_trace) if result.rule_trace else "<no rule fired>"
    print(
        f"  {role:<7} {verb:<9} {resource:<18} [{sensitivity:<12}] "
        f"=> {result.decision:<5} | rules: {trace}"
    )


def main() -> None:
    print("Fathom — Example 02: RBAC with Modules\n")
    print("scenarios (role, verb, resource, sensitivity):\n")

    check("alice", "admin", "configure", "feature_flags", "internal")
    check("bob", "editor", "write", "blog_post", "internal")
    check("bob", "editor", "configure", "feature_flags", "internal")
    check("carol", "viewer", "read", "reports", "internal")
    check("carol", "viewer", "delete", "reports", "internal")
    check("dave", "guest", "write", "comments", "public")
    check("dave", "guest", "read", "homepage", "public")
    check("erin", "editor", "read", "salary_sheet", "confidential")
    check("frank", "admin", "read", "salary_sheet", "confidential")

    print("\nThe rule_trace shows which rules fired; modules in focus_order")
    print("run first — non-admins hitting confidential data get stopped in")
    print("'deny_checks' before 'role_permits' ever gets a chance.")


if __name__ == "__main__":
    main()
