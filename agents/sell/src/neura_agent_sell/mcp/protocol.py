"""JSON-RPC 2.0 framing. The wire format and nothing else.

Separated from `server.py` on purpose: framing is a published standard with
fixed error codes, and the methods are ours. Mixing them makes it impossible to
tell, reading a failure, whether we broke the protocol or the logic.

**Error codes are the standard ones**, and using our own numbers would be a
small act of vandalism — an MCP client's error handling is written against the
JSON-RPC table, and a bespoke code arrives as "unknown error" in someone else's
system where a real message could have arrived instead.
"""

from __future__ import annotations

from typing import Any

# JSON-RPC 2.0, §5.1. Do not invent values in this range.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

VERSION = "2.0"


class JsonRpcError(Exception):
    """An error that should reach the caller as a JSON-RPC error object.

    Carries its own code, so a handler raises the right protocol-level failure
    at the point it discovers it rather than returning a sentinel that some
    outer layer has to interpret.
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def result(request_id: Any, payload: Any) -> dict[str, Any]:
    """A successful response."""
    return {"jsonrpc": VERSION, "id": request_id, "result": payload}


def error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    """A failed response.

    ``data`` is omitted when empty rather than sent as ``null``: a client that
    branches on its presence should not have to distinguish "absent" from
    "present and null".
    """
    body: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return {"jsonrpc": VERSION, "id": request_id, "error": body}


def parse_error(request_id: Any = None) -> dict[str, Any]:
    return error(request_id, PARSE_ERROR, "Invalid JSON.")


def invalid_request(request_id: Any = None, detail: str = "") -> dict[str, Any]:
    return error(request_id, INVALID_REQUEST, detail or "Not a valid JSON-RPC 2.0 request.")


def method_not_found(request_id: Any, method: str) -> dict[str, Any]:
    return error(request_id, METHOD_NOT_FOUND, f"Unknown method: {method}")


def invalid_params(request_id: Any, detail: str) -> dict[str, Any]:
    return error(request_id, INVALID_PARAMS, detail)


def is_notification(message: dict[str, Any]) -> bool:
    """A request with no ``id`` expects no response, and must not get one.

    Answering a notification is a protocol violation that a lenient client will
    tolerate and a strict one will not — which is the worst kind, because it
    works in testing.
    """
    return "id" not in message


__all__ = [
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "VERSION",
    "JsonRpcError",
    "error",
    "invalid_params",
    "invalid_request",
    "is_notification",
    "method_not_found",
    "parse_error",
    "result",
]
