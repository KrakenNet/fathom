#!/usr/bin/env python3
"""Measure the operations README publishes targets for, and enforce them.

README's "Performance Targets" table was a claim with nothing behind it: no
benchmark existed anywhere in the repo, so the numbers could only ever have
been true by accident. This script is the other half of that table. It holds
the numbers (``TARGETS`` below) and ``tests/test_scripts/test_benchmark.py``
fails if README and this file disagree.

Two properties this deliberately has:

* **Compilation is measured per rule, on two packs.** A flat "< 50ms to
  compile" is a claim about pack size, not about the compiler: it held for a
  100-rule synthetic pack and was already false for the SSVC pack this repo
  ships (144 rules, ~164ms). Per-rule is the size-independent claim, and both
  the synthetic pack and a real one are held to it.
* **Gating is on the median, not the max.** These run on shared CI runners
  where one sample can be an order of magnitude off for reasons unrelated to
  this code, and a max-based gate on a 25 microsecond budget would be red most
  mornings. The p95 is printed so a real regression stays visible in the log
  even while it is still under the bar.
* **CI applies a slack factor.** The published targets describe a developer
  machine, which is what a reader of README is holding. A GitHub shared runner
  measured 1.2x to 1.9x slower than that machine across five consecutive runs
  of the same job, so enforcing the published numbers there verbatim would
  fail on the hardware rather than on the code. ``--slack`` multiplies every
  limit and is printed in the header; CI passes 2.0, which covers the
  measured spread with a little room. A regression large enough to matter
  clears that factor easily -- the last one found here was 2x on the
  developer machine, which lands at 4x of the published target on a runner.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import yaml

from fathom.engine import Engine

if TYPE_CHECKING:
    from collections.abc import Callable


class Target(NamedTuple):
    limit_us: float
    unit: str
    #: The exact text of this row's "Target" cell in README.md.
    readme_cell: str


# Keyed by the README table's "Operation" column, verbatim. Change a number
# here and the parity test tells you to change README to match.
TARGETS: dict[str, Target] = {
    "Single rule evaluation": Target(100.0, "us", "< 100µs"),
    "100-rule evaluation": Target(500.0, "us", "< 500µs"),
    "Fact assertion": Target(25.0, "us", "< 25µs"),
    "YAML compilation": Target(2_000.0, "us/rule", "< 2ms per rule"),
}


class Case(NamedTuple):
    """One measurement. ``target_key`` indexes ``TARGETS``; ``label`` is display only."""

    target_key: str
    label: str
    operation: Callable[[], Any]
    iterations: int
    setup: Callable[[], Any] | None = None
    #: Divide each sample by this to reach the target's unit (per-rule targets).
    divisor: int = 1


class Result(NamedTuple):
    label: str
    median: float
    p95: float
    target: Target
    slack: float = 1.0

    @property
    def limit(self) -> float:
        """The target as enforced here: published limit times the slack factor."""
        return self.target.limit_us * self.slack

    @property
    def passed(self) -> bool:
        return self.median <= self.limit


def _write_pack(root: Path, rule_count: int) -> Path:
    """A pack with ``rule_count`` rules over one template.

    Every rule matches a distinct ``level``, so exactly one fires per
    evaluation however many are loaded -- the cost being measured is the
    engine's, not the ruleset's fan-out.
    """
    (root / "templates").mkdir(parents=True)
    (root / "modules").mkdir()
    (root / "rules").mkdir()

    (root / "templates" / "t.yaml").write_text(
        yaml.safe_dump(
            {
                "templates": [
                    {
                        "name": "request",
                        "slots": [
                            {"name": "level", "type": "integer"},
                            {"name": "user", "type": "symbol"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    (root / "modules" / "m.yaml").write_text(
        yaml.safe_dump(
            {
                "modules": [{"name": "bench", "description": "Benchmark rules"}],
                "focus_order": ["bench"],
            }
        ),
        encoding="utf-8",
    )

    (root / "rules" / "r.yaml").write_text(
        yaml.safe_dump(
            {
                "module": "bench",
                "rules": [
                    {
                        "name": f"rule-{i}",
                        "salience": 0,
                        "when": [
                            {
                                "template": "request",
                                "conditions": [{"slot": "level", "expression": f"equals({i})"}],
                            }
                        ],
                        "then": {"action": "allow", "reason": f"level {i} permitted"},
                    }
                    for i in range(rule_count)
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def _measure(case: Case, warmup: int) -> tuple[float, float]:
    """Return (median, p95) per call, in the target's unit.

    ``case.setup`` runs before each iteration and is excluded from the timing:
    the fact-assertion case has to empty working memory between calls, and
    charging that to the assertion publishes a number twice the real one.
    """
    for _ in range(warmup):
        if case.setup is not None:
            case.setup()
        case.operation()

    samples: list[float] = []
    for _ in range(case.iterations):
        if case.setup is not None:
            case.setup()
        start = time.perf_counter_ns()
        case.operation()
        samples.append((time.perf_counter_ns() - start) / 1000.0 / case.divisor)

    samples.sort()
    p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
    return statistics.median(samples), p95


FACTS: list[tuple[str, dict[str, Any]]] = [("request", {"level": 0, "user": "alice"})]

#: Rule count of the packaged SSVC pack, used as the per-rule divisor. Asserted
#: at runtime so a pack edit fails loudly instead of skewing the number.
SSVC_RULE_COUNT = 144


def _load_ssvc() -> Engine:
    engine = Engine()
    engine.load_pack("ssvc")
    return engine


def _cases(iterations: int, workdir: Path) -> list[Case]:
    one_rule = _write_pack(workdir / "one", 1)
    hundred_rules = _write_pack(workdir / "hundred", 100)

    _assert_rules_fire(one_rule)
    _assert_rules_fire(hundred_rules)

    single_engine = Engine.from_rules(str(one_rule))
    hundred_engine = Engine.from_rules(str(hundred_rules))
    assertion_engine = Engine.from_rules(str(one_rule))

    ssvc_rules = len(_load_ssvc().rule_registry)
    if ssvc_rules != SSVC_RULE_COUNT:
        raise SystemExit(
            f"ssvc pack has {ssvc_rules} rules, not {SSVC_RULE_COUNT}; "
            "update SSVC_RULE_COUNT so the per-rule number stays honest"
        )

    # Compilation costs milliseconds a call; the full iteration count would
    # make a CI run minutes long for no extra signal.
    compile_iterations = max(5, iterations // 100)

    return [
        Case(
            "Single rule evaluation",
            "Single rule evaluation",
            lambda: single_engine.evaluate_once(FACTS),
            iterations,
        ),
        Case(
            "100-rule evaluation",
            "100-rule evaluation",
            lambda: hundred_engine.evaluate_once(FACTS),
            iterations,
        ),
        Case(
            "Fact assertion",
            "Fact assertion",
            lambda: assertion_engine.assert_fact("request", {"level": 0, "user": "alice"}),
            iterations,
            # Facts accumulate, and a growing working memory would turn this
            # into a measurement of working-memory size, not of an assertion.
            setup=assertion_engine.clear_facts,
        ),
        Case(
            "YAML compilation",
            "YAML compilation (100 synthetic)",
            lambda: Engine.from_rules(str(hundred_rules)),
            compile_iterations,
            divisor=100,
        ),
        Case(
            "YAML compilation",
            f"YAML compilation (ssvc, {SSVC_RULE_COUNT})",
            _load_ssvc,
            compile_iterations,
            divisor=SSVC_RULE_COUNT,
        ),
    ]


def _assert_rules_fire(pack: Path) -> None:
    """Refuse to report evaluation timings for a pack that fires nothing.

    The first version of this script built a pack with a declared module and
    no ``focus_order``, which at the time meant CLIPS never drained that
    module's agenda: both evaluation cases timed an empty agenda and reported
    healthy microseconds for doing nothing. A benchmark that cannot tell those
    apart is worse than no benchmark.
    """
    result = Engine.from_rules(str(pack)).evaluate_once(FACTS)
    if not result.rule_trace:
        raise SystemExit(
            f"benchmark pack at {pack} fired no rules; the evaluation timings "
            "would measure an empty agenda"
        )


def run(iterations: int, warmup: int, workdir: Path, slack: float = 1.0) -> list[Result]:
    results = []
    for case in _cases(iterations, workdir):
        median, p95 = _measure(case, warmup)
        results.append(Result(case.label, median, p95, TARGETS[case.target_key], slack))
    return results


def _format(results: list[Result], slack: float) -> str:
    width = max(len(r.label) for r in results)
    header = "limit" if slack == 1.0 else f"limit (target x{slack:g})"
    lines = [
        f"{'Operation':<{width}} {'median':>18} {'p95':>18} {header:>18}",
        f"{'-' * width} {'-' * 18} {'-' * 18} {'-' * 18}",
    ]
    for r in results:
        unit = r.target.unit
        lines.append(
            f"{r.label:<{width}} {r.median:>10.1f} {unit:<7} {r.p95:>10.1f} {unit:<7} "
            f"{r.limit:>10.1f} {unit:<7} {'ok' if r.passed else 'MISS'}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument(
        "--slack",
        type=float,
        default=1.0,
        help=(
            "multiply every published target by this before gating. CI passes 1.5 "
            "because a shared runner is slower than the machine the targets describe."
        ),
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print the table but always exit 0 (for local profiling)",
    )
    args = parser.parse_args()

    if args.slack < 1.0:
        raise SystemExit("--slack below 1.0 would gate tighter than the published target")

    with tempfile.TemporaryDirectory() as tmp:
        results = run(args.iterations, args.warmup, Path(tmp), args.slack)

    print(_format(results, args.slack))

    missed = [r for r in results if not r.passed]
    if missed and not args.report_only:
        for r in missed:
            print(
                f"::error::{r.label} median {r.median:.1f}{r.target.unit} exceeds the "
                f"{r.limit:.1f}{r.target.unit} limit "
                f"({r.target.limit_us:.1f}{r.target.unit} published in README.md"
                f"{f', x{r.slack:g} slack' if r.slack != 1.0 else ''})"
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
