"""gRPC ``SubscribeChanges`` real-stream parity (FR for fact-change feed).

Spins up a :class:`FathomServicer` on a free loopback port, opens a
streaming subscription, and verifies that ``AssertFact`` + ``Retract``
RPCs against the same session push :class:`fathom_pb2.FactChange`
messages to the subscriber.

Tests:

* ``test_subscribe_receives_assert`` — assert one fact, expect one
  ``ASSERT`` message with matching template + slot data.
* ``test_subscribe_receives_retract`` — pre-populate a fact, then
  retract it, expect one ``RETRACT`` message.
* ``test_subscribe_isolated_per_session`` — events on session A do not
  bleed into a subscriber on session B.
"""

from __future__ import annotations

import json
import socket
import threading
from concurrent import futures
from typing import TYPE_CHECKING

import grpc
import pytest

from fathom.engine import Engine
from fathom.integrations.grpc_server import FathomServicer
from fathom.proto import fathom_pb2, fathom_pb2_grpc

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _engine_with_event_template(tmp_path: Path) -> Engine:
    (tmp_path / "templates.yaml").write_text(
        "templates:\n"
        "  - name: event\n"
        "    slots:\n"
        "      - name: kind\n"
        "        type: string\n"
        "        required: true\n"
    )
    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    return engine


@pytest.fixture
def grpc_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[str]:
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")

    servicer = FathomServicer(
        default_engine=_engine_with_event_template(tmp_path),
    )
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    fathom_pb2_grpc.add_FathomServiceServicer_to_server(servicer, server)
    port = _free_port()
    server.add_insecure_port(f"127.0.0.1:{port}")
    server.start()
    try:
        yield f"127.0.0.1:{port}"
    finally:
        server.stop(grace=None).wait(timeout=2.0)


_AUTH_META = (("authorization", "Bearer testtok"),)


def _collect_one(stream, *, timeout: float = 3.0) -> fathom_pb2.FactChange:
    """Pull a single FactChange from *stream* with a wall-clock timeout."""
    holder: list[fathom_pb2.FactChange] = []

    def reader() -> None:
        try:
            for msg in stream:
                holder.append(msg)
                return
        except grpc.RpcError:
            # Stream cancelled by the test after we collected; benign.
            return

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout=timeout)
    assert holder, "subscriber never received a FactChange before timeout"
    return holder[0]


def test_subscribe_receives_assert(grpc_server: str) -> None:
    target = grpc_server
    with grpc.insecure_channel(target) as channel:
        stub = fathom_pb2_grpc.FathomServiceStub(channel)
        sub_stream = stub.SubscribeChanges(
            fathom_pb2.SubscribeRequest(session_id=""),
            metadata=_AUTH_META,
            timeout=10.0,
        )
        # Race: the server-side generator must have registered its
        # listener before we call AssertFact. Sleep briefly to let the
        # subscriber thread spin up; the test stays well under the
        # _collect_one timeout.
        import time

        time.sleep(0.2)

        stub.AssertFact(
            fathom_pb2.AssertFactRequest(
                session_id="",
                template="event",
                data_json=json.dumps({"kind": "boot"}),
            ),
            metadata=_AUTH_META,
            timeout=5.0,
        )
        msg = _collect_one(sub_stream)
        sub_stream.cancel()

    assert msg.change_type == fathom_pb2.ChangeType.ASSERT
    assert msg.template == "event"
    assert json.loads(msg.data_json) == {"kind": "boot"}


def test_subscribe_receives_retract(grpc_server: str) -> None:
    target = grpc_server
    with grpc.insecure_channel(target) as channel:
        stub = fathom_pb2_grpc.FathomServiceStub(channel)
        # Pre-populate so the subscriber only sees the retract.
        stub.AssertFact(
            fathom_pb2.AssertFactRequest(
                session_id="",
                template="event",
                data_json=json.dumps({"kind": "doomed"}),
            ),
            metadata=_AUTH_META,
            timeout=5.0,
        )
        sub_stream = stub.SubscribeChanges(
            fathom_pb2.SubscribeRequest(session_id=""),
            metadata=_AUTH_META,
            timeout=10.0,
        )
        import time

        time.sleep(0.2)

        stub.Retract(
            fathom_pb2.RetractRequest(
                session_id="",
                template="event",
                filter_json=json.dumps({"kind": "doomed"}),
            ),
            metadata=_AUTH_META,
            timeout=5.0,
        )
        msg = _collect_one(sub_stream)
        sub_stream.cancel()

    assert msg.change_type == fathom_pb2.ChangeType.RETRACT
    assert msg.template == "event"
    assert json.loads(msg.data_json) == {"kind": "doomed"}


def test_subscribe_isolated_per_session(grpc_server: str) -> None:
    """Subscriber on session A must not receive events on session B."""
    target = grpc_server
    with grpc.insecure_channel(target) as channel:
        stub = fathom_pb2_grpc.FathomServiceStub(channel)
        sub_stream = stub.SubscribeChanges(
            fathom_pb2.SubscribeRequest(session_id="session-A"),
            metadata=_AUTH_META,
            timeout=4.0,
        )
        import time

        time.sleep(0.2)

        # Wrong session — should NOT reach the subscriber. Note the
        # session-B engine has no templates loaded so AssertFact would
        # fail; instead, fire on the default-engine session ("") which
        # also differs from session-A.
        stub.AssertFact(
            fathom_pb2.AssertFactRequest(
                session_id="",
                template="event",
                data_json=json.dumps({"kind": "noise"}),
            ),
            metadata=_AUTH_META,
            timeout=5.0,
        )
        # Wait a beat to confirm no event arrives, then cancel.
        holder: list[fathom_pb2.FactChange] = []

        def reader() -> None:
            try:
                for msg in sub_stream:
                    holder.append(msg)
                    return
            except grpc.RpcError:
                return

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout=1.5)
        sub_stream.cancel()

    assert holder == []
