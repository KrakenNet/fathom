"""`serve()` exposes what `Reload` needs, and the proto enum is prefixed."""

from __future__ import annotations

import inspect

from fathom.integrations.grpc_server import FathomServicer, serve
from fathom.proto import fathom_pb2


def test_serve_accepts_every_reload_setting() -> None:
    """Reload needs attestation; through `serve()` it was always not_ready."""
    servicer_params = set(inspect.signature(FathomServicer.__init__).parameters) - {
        "self",
        "default_engine",
    }
    assert servicer_params <= set(inspect.signature(serve).parameters)


def test_change_type_values_carry_the_enum_prefix() -> None:
    """Canonical names are prefixed; the bare ones stay as wire-compatible aliases."""
    assert fathom_pb2.ChangeType.Name(1) == "CHANGE_TYPE_ASSERT"
    assert fathom_pb2.ChangeType.Name(2) == "CHANGE_TYPE_RETRACT"
    assert fathom_pb2.ChangeType.Value("ASSERT") == 1
    assert fathom_pb2.ChangeType.Value("RETRACT") == 2
