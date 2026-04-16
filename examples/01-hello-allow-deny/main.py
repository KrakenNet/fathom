"""Example 01 — Hello Allow/Deny.

The simplest possible Fathom policy: a clearance vs classification check.

Mirrors the README's Quick Start. Demonstrates:
- Declaring templates in YAML
- Declaring rules with salience (allow: high, deny: low) for fail-closed last-write-wins
- Asserting facts and running `engine.evaluate()`

Run:
    uv run python examples/01-hello-allow-deny/main.py
"""

from __future__ import annotations

from pathlib import Path

from fathom import Engine

HERE = Path(__file__).parent


def evaluate_scenario(
    agent_id: str,
    clearance: str,
    classification: str,
    resource: str,
) -> None:
    """Spin up a fresh engine, assert the facts, and print the decision."""
    engine = Engine()
    engine.load_templates(str(HERE / "templates"))
    engine.load_modules(str(HERE / "modules"))
    engine.load_rules(str(HERE / "rules"))

    engine.assert_fact("agent", {"id": agent_id, "clearance": clearance})
    engine.assert_fact(
        "data_request",
        {
            "agent_id": agent_id,
            "classification": classification,
            "resource": resource,
        },
    )

    result = engine.evaluate()
    print(
        f"  [{clearance:>12} -> {classification:<12}] "
        f"{result.decision:<5}  ({result.duration_us}us)  {result.reason}"
    )


def main() -> None:
    print("Fathom — Example 01: Hello Allow/Deny\n")

    print("Scenarios:")
    evaluate_scenario("alice", "top-secret", "unclassified", "public_reports")
    evaluate_scenario("bob", "confidential", "unclassified", "public_reports")
    evaluate_scenario("carol", "confidential", "secret", "hr_records")
    evaluate_scenario("dave", "secret", "top-secret", "nuclear_codes")
    evaluate_scenario("erin", "unclassified", "unclassified", "cafeteria_menu")

    print("\nNote: when no rule matches, the engine falls back to its default")
    print("decision, which is 'deny' (fail-closed).")


if __name__ == "__main__":
    main()
