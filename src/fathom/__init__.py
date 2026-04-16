"""Fathom - Deterministic reasoning runtime for AI agents."""

from fathom.engine import Engine
from fathom.errors import CompilationError, EvaluationError, ValidationError
from fathom.models import AssertedFact, AssertSpec, EvaluationResult

__version__ = "0.3.0"

__all__ = [
    "__version__",
    "Engine",
    "CompilationError",
    "EvaluationError",
    "ValidationError",
    "AssertSpec",
    "AssertedFact",
    "EvaluationResult",
]
