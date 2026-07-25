"""Request-scoped context.

``trace_id``, ``tenant_id`` and ``conversation_id`` must appear on every log line
and every span so that one identifier answers "what did the agent do, and why"
end to end (docs/architecture/overview.md §5).

Context variables are used rather than passing a context object through every
call because these values are genuinely ambient — logging, telemetry and the
audit log all need them without the intervening code caring.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_conversation_id: ContextVar[str | None] = ContextVar("conversation_id", default=None)


def get_trace_id() -> str | None:
    return _trace_id.get()


def get_tenant_id() -> str | None:
    return _tenant_id.get()


def get_conversation_id() -> str | None:
    return _conversation_id.get()


def current_context() -> dict[str, str]:
    """The subset of context that is set, for merging into logs and spans."""
    return {
        key: value
        for key, value in (
            ("trace_id", _trace_id.get()),
            ("tenant_id", _tenant_id.get()),
            ("conversation_id", _conversation_id.get()),
        )
        if value is not None
    }


@contextmanager
def bind_context(
    *,
    trace_id: str | None = None,
    tenant_id: str | None = None,
    conversation_id: str | None = None,
) -> Iterator[None]:
    """Bind context for a block, restoring the previous values on exit.

    Restoring matters under connection pooling and task reuse: a leaked
    ``tenant_id`` would attribute one tenant's activity to another.
    """
    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = []
    for var, value in (
        (_trace_id, trace_id),
        (_tenant_id, tenant_id),
        (_conversation_id, conversation_id),
    ):
        if value is not None:
            tokens.append((var, var.set(value)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
