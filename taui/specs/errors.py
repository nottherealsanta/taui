from __future__ import annotations


class SpecServiceError(RuntimeError):
    """Base class for spec service failures."""

    code = "spec_error"


class SpecNotFoundError(SpecServiceError):
    code = "spec_not_found"


class SpecValidationError(SpecServiceError):
    code = "spec_validation_error"

