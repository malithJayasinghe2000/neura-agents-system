"""Translate exceptions into the one wire error shape.

Defined in docs/architecture/api-design.md §3. Every failure — ours, FastAPI's,
or unexpected — leaves through here, so clients only ever parse one structure.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from neura_core import NeuraError, current_trace_id, get_logger

log = get_logger(__name__)


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    return rid or current_trace_id()


def _retry_headers(exc: NeuraError) -> dict[str, str] | None:
    retry_after = exc.details.get("retry_after")
    return {"Retry-After": str(retry_after)} if retry_after else None


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NeuraError)
    async def _neura(request: Request, exc: NeuraError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_dict(_request_id(request)),
            # `Retry-After` has to survive the exception path, or a 429 raised
            # from deep in a handler arrives without the one header a client
            # needs in order to back off correctly (api-design.md §6). The
            # limiter puts the value in `details`; this is what gets it onto the
            # response.
            headers=_retry_headers(exc),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Request validation failed.",
                    "type": "invalid_request",
                    # A check of our own (a validator) carries its Python
                    # exception, and can carry the date it refused. As they
                    # are, neither is JSON, and this handler itself failed as a
                    # 500 for one wrong field (G64): the exception becomes its
                    # message.
                    "details": {
                        "errors": jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
                    },
                    "request_id": _request_id(request),
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": str(exc.detail),
                    "type": "invalid_request" if exc.status_code < 500 else "api_error",
                    "request_id": _request_id(request),
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the detail; return none of it. An unexpected exception message can
        # contain internal structure, and occasionally customer data.
        log.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred.",
                    "type": "api_error",
                    "request_id": _request_id(request),
                }
            },
        )
