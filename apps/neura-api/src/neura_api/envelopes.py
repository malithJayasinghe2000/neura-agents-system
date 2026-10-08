"""The one success envelope, and the one pagination style.

api-design.md §3 and §5. There is a single shape for a successful response and a
single shape for a page of them, and the reason is in principle 2: *predictable*.
An integrator who has parsed one endpoint has parsed all of them, and a client
library can be generated rather than hand-written per route.

The error envelope lives in ``errors.py``, next to the handlers that emit it.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any

from neura_core import ValidationError, current_trace_id


def meta(request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """The ``meta`` block every response carries.

    ``request_id`` is the OpenTelemetry trace id where tracing is on, so a
    customer quoting it leads straight to the agent run that produced their
    answer (api-design.md §3).
    """
    return {
        "request_id": request_id or current_trace_id() or "",
        "timestamp": datetime.now(UTC).isoformat(),
        **extra,
    }


def envelope(data: Any, *, request_id: str | None = None, **extra_meta: Any) -> dict[str, Any]:
    """``{"data": ..., "meta": {...}}`` — and never anything else."""
    return {"data": data, "meta": meta(request_id, **extra_meta)}


def page(
    items: list[Any],
    *,
    next_cursor: str | None,
    request_id: str | None = None,
    **extra_meta: Any,
) -> dict[str, Any]:
    """A cursor-paginated page.

    ``has_more`` is derived from the cursor rather than passed separately: two
    fields that must agree are two fields that will eventually disagree.
    ``extra_meta`` is for what a particular list can also say about itself — a
    total, a position — and never overrides those two.
    """
    return {
        "data": items,
        "meta": meta(
            request_id, **extra_meta, next_cursor=next_cursor, has_more=next_cursor is not None
        ),
    }


def encode_cursor(payload: dict[str, Any]) -> str:
    """Opaque, and meant to stay that way (api-design.md §5).

    URL-safe base64 over JSON. It is **not signed**, and that is a deliberate
    limit rather than an oversight: a cursor here names a position within one
    tenant's rows, and the query it feeds is already scoped by Row-Level
    Security, so a forged cursor can move a caller around inside data they may
    already read and nowhere else. Signing would add a key rotation problem to
    defend against a caller reordering their own list.

    What it does buy is that clients cannot *parse* it, so the fields inside it
    can change without breaking anyone — which is the actual reason to encode.
    """
    return base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    """Decode a cursor, or refuse it clearly.

    A malformed cursor is a ``400``, not a silent restart from the beginning.
    Silently ignoring it makes a paginating client loop over page one forever
    while looking like it is making progress.
    """
    if not cursor:
        return None
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, binascii.Error) as exc:
        raise ValidationError(
            "That cursor could not be read. Pass back the `next_cursor` from the "
            "previous page exactly as it was returned.",
            details={"field": "cursor"},
        ) from exc
    if not isinstance(decoded, dict):
        raise ValidationError("That cursor could not be read.", details={"field": "cursor"})
    return decoded


__all__ = ["decode_cursor", "encode_cursor", "envelope", "meta", "page"]
