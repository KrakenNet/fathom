"""End-to-end FleetEngine tests against real Redis and PostgreSQL containers.

Also hosts the container plumbing shared with :mod:`tests.test_fleet_redis` and
:mod:`tests.test_fleet_pg`. Every test here is marked ``integration`` and skips
when Docker is unavailable.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import socket
import subprocess
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from fathom.engine import Engine

pytestmark = pytest.mark.integration

REDIS_IMAGE = "redis:7-alpine"
POSTGRES_IMAGE = "postgres:16-alpine"
POSTGRES_PASSWORD = "fathom-test"

DOCKER_REASON = "docker is not available on this host"


@functools.cache
def docker_available() -> bool:
    """Return True if a usable Docker daemon is reachable.

    Cached, and evaluated lazily: probing at import time ran a `docker info`
    subprocess (up to a 30s timeout) on EVERY collection of the test suite,
    including runs that touch none of these tests.
    """
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


class _NoDocker:
    """Truthy iff Docker is unavailable, decided the first time it is asked.

    ``pytest.mark.skipif(not docker_available(), ...)`` probed Docker at
    IMPORT time, so every collection of the whole suite paid a `docker info`
    subprocess (up to a 30s timeout) even for runs that touch none of these
    tests. pytest evaluates a non-string condition at test setup, so
    deferring the probe behind ``__bool__`` keeps unrelated runs clean.

    A string condition would work too, but it is evaluated in the globals of
    whichever module applies the marker — and `requires_docker` is imported
    by the Redis and Postgres suites as well.
    """

    def __bool__(self) -> bool:
        return not docker_available()


requires_docker = pytest.mark.skipif(_NoDocker(), reason=DOCKER_REASON)


def wait_until(check: Callable[[], bool], timeout: float = 60.0) -> None:
    """Poll *check* until it returns True or *timeout* seconds elapse.

    A *check* that raises counts as "not ready yet": the host-side probes below
    connect over TCP, and a server mid-startup refuses or resets rather than
    answering, which surfaces as an exception rather than a False.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except Exception:  # noqa: BLE001 - any failure means "not ready yet"
            pass
        time.sleep(0.25)
    raise TimeoutError("container did not become ready in time")


@contextlib.contextmanager
def running_container(
    image: str,
    container_port: int,
    env: dict[str, str] | None = None,
) -> Iterator[tuple[str, int]]:
    """Run *image* detached with *container_port* published on a free host port.

    Yields ``(container_id, host_port)`` and force-removes the container on exit.
    """
    cmd = ["docker", "run", "-d", "--rm", "-p", f"127.0.0.1::{container_port}"]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd.append(image)
    container_id = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    try:
        published = subprocess.run(
            ["docker", "port", container_id, str(container_port)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        host_port = int(published.splitlines()[0].rsplit(":", 1)[1])
        yield container_id, host_port
    finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, check=False)


def tcp_answers(host: str, port: int) -> bool:
    """True when *host*:*port* completes a TCP handshake.

    Readiness must be probed from the HOST, the way the tests connect. An
    in-container ``redis-cli ping`` answers over the unix socket and can pass
    before the published port is accepting.
    """
    with socket.create_connection((host, port), timeout=1.0):
        return True


def postgres_accepts(dsn: str) -> bool:
    """True when *dsn* completes a real asyncpg connect-and-close.

    ``pg_isready`` inside the container is NOT a readiness signal: the image
    runs initdb against a temporary server and then restarts it, so pg_isready
    passes during init while the host's next TCP connect is reset ("[Errno 104]
    Connection reset by peer"). Poll a real connect instead -- the same client,
    over the same socket, as the tests use.
    """
    import asyncpg

    async def _probe() -> bool:
        conn = await asyncpg.connect(dsn, timeout=2.0)
        await conn.close()
        return True

    return asyncio.run(_probe())


@pytest.fixture(scope="session")
def redis_port() -> Iterator[int]:
    """Start a Redis container for the test session and yield its host port."""
    with running_container(REDIS_IMAGE, 6379) as (_container_id, host_port):
        wait_until(lambda: tcp_answers("127.0.0.1", host_port))
        yield host_port


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    """Start a PostgreSQL container for the test session and yield its DSN."""
    with running_container(
        POSTGRES_IMAGE,
        5432,
        env={"POSTGRES_PASSWORD": POSTGRES_PASSWORD},
    ) as (_container_id, host_port):
        dsn = f"postgresql://postgres:{POSTGRES_PASSWORD}@127.0.0.1:{host_port}/postgres"
        wait_until(lambda: postgres_accepts(dsn), timeout=60.0)
        yield dsn


def seed_shared_status(engine: Engine) -> None:
    """Register a fleet-scoped ``shared_status`` template on *engine*."""
    from fathom.models import SlotDefinition, SlotType, TemplateDefinition

    engine._template_registry["shared_status"] = TemplateDefinition(
        name="shared_status",
        scope="fleet",
        slots=[
            SlotDefinition(
                name="status",
                type=SlotType.STRING,
                required=True,
                allowed_values=["online", "offline"],
            )
        ],
    )
    engine._safe_build(
        "(deftemplate shared_status (slot status (type STRING)))",
        context="shared_status",
    )


# ---------------------------------------------------------------------------
# FleetEngine over a real Redis backend
# ---------------------------------------------------------------------------


@requires_docker
class TestFleetEngineOverRedis:
    """FleetEngine write-through and sync against RedisFactStore."""

    @pytest.mark.asyncio
    async def test_write_through_reaches_peer_session(
        self, redis_port: int, tmp_path: Path
    ) -> None:
        from fathom.fleet import FleetEngine
        from fathom.fleet_redis import RedisFactStore

        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        store = RedisFactStore(host="127.0.0.1", port=redis_port, db=1)
        try:
            fleet = FleetEngine(fact_store=store, rules_path=str(rules_dir))
            node_a = fleet.create_session("A")
            seed_shared_status(node_a)
            node_b = fleet.create_session("B")
            seed_shared_status(node_b)

            await fleet.assert_fact("A", "shared_status", {"status": "online"})
            await fleet.sync_fleet_facts(node_b)

            assert node_b.query("shared_status") == [{"status": "online"}]
        finally:
            await store.retract("shared_status")
            await store.close()

    @pytest.mark.asyncio
    async def test_invalid_fact_never_reaches_redis(self, redis_port: int, tmp_path: Path) -> None:
        from fathom.errors import ValidationError
        from fathom.fleet import FleetEngine
        from fathom.fleet_redis import RedisFactStore

        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        store = RedisFactStore(host="127.0.0.1", port=redis_port, db=2)
        try:
            fleet = FleetEngine(fact_store=store, rules_path=str(rules_dir))
            node_a = fleet.create_session("A")
            seed_shared_status(node_a)

            with pytest.raises(ValidationError):
                await fleet.assert_fact("A", "shared_status", {"status": "BOGUS"})

            assert await store.count("shared_status") == 0
        finally:
            await store.retract("shared_status")
            await store.close()

    @pytest.mark.asyncio
    async def test_poison_row_does_not_block_peer_sync(
        self, redis_port: int, tmp_path: Path
    ) -> None:
        from fathom.fleet import FleetEngine
        from fathom.fleet_redis import RedisFactStore

        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        store = RedisFactStore(host="127.0.0.1", port=redis_port, db=3)
        try:
            # A row published by a node running different rules.
            await store.assert_fact("shared_status", {"status": "BOGUS"})
            await store.assert_fact("shared_status", {"status": "offline"})

            fleet = FleetEngine(fact_store=store, rules_path=str(rules_dir))
            peer = fleet.create_session("B")
            seed_shared_status(peer)
            await fleet.sync_fleet_facts(peer)

            assert peer.query("shared_status") == [{"status": "offline"}]
        finally:
            await store.retract("shared_status")
            await store.close()


# ---------------------------------------------------------------------------
# FleetEngine over a real PostgreSQL backend
# ---------------------------------------------------------------------------


@requires_docker
class TestFleetEngineOverPostgres:
    """FleetEngine write-through and sync against PostgresFactStore."""

    @pytest.mark.asyncio
    async def test_write_through_reaches_peer_session(
        self, postgres_dsn: str, tmp_path: Path
    ) -> None:
        from fathom.fleet import FleetEngine
        from fathom.fleet_pg import PostgresFactStore

        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        store = PostgresFactStore(postgres_dsn)
        await store.connect()
        try:
            await store.retract("shared_status")
            fleet = FleetEngine(fact_store=store, rules_path=str(rules_dir))
            node_a = fleet.create_session("A")
            seed_shared_status(node_a)
            node_b = fleet.create_session("B")
            seed_shared_status(node_b)

            fact_id = await fleet.assert_fact("A", "shared_status", {"status": "online"})
            assert fact_id is not None

            await fleet.sync_fleet_facts(node_b)
            assert node_b.query("shared_status") == [{"status": "online"}]
        finally:
            await store.retract("shared_status")
            await store.close()

    @pytest.mark.asyncio
    async def test_invalid_fact_never_reaches_postgres(
        self, postgres_dsn: str, tmp_path: Path
    ) -> None:
        from fathom.errors import ValidationError
        from fathom.fleet import FleetEngine
        from fathom.fleet_pg import PostgresFactStore

        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        store = PostgresFactStore(postgres_dsn)
        await store.connect()
        try:
            await store.retract("shared_status")
            fleet = FleetEngine(fact_store=store, rules_path=str(rules_dir))
            node_a = fleet.create_session("A")
            seed_shared_status(node_a)

            with pytest.raises(ValidationError):
                await fleet.assert_fact("A", "shared_status", {"status": "BOGUS"})

            assert await store.count("shared_status") == 0
        finally:
            await store.retract("shared_status")
            await store.close()
