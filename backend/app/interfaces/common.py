"""Shared types and helpers for the HTTP transport layer.

This module is the home for the typed error hierarchy and any
cross-router utilities. Keeping the error class definition here lets
future router modules (see `interfaces/routers/`) raise the same
typed errors without a circular import on `api.py`.

The transport layer imports the application layer; never the other
way. A service that knows the HTTP shape leaks (spec rule).
"""

from __future__ import annotations


class APIError(Exception):
    """Base API error with status_code and message."""

    def __init__(self, status_code: int, message: str, detail: str | None = None):
        self.status_code = status_code
        self.message = message
        self.detail = detail or message


class NotFoundError(APIError):
    def __init__(self, resource: str, identifier: str):
        super().__init__(404, f"{resource} '{identifier}' not found")


class ValidationError(APIError):
    def __init__(self, message: str, field: str | None = None):
        detail = f"Validation error: {message}" if field else message
        super().__init__(400, message, detail)


class ConflictError(APIError):
    def __init__(self, message: str):
        super().__init__(409, message)


class RateLimitError(APIError):
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(429, message)
        self.retry_after = retry_after


__all__ = [  # noqa: RUF022
    "APIError",
    "NotFoundError",
    "ValidationError",
    "ConflictError",
    "RateLimitError",
]
