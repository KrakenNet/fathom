"""Tests for Engine.reload_rules — hot-reload semantics (C5, FR-16, AC-5.1).

Covers the hash-trajectory contract documented in design.md C5: callers pass
raw ruleset YAML bytes to ``reload_rules`` and receive ``(hash_before,
hash_after)`` bracketing the atomic swap. The REST / gRPC reload endpoints
echo these values as ``ruleset_hash_before`` / ``ruleset_hash_after`` in
their responses and in the signed audit attestation.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
import yaml

from fathom.engine import Engine
from fathom.errors import CompilationError


def _write_pack(tmp_path: Path) -> None:
    """Set up a minimal templates + modules pack in *tmp_path*.

    ``reload_rules`` assumes templates and modules are already registered
    (it's a rule-only swap; see learnings from T-2.4). This helper emits
    the shared infrastructure both rulesets A and B compile against.
    """
    (tmp_path / "templates.yaml").write_text(
        "templates:\n"
        "  - name: agent\n"
        "    slots:\n"
        "      - name: id\n"
        "        type: symbol\n"
    )
    (tmp_path / "modules.yaml").write_text(
        "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"
    )


def _ruleset_yaml(rule_name: str, subject: str) -> bytes:
    """Build a self-contained ruleset YAML payload for reload_rules."""
    return yaml.safe_dump(
        {
            "ruleset": f"rs-{rule_name}",
            "module": "gov",
            "rules": [
                {
                    "name": rule_name,
                    "when": [
                        {
                            "template": "agent",
                            "conditions": [
                                {"slot": "id", "expression": f"equals({subject})"},
                            ],
                        },
                    ],
                    "then": {"action": "allow", "reason": f"{rule_name} ok"},
                },
            ],
        }
    ).encode("utf-8")


def test_reload_returns_hashes(tmp_path: Path) -> None:
    """reload_rules returns (hash_before, hash_after) matching ruleset_hash trajectory."""
    _write_pack(tmp_path)

    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    engine.load_modules(str(tmp_path / "modules.yaml"))

    # Empty engine has the zero sentinel hash.
    empty_sentinel = "sha256:" + "0" * 64
    assert engine.ruleset_hash == empty_sentinel

    # Load ruleset A.
    ruleset_a = _ruleset_yaml("rule-a", "alice")
    (tmp_path / "rules-a.yaml").write_bytes(ruleset_a)
    engine.load_rules(str(tmp_path / "rules-a.yaml"))

    hash_a = engine.ruleset_hash
    assert hash_a != empty_sentinel
    assert hash_a.startswith("sha256:")

    # Reload with ruleset B (different rule name + subject → different bytes).
    ruleset_b = _ruleset_yaml("rule-b", "bob")
    assert ruleset_a != ruleset_b

    hash_before, hash_after = engine.reload_rules(ruleset_b)

    # Returned tuple brackets the swap: before matches pre-reload state,
    # after matches post-reload state, and the two differ.
    assert hash_before == hash_a
    assert hash_after == engine.ruleset_hash
    assert hash_before != hash_after
    assert hash_before.startswith("sha256:")
    assert hash_after.startswith("sha256:")


def test_reload_compile_failure_preserves_old_env(tmp_path: Path) -> None:
    """reload_rules with broken YAML raises CompilationError and leaves the old env intact (NFR-8).

    Design C5 / AC-5.3 / NFR-8: a failed compile on the fresh env must never
    mutate ``self._env`` or any registry. This codifies the "CompilationError
    leaves old env byte-identical" smoke test T-2.4 relied on.
    """
    _write_pack(tmp_path)

    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    engine.load_modules(str(tmp_path / "modules.yaml"))

    # Load ruleset A — matches agent(id=alice) → allow / "rule-a ok".
    ruleset_a = _ruleset_yaml("rule-a", "alice")
    (tmp_path / "rules-a.yaml").write_bytes(ruleset_a)
    engine.load_rules(str(tmp_path / "rules-a.yaml"))

    hash_before = engine.ruleset_hash
    env_id_before = id(engine._env)

    # Intentionally-broken YAML — unterminated flow sequence. reload_rules
    # wraps yaml.YAMLError as CompilationError (construct="reload_rules:parse").
    broken_yaml = b"ruleset: broken\nmodule: gov\nrules: [{name: broken, when: [{\n"

    with pytest.raises(CompilationError):
        engine.reload_rules(broken_yaml)

    # Invariants after the failure: ruleset_hash unchanged, env identity
    # unchanged (no pointer flip), ruleset A still evaluates to its
    # original decision.
    assert engine.ruleset_hash == hash_before
    assert id(engine._env) == env_id_before

    engine.assert_fact("agent", {"id": "alice"})
    result = engine.evaluate()
    assert result.decision == "allow"
    assert result.reason == "rule-a ok"
    assert result.rule_trace == ["gov::rule-a"]


def test_inflight_eval_atomicity(tmp_path: Path) -> None:
    """In-flight evaluate() stays on the OLD env after reload_rules swaps (C5, AC-5.3).

    Design D1: :class:`Evaluator` snapshots ``env = self._env_provider()`` at
    evaluate() entry. After ``reload_rules(B)`` flips ``self._env``, the
    paused thread-A eval still holds the OLD env reference in its local
    variable and continues firing rules compiled on that old env. The next
    evaluate() — started AFTER the swap — snapshots the NEW env and runs
    ruleset B.

    Coordination is deterministic via two ``threading.Event`` objects — no
    ``time.sleep``:

      * ``callback_reached`` — thread A's RHS-triggered Python callback sets
        this when it enters, signalling the main thread that ``env.run()``
        is paused inside rule A's RHS on the old env.
      * ``release_callback`` — main thread sets this after ``reload_rules``
        returns; the callback unblocks, the RHS completes asserting A's
        decision fact on the old env, eval returns A's decision.

    Ruleset A is built as raw CLIPS via ``load_clips_function`` because
    Fathom YAML's LHS ``test:`` CEs are evaluated at pattern-match time
    (fact-assert or rule-build), not during ``env.run()`` — so a callback
    placed on the LHS would fire in the main thread before the eval even
    starts. An RHS-placed callback fires inside ``env.run()`` in thread A,
    which is the execution point the atomicity invariant guards. Ruleset
    B is a plain YAML ruleset consumed by :meth:`Engine.reload_rules`;
    it makes no callback references so it compiles cleanly onto the new
    env (where user-registered functions from the old env are not
    carried over).
    """
    _write_pack(tmp_path)

    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    engine.load_modules(str(tmp_path / "modules.yaml"))

    callback_reached = threading.Event()
    release_callback = threading.Event()

    def inflight_block() -> bool:
        callback_reached.set()
        # Bounded wait keeps a hung-test failure as a pytest timeout, not
        # a deadlock that blocks the whole suite forever. 30s is generous
        # vs the microseconds the swap takes; the Event will be set
        # promptly.
        released = release_callback.wait(timeout=30.0)
        if not released:
            raise RuntimeError("inflight_block: release_callback never set")
        return True

    engine.register_function("inflight_block", inflight_block)

    # Ruleset A — raw CLIPS so the callback lives on the RHS. The RHS
    # first calls the blocking Python function (which gates the rule's
    # effect on ``release_callback``), then asserts the ``__fathom_decision``
    # fact that the Evaluator reads on return. Salience is irrelevant
    # (single rule) but matches the default. The rule is scoped to
    # ``gov::`` to match the focus_order from _write_pack. ``cb_fn``
    # stands in for ``inflight_block`` — CLIPS is happy with the alias.
    engine.load_clips_function(
        "(defrule gov::rule-a\n"
        "  (agent (id alice))\n"
        "  =>\n"
        "  (bind ?result (inflight_block))\n"
        '  (assert (__fathom_decision\n'
        "    (action allow)\n"
        '    (reason "from-A")\n'
        '    (rule "gov::rule-a")\n'
        "    (log-level summary)\n"
        '    (notify "")\n'
        "    (attestation FALSE)\n"
        '    (metadata ""))))'
    )

    # Ruleset B — plain YAML ``equals(bob)`` → ``deny`` / from-B. No
    # callback reference. reload_rules rebuilds onto a fresh env where
    # the user-registered inflight_block does not exist; ruleset B must
    # not reference it.
    ruleset_b = yaml.safe_dump(
        {
            "ruleset": "rs-b",
            "module": "gov",
            "rules": [
                {
                    "name": "rule-b",
                    "when": [
                        {
                            "template": "agent",
                            "conditions": [
                                {"slot": "id", "expression": "equals(bob)"},
                            ],
                        },
                    ],
                    "then": {"action": "deny", "reason": "from-B"},
                },
            ],
        }
    ).encode("utf-8")

    # Pre-assert the alice fact on the OLD env — thread A's evaluate()
    # will pop the rule-a activation off the agenda, enter the RHS, call
    # inflight_block, and block there.
    engine.assert_fact("agent", {"id": "alice"})

    thread_a_result: list = []
    thread_a_error: list[BaseException] = []

    def run_thread_a() -> None:
        try:
            thread_a_result.append(engine.evaluate())
        except BaseException as exc:  # noqa: BLE001 — surface any failure
            thread_a_error.append(exc)

    thread_a = threading.Thread(target=run_thread_a, name="inflight-eval-A")
    thread_a.start()

    # Wait for thread A's eval to reach the RHS callback. The timeout
    # guards against a missed registration / compile bug showing up as a
    # deadlock.
    assert callback_reached.wait(timeout=30.0), (
        "thread A's callback was never entered — rule-a did not fire or "
        "inflight_block was not registered on the old env"
    )

    # Swap to ruleset B while thread A is paused inside env.run(). The
    # compile work (new Environment + rebuild templates/modules/rules)
    # happens outside self._reload_lock; the lock covers only the pointer
    # swap. Completion returns (hash_before, hash_after).
    hash_before, hash_after = engine.reload_rules(ruleset_b)
    assert hash_before != hash_after

    # Release the callback. Thread A's env.run() resumes on the OLD env,
    # finishes the RHS asserting A's decision fact, eval completes,
    # thread A joins with A's decision.
    release_callback.set()
    thread_a.join(timeout=30.0)
    assert not thread_a.is_alive(), "thread A did not complete within timeout"
    assert not thread_a_error, f"thread A raised: {thread_a_error[0]!r}"
    assert len(thread_a_result) == 1, "thread A did not record a result"

    result_a = thread_a_result[0]
    assert result_a.decision == "allow", (
        f"in-flight eval should have completed on OLD env with A's decision, "
        f"got decision={result_a.decision!r} reason={result_a.reason!r}"
    )
    assert result_a.reason == "from-A"
    assert result_a.rule_trace == ["gov::rule-a"]

    # Second evaluate() — starts AFTER the swap, so its env_provider()
    # snapshot returns the NEW env with ruleset B loaded. Working memory
    # on the new env is empty (reload_rules builds a fresh
    # clips.Environment), so we re-assert the trigger fact that matches B.
    engine.assert_fact("agent", {"id": "bob"})
    result_b = engine.evaluate()
    assert result_b.decision == "deny", (
        f"post-swap eval should run B's rules on the NEW env, "
        f"got decision={result_b.decision!r} reason={result_b.reason!r}"
    )
    assert result_b.reason == "from-B"
    assert result_b.rule_trace == ["gov::rule-b"]
