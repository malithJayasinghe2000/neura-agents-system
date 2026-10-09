"""CORS decided by the presented key, not by a deployment-wide list.

[security-model.md §13](../../../../../docs/architecture/security-model.md) asks
for "strict CORS with per-tenant widget origin allowlists". Until 1.16 the
allowlist was ``WIDGET_ALLOWED_ORIGINS`` — one list for the whole process, so
onboarding a second merchant meant an environment change and a restart, and any
origin on the list passed CORS while holding *any* tenant's key.

**Resolving the tenant at preflight is not possible, and the reason is
structural rather than an oversight.** A CORS preflight is an ``OPTIONS``
request carrying no ``Authorization`` header, so there is no key to resolve a
tenant from; and the union of every tenant's origins cannot be read out of
PostgreSQL either, because ``api_keys`` is under forced Row-Level Security and
no transaction can enumerate tenants (open question **P7**, ADR-0008). The ways
around that are a ``BYPASSRLS`` role, which P7 argues against, or an index kept
outside PostgreSQL — which for the webhook outbox costs a delayed schedule and
here would cost a **total widget outage** every time the index was lost.

So the check goes where the credential actually is (ADR-0019 §3):

* **A preflight is answered for any syntactically valid origin.** Approving a
  preflight authorises a browser to *send* a request. It authorises nothing to
  be read, and the request it permits is still refused by the key's own origin
  lock (ADR-0014 §3) before a single model call.
* **A real response carries ``Access-Control-Allow-Origin`` only when the
  presented key permitted that origin.** No authenticated caller, no header — so
  a cross-origin request from an origin a key does not allow is unreadable in
  the browser, and its refusal is not an oracle for *"is this key valid
  somewhere else?"*.

This is the honest reading of what CORS is doing here. ``allow_credentials`` is
false and the credential is a bearer token, so there are no ambient credentials
for a hostile page to ride on: **CORS is defence in depth and the key's origin
lock is the access control.** A change that weakens either one silently
re-weights this decision.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from neura_core import get_settings

#: Everything the browser is allowed to send us. Deliberately not a wildcard:
#: an unlisted header is a request a merchant's integration should fail on here
#: rather than discover in production.
ALLOWED_HEADERS = "Authorization, Content-Type, Idempotency-Key"
ALLOWED_METHODS = "GET, POST, DELETE, OPTIONS"

#: Read by a browser client, so the widget can back off on the subject that is
#: actually binding it (ADR-0017) and replay under its own idempotency key.
EXPOSED_HEADERS = (
    "X-Request-Id, X-RateLimit-Limit, X-RateLimit-Remaining, "
    "X-RateLimit-Reset, Retry-After, Idempotency-Replayed"
)

#: How long a browser may cache a preflight. Ten minutes: long enough that a
#: chatty widget is not preflighting every turn, short enough that revoking a
#: key is not waiting out a day-long cache. The preflight grants nothing on its
#: own, so this is a performance number and not a security one.
PREFLIGHT_MAX_AGE = "600"


def is_valid_origin(origin: str | None) -> bool:
    """A parseable ``scheme://host`` and nothing else.

    ``null`` — what a sandboxed iframe or a ``file://`` page sends — is refused
    rather than reflected. Reflecting it would name an origin that every such
    page shares, which is the one string that cannot identify anybody.
    """
    if not origin or origin == "null":
        return False
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    # An origin is scheme, host and port. Anything else — a path, a query, a
    # fragment — means this is a URL somebody pasted, not an origin a browser
    # sent, and echoing it back would put attacker-chosen text in a header.
    return not (parsed.path or parsed.query or parsed.fragment)


class TenantCorsMiddleware(BaseHTTPMiddleware):
    """Per-tenant CORS, resolved from the key the request actually presented."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")

        if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
            return self._preflight(origin)

        response = await call_next(request)
        if is_valid_origin(origin) and self._permits(request, origin):
            response.headers["Access-Control-Allow-Origin"] = origin or ""
            response.headers["Access-Control-Expose-Headers"] = EXPOSED_HEADERS
            # The permitted set is per key, so a shared cache must not serve one
            # merchant's allowed response to another merchant's origin.
            response.headers["Vary"] = "Origin"
        return response

    def _preflight(self, origin: str | None) -> Response:
        """Answer a preflight without knowing who is asking.

        A refusal here would be a refusal to *ask*, and the question is answered
        by the origin lock a few milliseconds later. What this must not do is
        promise anything a real request will not honour, which is why the
        allowed headers and methods are the same constants either way.
        """
        if not is_valid_origin(origin):
            return Response(status_code=400)
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin or "",
                "Access-Control-Allow-Methods": ALLOWED_METHODS,
                "Access-Control-Allow-Headers": ALLOWED_HEADERS,
                "Access-Control-Max-Age": PREFLIGHT_MAX_AGE,
                "Vary": "Origin",
            },
        )

    def _permits(self, request: Request, origin: str | None) -> bool:
        """Did the credential behind this request allow this origin?

        ``request.state.caller`` is set by ``authenticate_request`` and is
        therefore present only when authentication *succeeded* — which for a
        public key already means the origin passed ``permits_origin``
        (ADR-0014 §3). So the presence of a caller is the answer for every keyed
        request, and there is no second implementation of the rule to drift from
        the first.

        Endpoints with no key to consult — the widget asset, health — fall back
        to the platform list, which is what that setting is now for.

        **One kind of refusal is readable: a secret sent from a web page**, a
        secret key (G55), the shop token (G57) or the customer sign-in secret
        (ADR-0057). It is decided from the shape
        of the string the page itself sent, before any lookup, so reading it
        tells the page nothing it did not already hold, and it is no oracle for
        whether the key exists. Unreadable, the chat box could only show the
        browser's *"Failed to fetch"*, and the developer would never learn that
        the wrong secret is in the page.
        """
        caller = getattr(request.state, "caller", None)
        if caller is not None:
            return True
        if getattr(request.state, "secret_key_in_page", False):
            return True
        return origin in get_settings().widget_origins


__all__ = [
    "ALLOWED_HEADERS",
    "ALLOWED_METHODS",
    "EXPOSED_HEADERS",
    "TenantCorsMiddleware",
    "is_valid_origin",
]
