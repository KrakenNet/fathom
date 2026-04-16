"""Fathom exception hierarchy.

All Fathom-specific exceptions inherit from FathomError.
Each exception carries structured context fields for programmatic handling.
"""

from __future__ import annotations

from typing import Any


class FathomError(Exception):
    """Base exception for all Fathom errors."""

    pass


class CompilationError(FathomError):
    """Raised when YAML→CLIPS compilation fails."""

    def __init__(
        self,
        message: str,
        file: str | None = None,
        construct: str | None = None,
        detail: str | None = None,
    ):
        self.file = file
        self.construct = construct  # e.g., "template:agent", "rule:deny-access"
        self.detail = detail
        super().__init__(message)


class ValidationError(FathomError):
    """Raised when fact assertion fails validation."""

    def __init__(
        self,
        message: str,
        template: str | None = None,
        slot: str | None = None,
        value: Any = None,
        expected: str | None = None,
    ):
        self.template = template
        self.slot = slot
        self.value = value
        self.expected = expected
        super().__init__(message)


class EvaluationError(FathomError):
    """Raised when evaluation encounters a runtime error."""

    def __init__(
        self,
        message: str,
        rule: str | None = None,
        module: str | None = None,
    ):
        self.rule = rule
        self.module = module
        super().__init__(message)


class AttestationError(FathomError):
    """Raised when attestation operations fail (key generation, signing, verification)."""

    def __init__(
        self,
        message: str,
        operation: str | None = None,
    ):
        self.operation = operation  # e.g., "sign", "verify", "generate_keypair"
        super().__init__(message)


class FleetError(FathomError):
    """Base exception for fleet-related errors (shared working memory, sync)."""

    def __init__(
        self,
        message: str,
        session_id: str | None = None,
    ):
        self.session_id = session_id
        super().__init__(message)


class FleetConnectionError(FleetError):
    """Raised when a fleet backend connection fails (Redis, Postgres, etc.)."""

    def __init__(
        self,
        message: str,
        session_id: str | None = None,
        backend: str | None = None,
    ):
        self.backend = backend  # e.g., "redis", "postgres"
        super().__init__(message, session_id=session_id)


class ScopeError(RuntimeError):
    """Raised when an operation is attempted at the wrong scope.

    E.g. asserting a fleet-scoped fact through ``Engine.assert_fact`` instead
    of ``FleetEngine.assert_fact``.
    """
