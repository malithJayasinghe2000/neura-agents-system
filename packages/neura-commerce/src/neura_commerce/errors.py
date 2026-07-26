"""Adapter errors.

Adapters translate whatever their platform throws into this hierarchy, so retry,
degradation and escalation logic is written **once** rather than per platform
(docs/architecture/commerce-integration.md §3.3).

Each class exists because a caller reacts differently to it. If two errors would
be handled identically, they should not be separate classes.
"""

from __future__ import annotations

from neura_core import NeuraError


class AdapterError(NeuraError):
    code = "ADAPTER_ERROR"
    error_type = "api_error"
    http_status = 502

    #: Whether retrying the same call could plausibly succeed.
    retryable: bool = False


class AdapterUnavailableError(AdapterError):
    """The store is unreachable. Retry with backoff, then degrade."""

    code = "ADAPTER_UNAVAILABLE"
    http_status = 503
    retryable = True


class AdapterTimeoutError(AdapterError):
    code = "ADAPTER_TIMEOUT"
    http_status = 504
    retryable = True


class AdapterAuthError(AdapterError):
    """Credentials rejected.

    Deliberately **not** retryable: hammering a store with bad credentials can
    get us rate-limited or blocked. The merchant is alerted instead.
    """

    code = "ADAPTER_AUTH_FAILED"
    http_status = 502
    retryable = False


class AdapterRateLimitedError(AdapterError):
    """The store is rate limiting us.

    We must never take down a merchant's production store with our own sync, so
    ``retry_after_s`` is honoured rather than ignored.
    """

    code = "ADAPTER_RATE_LIMITED"
    error_type = "rate_limit_error"
    http_status = 429
    retryable = True

    def __init__(
        self, message: str, *, retry_after_s: float | None = None, **kwargs: object
    ) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.retry_after_s = retry_after_s


class EntityNotFoundError(AdapterError):
    """The entity does not exist.

    A normal outcome, not a fault: a customer mistyping an order number is
    routine. Adapters generally return ``None`` instead; this exists for callers
    that need a raised error.
    """

    code = "ENTITY_NOT_FOUND"
    error_type = "not_found"
    http_status = 404
    retryable = False


class AdapterMappingError(AdapterError):
    """Platform data that could not be turned into a canonical model.

    Surfaced in store health rather than swallowed. Silent mapping failures show
    up much later as an agent that mysteriously cannot see certain products.
    """

    code = "ADAPTER_MAPPING_FAILED"
    http_status = 502
    retryable = False


class CapabilityNotSupportedError(AdapterError):
    """An operation the platform does not support was attempted.

    Should be unreachable in normal use: tools are filtered by capability before
    the model ever sees them. Reaching this means the filtering was bypassed, so
    it is a bug rather than a user error.
    """

    code = "CAPABILITY_NOT_SUPPORTED"
    error_type = "invalid_request"
    http_status = 400
    retryable = False
