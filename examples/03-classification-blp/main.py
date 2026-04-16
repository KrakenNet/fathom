"""Example 03 — Bell-LaPadula with Compartments.

Multi-level security using the Bell-LaPadula model:

- Simple security property: no read up
- *-property:               no write down
- Need-to-know:             compartments must match

The hierarchy is defined in YAML (``hierarchies/clearance.yaml``), registered
with a classification function (``functions/clearance.yaml``), and rules use
``below(...)``, ``meets_or_exceeds(...)`` and ``has_compartments(...)``
operators to compare levels and compartment sets.

Compartments are pipe-delimited strings — e.g. ``"NOFORN|SI|TK"``. The builtin
``has_compartments`` operator is a subset check.

Run:
    uv run python examples/03-classification-blp/main.py
"""

from __future__ import annotations

from pathlib import Path

from fathom import Engine

HERE = Path(__file__).parent


def make_engine() -> Engine:
    engine = Engine()
    engine.load_templates(str(HERE / "templates"))
    engine.load_modules(str(HERE / "modules"))
    engine.load_functions(str(HERE / "functions"))
    engine.load_rules(str(HERE / "rules"))
    return engine


def check(
    s_id: str,
    s_clearance: str,
    s_comps: str,
    o_id: str,
    o_classification: str,
    o_comps: str,
    mode: str,
) -> None:
    engine = make_engine()
    engine.assert_facts(
        [
            (
                "subject",
                {"id": s_id, "clearance": s_clearance, "compartments": s_comps},
            ),
            (
                "resource",
                {
                    "id": o_id,
                    "classification": o_classification,
                    "compartments": o_comps,
                },
            ),
            (
                "access_request",
                {"subject_id": s_id, "object_id": o_id, "mode": mode},
            ),
        ]
    )
    result = engine.evaluate()
    s_desc = f"{s_clearance}[{s_comps or '-'}]"
    o_desc = f"{o_classification}[{o_comps or '-'}]"
    print(
        f"  {mode:<5} {s_id:<6} {s_desc:<30} -> {o_id:<14} {o_desc:<30} "
        f"=> {result.decision:<5}  {result.reason or '(default deny)'}"
    )


def main() -> None:
    print("Fathom — Example 03: Bell-LaPadula with Compartments\n")
    print("Hierarchy: unclassified < cui < confidential < secret < top-secret\n")
    print("scenarios (mode, subject, -> object):\n")

    # Clean reads (no compartments)
    check(
        "alice", "top-secret", "", "intel-01", "secret", "", "read"
    )  # clearance dominates — allow
    check("bob", "confidential", "", "intel-01", "secret", "", "read")  # read-up — deny
    check(
        "carol", "secret", "", "report-02", "unclassified", "", "read"
    )  # clearance dominates — allow

    # Writes ( *-property — no write down)
    check(
        "alice", "top-secret", "", "shared-03", "top-secret", "", "write"
    )  # equal — allow
    check(
        "alice", "top-secret", "", "public-blog", "unclassified", "", "write"
    )  # write-down — deny
    check(
        "bob", "confidential", "", "intel-01", "secret", "", "write"
    )  # write-up — allow

    # Compartment checks (need-to-know)
    check(
        "diana", "secret", "SI|TK", "sigint-04", "secret", "SI", "read"
    )  # subject covers object — allow
    check(
        "eve", "secret", "SI", "sigint-04", "secret", "SI|TK", "read"
    )  # missing TK — deny
    check(
        "frank", "top-secret", "", "sigint-04", "secret", "SI|TK", "read"
    )  # no compartments at all — deny
    check(
        "grace", "secret", "SI", "shared-03", "top-secret", "SI|TK", "write"
    )  # object compartments cover subject — allow
    check(
        "henry", "secret", "SI|TK", "shared-03", "top-secret", "SI", "write"
    )  # object missing TK — deny


if __name__ == "__main__":
    main()
