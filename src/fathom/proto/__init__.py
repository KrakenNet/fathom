"""Generated protobuf + gRPC stubs for ``protos/fathom.proto``.

Do not edit files in this package by hand — they are regenerated via::

    uv run python -m grpc_tools.protoc \\
        --proto_path=protos \\
        --python_out=src/fathom/proto \\
        --grpc_python_out=src/fathom/proto \\
        --pyi_out=src/fathom/proto \\
        protos/fathom.proto

The one manual edit after regeneration: the generated ``fathom_pb2_grpc.py``
emits ``import fathom_pb2`` (flat layout) which fails inside a package. Rewrite
to ``from . import fathom_pb2`` after each regen.
"""
