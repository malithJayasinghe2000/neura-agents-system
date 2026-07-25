"""Structured logging with a redaction filter.

Two non-negotiables from docs/architecture/security-model.md:

* every line carries ``trace_id`` / ``tenant_id`` / ``conversation_id`` when known;
* credentials, PII and prompt content never reach the logs.

The redaction processor is a safety net, not permission to be careless — code
should not pass secrets to the logger in the first place.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

from neura_core.context import current_context

# Keys whose values are replaced wholesale, whatever they contain.
_REDACT_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "kek",
        "dek",
        "credential",
        "credentials",
        "secret_key",
        "private_key",
        "prompt",
        "completion",
        "message",
        "content",
        "transcript",
        "email",
        "phone",
        "address",
        "card",
        "card_number",
    }
)

_REDACTED = "[REDACTED]"

# Belt-and-braces for secrets embedded in free text (e.g. an exception message).
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfn_(sk|pk)_[A-Za-z0-9_\-]{8,}"), "fn_***"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD]"),
)


def _scrub_text(value: str) -> str:
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _redact(value: Any, key: str | None = None) -> Any:
    if key is not None and key.lower() in _REDACT_KEYS:
        return _REDACTED
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact(v) for v in value)
    return value


def redaction_processor(
    _logger: object, _name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    return {key: _redact(value, key) for key, value in event_dict.items()}


def context_processor(
    _logger: object, _name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Merge the ambient request context into every line."""
    event_dict.update(current_context())
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog. Call once, at startup.

    ``json_output=False`` gives a human-readable console renderer for local work.
    """
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            context_processor,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redaction_processor,  # last, so nothing added above escapes it
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
