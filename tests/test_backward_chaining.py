"""Backward chaining flag tests for experimental_backward_chaining parameter."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from fathom.engine import Engine

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# 1. Flag default value
# ---------------------------------------------------------------------------


class TestBackwardChainingDefault:
    """Verify the flag defaults to False."""

    def test_default_is_false(self) -> None:
        engine = Engine()
        assert engine._experimental_backward_chaining is False

    def test_explicit_false(self) -> None:
        engine = Engine(experimental_backward_chaining=False)
        assert engine._experimental_backward_chaining is False

    def test_no_warning_when_false(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Engine(experimental_backward_chaining=False)
            bc_warnings = [x for x in w if "backward chaining" in str(x.message).lower()]
            assert len(bc_warnings) == 0


# ---------------------------------------------------------------------------
# 2. Flag enabled
# ---------------------------------------------------------------------------


class TestBackwardChainingEnabled:
    """Verify setting the flag to True and warning behavior."""

    def test_flag_set_true(self) -> None:
        engine = Engine(experimental_backward_chaining=True)
        assert engine._experimental_backward_chaining is True

    def test_warning_issued_when_true(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Engine(experimental_backward_chaining=True)
            bc_warnings = [x for x in w if "backward chaining" in str(x.message).lower()]
            assert len(bc_warnings) == 1

    def test_warning_message_content(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Engine(experimental_backward_chaining=True)
            bc_warnings = [x for x in w if "backward chaining" in str(x.message).lower()]
            assert "experimental" in str(bc_warnings[0].message).lower()


# ---------------------------------------------------------------------------
# 3. Forward chaining still works with flag on
# ---------------------------------------------------------------------------


class TestForwardChainingWithFlagOn:
    """Forward chaining must work regardless of backward chaining flag."""

    @pytest.fixture
    def bc_engine(self, tmp_path: Path) -> Engine:
        """Engine with backward chaining enabled and a simple rule set."""
        tmpl = """templates:
  - name: request
    slots:
      - name: kind
        type: symbol
        required: true
"""
        (tmp_path / "templates.yaml").write_text(tmpl)

        mod = """modules:
  - name: bc_mod
focus_order:
  - bc_mod
"""
        (tmp_path / "modules.yaml").write_text(mod)

        rules = """module: bc_mod
rules:
  - name: deny-admin
    salience: 50
    when:
      - template: request
        conditions:
          - slot: kind
            expression: "equals(admin)"
    then:
      action: deny
      reason: "Admin requests denied"
"""
        (tmp_path / "rules.yaml").write_text(rules)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            e = Engine(experimental_backward_chaining=True)
        e.load_templates(str(tmp_path / "templates.yaml"))
        e.load_modules(str(tmp_path / "modules.yaml"))
        e.load_rules(str(tmp_path / "rules.yaml"))
        return e

    def test_rule_fires_with_flag_on(self, bc_engine: Engine) -> None:
        bc_engine.assert_fact("request", {"kind": "admin"})
        result = bc_engine.evaluate()
        assert result.decision == "deny"

    def test_default_decision_with_flag_on(self, bc_engine: Engine) -> None:
        bc_engine.assert_fact("request", {"kind": "read"})
        result = bc_engine.evaluate()
        assert result.decision == "deny"  # default decision (fail-closed)

    def test_rule_trace_present_with_flag_on(self, bc_engine: Engine) -> None:
        bc_engine.assert_fact("request", {"kind": "admin"})
        result = bc_engine.evaluate()
        assert len(result.rule_trace) > 0


# ---------------------------------------------------------------------------
# 4. No effect when flag is off (baseline parity)
# ---------------------------------------------------------------------------


class TestNoEffectWhenFlagOff:
    """Behavior must be identical whether flag is off or on."""

    @pytest.fixture
    def engines(self, tmp_path: Path) -> tuple[Engine, Engine]:
        """Return (flag_off, flag_on) engines with same rules."""
        tmpl = """templates:
  - name: action_req
    slots:
      - name: op
        type: symbol
        required: true
"""
        (tmp_path / "templates.yaml").write_text(tmpl)

        mod = """modules:
  - name: parity_mod
focus_order:
  - parity_mod
"""
        (tmp_path / "modules.yaml").write_text(mod)

        rules = """module: parity_mod
rules:
  - name: allow-read
    salience: 50
    when:
      - template: action_req
        conditions:
          - slot: op
            expression: "equals(read)"
    then:
      action: allow
      reason: "Read allowed"
"""
        (tmp_path / "rules.yaml").write_text(rules)

        e_off = Engine(experimental_backward_chaining=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            e_on = Engine(experimental_backward_chaining=True)

        for e in (e_off, e_on):
            e.load_templates(str(tmp_path / "templates.yaml"))
            e.load_modules(str(tmp_path / "modules.yaml"))
            e.load_rules(str(tmp_path / "rules.yaml"))

        return e_off, e_on

    def test_same_decision_when_rule_fires(
        self,
        engines: tuple[Engine, Engine],
    ) -> None:
        e_off, e_on = engines
        e_off.assert_fact("action_req", {"op": "read"})
        e_on.assert_fact("action_req", {"op": "read"})
        assert e_off.evaluate().decision == e_on.evaluate().decision

    def test_same_decision_when_no_rule_fires(
        self,
        engines: tuple[Engine, Engine],
    ) -> None:
        e_off, e_on = engines
        e_off.assert_fact("action_req", {"op": "write"})
        e_on.assert_fact("action_req", {"op": "write"})
        assert e_off.evaluate().decision == e_on.evaluate().decision

    def test_fact_operations_unaffected(
        self,
        engines: tuple[Engine, Engine],
    ) -> None:
        e_off, e_on = engines
        for e in (e_off, e_on):
            e.assert_fact("action_req", {"op": "read"})
            assert e.count("action_req") == 1
            results = e.query("action_req")
            assert len(results) == 1
            retracted = e.retract("action_req")
            assert retracted == 1
            assert e.count("action_req") == 0
