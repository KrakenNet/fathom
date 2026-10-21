"""A CLIPS runtime error during evaluation fails closed.

CLIPS reports a runtime error -- in a pattern predicate, a ``test:`` CE or a
rule's action -- by printing it and carrying on: the rule that errored does
not match, and an error in an action halts the agenda. Fathom used to return
whatever decision had been written by then, so a higher-salience allow won
over a deny that never got to run. Each case here must raise
:class:`EvaluationError` instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fathom.engine import Engine
from fathom.errors import CompilationError, EvaluationError

if TYPE_CHECKING:
    from pathlib import Path

_TEMPLATES = """
templates:
  - name: req
    slots:
      - {name: user, type: string}
      - {name: role, type: symbol}
      - {name: amount, type: integer}
"""

_ALLOW = """
  - name: allow_admin
    salience: 10
    when:
      - template: req
        conditions:
          - {slot: role, expression: equals(admin)}
    then: {action: allow}
"""

# The user slot is over fathom-matches' 4096-char cap, so the deny rule's
# predicate raises on it: a request can trigger the error on purpose.
_FACTS = [("req", {"user": "evil" + "x" * 5000, "role": "admin", "amount": 0})]


def _engine(tmp_path: Path, rules: str) -> Engine:
    for sub, text in (
        ("templates", _TEMPLATES),
        ("modules", "modules:\n  - name: m\n"),
        ("rules", "ruleset: rs\nmodule: m\nrules:\n" + _ALLOW + rules),
    ):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "a.yaml").write_text(text)
    engine = Engine()
    engine.register_function("risky", _risky)
    engine.load_pack_dir(str(tmp_path))
    return engine


def _risky(_user: str) -> bool:
    raise RuntimeError("backend down")


_OVERSIZED_INPUT = """
  - name: deny_bad_user
    salience: -10
    when:
      - template: req
        conditions:
          - {slot: user, expression: 'matches(^evil)'}
    then: {action: deny, reason: blocked}
"""

_RAISING_TEST = """
  - name: deny_risky
    salience: -10
    when:
      - template: req
        conditions:
          - {slot: user, bind: '?u'}
          - test: (risky ?u)
    then: {action: deny, reason: risky}
"""

_RHS_ERROR = """
  - name: derive
    salience: 0
    when:
      - template: req
        conditions:
          - {slot: amount, bind: '?a'}
    then:
      assert:
        - template: req
          slots: {user: '"x"', role: other, amount: "(div 10 ?a)"}
  - name: deny_all
    salience: -10
    when:
      - template: req
        conditions:
          - {slot: role, expression: equals(admin)}
    then: {action: deny, reason: final}
"""

_CASES = pytest.mark.parametrize(
    "rules",
    [_OVERSIZED_INPUT, _RAISING_TEST, _RHS_ERROR],
    ids=["oversized-input", "raising-test", "rhs"],
)


@_CASES
def test_evaluate_once_raises(tmp_path: Path, rules: str) -> None:
    engine = _engine(tmp_path, rules)
    with pytest.raises(EvaluationError):
        engine.evaluate_once(_FACTS)


@_CASES
def test_evaluate_after_assert_raises(tmp_path: Path, rules: str) -> None:
    """The error can happen at assert time, when CLIPS pattern-matches."""
    engine = _engine(tmp_path, rules)
    engine.assert_facts(_FACTS)
    with pytest.raises(EvaluationError):
        engine.evaluate()


def test_a_reported_error_is_not_reported_again(tmp_path: Path) -> None:
    """Once raised, an error does not fail the next, clean request."""
    engine = _engine(tmp_path, _RHS_ERROR)
    with pytest.raises(EvaluationError):
        engine.evaluate_once(_FACTS)

    result = engine.evaluate_once([("req", {"user": "bob", "role": "admin", "amount": 1})])

    assert result.decision == "deny"


def test_an_invalid_regex_fails_at_load(tmp_path: Path) -> None:
    bad = _OVERSIZED_INPUT.replace("matches(^evil)", "matches([)")
    with pytest.raises(CompilationError, match="invalid regex"):
        _engine(tmp_path, bad)


@_CASES
def test_errors_do_not_echo_to_stderr(
    tmp_path: Path, rules: str, capfd: pytest.CaptureFixture[str]
) -> None:
    """The exception carries the CLIPS text; stderr does not get a second copy."""
    engine = _engine(tmp_path, rules)
    with pytest.raises(EvaluationError):
        engine.evaluate_once(_FACTS)
    bad = _OVERSIZED_INPUT.replace("matches(^evil)", "greater_than(abc)").replace("user", "amount")
    with pytest.raises(CompilationError, match="ARGACCES2"):
        (tmp_path / "bad").mkdir()
        _engine(tmp_path / "bad", bad)
    assert capfd.readouterr().err == ""
