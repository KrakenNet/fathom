"""Engine must serialise concurrent CLIPS access (C1).

Before ``Engine._lock`` existed, two threads calling
``assert_fact``/``evaluate``/``retract`` on one Engine corrupted the CLIPS
heap and aborted the whole interpreter (``*** CLIPS SYSTEM ERROR *** ID =
MEMORY1``, ``malloc(): corrupted top size``). That kills the process, not
just the request, so the hammer runs in a **subprocess**: this test asserts
the child exits 0, which it cannot do on the unlocked engine.

Marked ``concurrency`` so it can be excluded wholesale
(``pytest -m "not concurrency"``) if it ever proves flaky in CI.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.concurrency

REPO_ROOT = Path(__file__).resolve().parents[1]
RULES = REPO_ROOT / "examples" / "01-hello-allow-deny"

THREADS = 4
ITERATIONS = 150
RELOAD_ROUNDS = 20
TIMEOUT_S = 180.0


def _worker() -> int:
    """Hammer one shared Engine from several threads. Returns an exit code."""
    import threading

    from fathom.engine import Engine

    engine = Engine.from_rules(str(RULES))
    ruleset_yaml = (RULES / "rules" / "access.yaml").read_bytes()
    errors: list[BaseException] = []
    stop = threading.Event()

    def hammer(worker_id: int) -> None:
        try:
            for i in range(ITERATIONS):
                agent_id = f"a{worker_id}-{i}"
                engine.assert_fact("agent", {"id": agent_id, "clearance": "secret"})
                engine.assert_fact(
                    "data_request",
                    {
                        "agent_id": agent_id,
                        "classification": "top-secret" if i % 2 else "secret",
                        "resource": f"r{i}",
                    },
                )
                engine.evaluate()
                engine.query("agent", {"id": agent_id})
                engine.count("data_request")
                engine.retract("agent", {"id": agent_id})
                engine.retract("data_request", {"agent_id": agent_id})
        except BaseException as exc:  # noqa: BLE001 -- reported, not swallowed
            errors.append(exc)

    def reloader() -> None:
        try:
            for _ in range(RELOAD_ROUNDS):
                if stop.is_set():
                    return
                engine.reload_rules(ruleset_yaml)
        except BaseException as exc:  # noqa: BLE001 -- reported, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(THREADS)]
    threads.append(threading.Thread(target=reloader))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()

    if errors:
        for exc in errors:
            print(f"WORKER-ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print("WORKER-OK")
    return 0


def test_concurrent_engine_access_does_not_corrupt_clips() -> None:
    """N threads + a concurrent reload on one Engine must not crash or error."""
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0, (
        f"concurrent hammer exited {proc.returncode} "
        f"(negative means a fatal signal — CLIPS heap corruption)\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "WORKER-OK" in proc.stdout


if __name__ == "__main__":  # pragma: no cover -- subprocess entry point
    sys.exit(_worker())


# ---------------------------------------------------------------------------
# Snapshot iteration vs. hot reload
# ---------------------------------------------------------------------------
#
# ``reload_rules`` rebuilds ``_template_registry`` IN PLACE (clear() +
# update()) and does so under ``_reload_lock`` — not under ``_lock``. The
# audit/attestation snapshots run inside ``evaluate()`` under ``_lock``, so
# the two are not mutually excluded: iterating the live dict raised
# ``RuntimeError: dictionary changed size during iteration`` mid-evaluation.
#
# Since the attestation/audit fix these snapshots run on EVERY evaluate()
# whenever an attestation service or a recording audit sink is configured,
# so the exposure is far wider than the old ``_has_asserting_rules`` path.
# The subprocess hammer above cannot catch it: its engine has no attestation
# service and a Null sink, so both snapshots are skipped.


@pytest.mark.parametrize("snapshot", ["_snapshot_input_facts", "_snapshot_user_facts"])
def test_snapshot_survives_registry_rebuild_mid_iteration(snapshot: str) -> None:
    """Deterministic stand-in for the reload race: mutate the registry mid-walk."""
    from fathom.engine import Engine
    from fathom.models import SlotDefinition, SlotType, TemplateDefinition

    engine = Engine.from_rules(str(RULES))
    engine.assert_fact("agent", {"id": "alice", "clearance": "secret"})

    real_query = engine._fact_manager.query
    fired = False

    def racing_query(template_name: str):  # type: ignore[no-untyped-def]
        nonlocal fired
        if not fired:
            fired = True
            # Exactly what reload_rules does, from another thread.
            engine._template_registry["injected_by_reload"] = TemplateDefinition(
                name="injected_by_reload",
                slots=[SlotDefinition(name="x", type=SlotType.STRING)],
            )
        return real_query(template_name)

    engine._fact_manager.query = racing_query  # type: ignore[method-assign]
    # Must not raise "dictionary changed size during iteration".
    getattr(engine, snapshot)()
    assert fired
