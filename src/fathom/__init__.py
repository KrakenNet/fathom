"""Fathom - Deterministic reasoning runtime for AI agents.

``__all__`` is the package's covered public surface: the names this project
promises to keep working, and the exact list `VERSIONING.md` describes. A
symbol reachable by import but absent from here — or from the ``__all__`` of
a submodule — is internal, and may move or change in any release.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from fathom.audit import AuditLog, AuditSink, FileSink, NullSink
from fathom.engine import Engine
from fathom.errors import (
    AttestationError,
    CompilationError,
    EvaluationError,
    EvaluationLimitError,
    FathomError,
    FleetConnectionError,
    FleetError,
    ScopeError,
    ValidationError,
)
from fathom.fleet import FactStore, FleetEngine, InMemoryFactStore
from fathom.models import AssertedFact, AssertSpec, AuditRecord, EvaluationResult

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from fathom.attestation import AttestationService, verify_token
    from fathom.chained_log import ChainedAttestationLog, verify_chain

__version__ = "0.10.0"  # x-release-please-version

#: Names served on first access instead of at import. Both modules import
#: ``jwt`` and ``cryptography``, which ship in the optional ``attestation``
#: extra -- eagerly importing them would make ``import fathom`` fail for every
#: install that did not ask for signing.
_LAZY_EXPORTS: dict[str, str] = {
    "AttestationService": "fathom.attestation",
    "verify_token": "fathom.attestation",
    "ChainedAttestationLog": "fathom.chained_log",
    "verify_chain": "fathom.chained_log",
}

__all__ = [
    "AssertSpec",
    "AssertedFact",
    "AttestationError",
    "AttestationService",
    "AuditLog",
    "AuditRecord",
    "AuditSink",
    "ChainedAttestationLog",
    "CompilationError",
    "Engine",
    "EvaluationError",
    "EvaluationLimitError",
    "EvaluationResult",
    "FactStore",
    "FathomError",
    "FileSink",
    "FleetConnectionError",
    "FleetEngine",
    "FleetError",
    "InMemoryFactStore",
    "NullSink",
    "ScopeError",
    "ValidationError",
    "__version__",
    "verify_chain",
    "verify_token",
]


def __getattr__(name: str) -> Any:
    """Resolve the attestation exports on first access (PEP 562)."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        value = getattr(importlib.import_module(module_name), name)
    except ImportError as exc:  # missing optional dependency, not a typo
        raise ImportError(
            f"fathom.{name} needs the 'attestation' extra: pip install 'fathom-rules[attestation]'"
        ) from exc
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
