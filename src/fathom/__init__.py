"""Fathom - Deterministic reasoning runtime for AI agents."""

from fathom.engine import Engine
from fathom.errors import (
    CompilationError,
    EvaluationError,
    EvaluationLimitError,
    ScopeError,
    ValidationError,
)
from fathom.models import AssertedFact, AssertSpec, EvaluationResult

__version__ = "0.8.0"  # x-release-please-version

__all__ = [
    "__version__",
    "Engine",
    "CompilationError",
    "EvaluationError",
    "EvaluationLimitError",
    "ScopeError",
    "ValidationError",
    "AssertSpec",
    "AssertedFact",
    "EvaluationResult",
]
