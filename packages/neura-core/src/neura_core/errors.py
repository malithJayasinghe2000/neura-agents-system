"""One exception hierarchy for the whole system.

Every error that reaches the API boundary is translated into the single wire
shape defined in docs/architecture/api-design.md §3. Keeping that mapping in one
place is what makes the error contract stable enough for clients to branch on.
"""

from __future__ import annotations

from typing import Any


class NeuraError(Exception):
    """Base for every error we raise deliberately.

    ``code`` is a stable, machine-readable string. Clients branch on it, so it is
    part of the public contract and must not change once released. ``message`` is
    human-facing and may be reworded freely.
    """

    code: str = "INTERNAL_ERROR"
    error_type: str = "api_error"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code is not None:
            self.code = code

    def to_dict(self, request_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "type": self.error_type,
        }
        if self.details:
            payload["details"] = self.details
        if request_id:
            payload["request_id"] = request_id
        # No `docs_url` until a page exists to link to (G62, ADR-0056).
        return {"error": payload}


# ── Client errors ────────────────────────────────────────────────────────────


class ValidationError(NeuraError):
    code = "INVALID_REQUEST"
    error_type = "invalid_request"
    http_status = 400


class AuthenticationError(NeuraError):
    code = "AUTHENTICATION_FAILED"
    error_type = "authentication_error"
    http_status = 401


class ForbiddenError(NeuraError):
    """Authenticated, but not allowed. Named to avoid the builtin ``PermissionError``."""

    code = "PERMISSION_DENIED"
    error_type = "permission_error"
    http_status = 403


class AgentNotEnabledError(ForbiddenError):
    """The tenant has not bought this agent.

    Not a bug — an entitlement. See docs/architecture/tenancy-and-packaging.md §3.
    """

    code = "AGENT_NOT_ENABLED"


class NotFoundError(NeuraError):
    code = "NOT_FOUND"
    error_type = "not_found"
    http_status = 404


class ConflictError(NeuraError):
    code = "CONFLICT"
    error_type = "conflict"
    http_status = 409


class IdempotencyConflictError(ConflictError):
    """Same idempotency key, different request body — a client bug worth surfacing."""

    code = "IDEMPOTENCY_KEY_REUSED"


class RateLimitError(NeuraError):
    code = "RATE_LIMITED"
    error_type = "rate_limit_error"
    http_status = 429


class BudgetExceededError(NeuraError):
    """A tenant hit a hard cost ceiling.

    Callers degrade to escalate-only rather than failing the conversation —
    see docs/architecture/llm-abstraction.md §6.
    """

    code = "BUDGET_EXCEEDED"
    error_type = "rate_limit_error"
    http_status = 429


# ── Server / dependency errors ───────────────────────────────────────────────


class ConfigurationError(NeuraError):
    """Raised at boot. A misconfigured deployment must not start."""

    code = "CONFIGURATION_ERROR"


class ServiceUnavailableError(NeuraError):
    code = "SERVICE_UNAVAILABLE"
    error_type = "service_unavailable"
    http_status = 503
