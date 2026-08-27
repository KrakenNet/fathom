"""No suite in this set may pass by asserting on the machinery.

Structural check G from the audit post-mortem. Every finding these paths were
supposed to catch was already "covered" by a test that passed while the
behaviour was broken, because the assertion was about the machinery rather
than the answer:

- ``assert "trust" in engine._hierarchy_registry`` stayed true for the whole
  life of the bug where the trust ladder ranked every level at ``-1``;
- ``engine.evaluate_once.assert_called_once()`` says an adapter reached the
  engine, not that a deny stopped the call.

So the paths whose job is to prove real behaviour are held to it mechanically:
no assertion on a private attribute, and no mock-call assertion. The adapter
unit suites are deliberately *not* in scope -- their mock call-args checks are
how they read the fact an adapter scoped, and
``tests/contracts/test_adapter_dispatch.py`` asserts the blocking behaviour
against a real engine.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent

#: Paths whose findings were missed by proxy assertions, plus the contract
#: suites written to replace them.
COVERED = [
    "tests/contracts",
    "tests/integrations",
    "tests/test_adapters_real_engine.py",
    "tests/test_chained_log.py",
    "tests/test_classification_ops.py",
]

#: ``assert ... obj._private ...`` -- the state behind the answer.
PRIVATE_ATTR = re.compile(r"^\s*assert\b.*\b[A-Za-z_][\w\]\)]*\._[a-z]")

#: ``mock.assert_called_once()``, ``mock.call_count == 1`` -- that a call
#: happened, not what it decided.
MOCK_CALL = re.compile(
    r"\.(assert_(called|not_called|any_call|has_calls|awaited)\w*|call_count)\b"
)


def _files() -> list[Path]:
    files: list[Path] = []
    for entry in COVERED:
        target = REPO / entry
        files.extend(sorted(target.rglob("test_*.py")) if target.is_dir() else [target])
    return [f for f in files if f != Path(__file__)]


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_the_suite_asserts_on_answers_not_on_machinery(path: Path) -> None:
    offenders = [
        f"{path.relative_to(REPO)}:{number}: {line.strip()}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if PRIVATE_ATTR.search(line) or MOCK_CALL.search(line)
    ]

    assert not offenders, "assert on what the code answered, not on its internals:\n" + "\n".join(
        offenders
    )
