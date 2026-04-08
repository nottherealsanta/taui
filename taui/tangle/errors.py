from __future__ import annotations


class TangleServiceError(RuntimeError):
    """Base class for tangle service failures."""

    code = "tangle_error"


class TangleNotFoundError(TangleServiceError):
    code = "tangle_not_found"


class TangleValidationError(TangleServiceError):
    code = "tangle_validation_error"


# Backward-compat aliases for incremental migration
SpecServiceError = TangleServiceError
SpecNotFoundError = TangleNotFoundError
SpecValidationError = TangleValidationError
