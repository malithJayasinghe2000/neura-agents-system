"""Attach a request ID and bind logging context for every request.

The request ID is the trace ID where tracing is on, so the value a customer
quotes in a complaint leads straight to the run that produced their answer
(docs/architecture/api-design.md §3).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from neura_core import bind_context, current_trace_id, get_logger, new_id
from neura_core.ids import REQUEST

log = get_logger(__name__)

_QUIET_PATHS = frozenset({"/v1/health", "/v1/health/ready", "/metrics"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = current_trace_id() or new_id(REQUEST)
        request.state.request_id = request_id

        started = time.perf_counter()
        with bind_context(trace_id=request_id):
            response = await call_next(request)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-Id"] = request_id

        # Health checks fire constantly; logging them buries everything else.
        if request.url.path not in _QUIET_PATHS:
            log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        return response
