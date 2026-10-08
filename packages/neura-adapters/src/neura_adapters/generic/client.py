"""HTTP transport for the Generic Commerce Interface.

Thin on purpose. Its whole job is to turn *someone else's* HTTP behaviour into
our error hierarchy, so every caller above it — adapter, sync engine, agent —
reacts to a merchant's store failing without knowing anything about HTTP
(docs/architecture/commerce-integration.md §3.3).

**No retries here.** Whether to retry is a policy decision that depends on the
caller: a background sync should back off and try again, a live chat turn should
degrade immediately rather than make a customer wait. Each error carries
``retryable``; the caller decides.
"""

from __future__ import annotations

from typing import Any

import httpx

from neura_adapters.generic.wire import SPEC_VERSION
from neura_commerce import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitedError,
    AdapterTimeoutError,
    AdapterUnavailableError,
)
from neura_core import get_logger

log = get_logger(__name__)

#: Long enough for a slow store, short enough that a chat turn stays a chat turn.
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_CONNECT_TIMEOUT_S = 5.0

USER_AGENT = f"neura-generic-client/{SPEC_VERSION}"


class GenericClient:
    """Authenticated JSON GETs against one store's interface."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_s, connect=DEFAULT_CONNECT_TIMEOUT_S),
            transport=transport,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )

    @property
    def has_token(self) -> bool:
        """Whether requests carry a token. Never the token itself."""
        return bool(self._token)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GenericClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ── Raw ──────────────────────────────────────────────────────────────────

    async def request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        token: str | None = None,
        authenticate: bool = True,
    ) -> httpx.Response:
        """One GET, no interpretation of the status code.

        ``authenticate=False`` exists for the conformance tool, which must be
        able to ask a store what it serves to an anonymous caller.
        """
        headers = {}
        bearer = token if token is not None else self._token
        if authenticate and bearer:
            headers["Authorization"] = f"Bearer {bearer}"

        try:
            return await self._client.get(path, params=_clean(params), headers=headers)
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(f"store did not respond in time: GET {path}") from exc
        except httpx.HTTPError as exc:
            raise AdapterUnavailableError(f"could not reach the store: {exc}") from exc

    # ── JSON ─────────────────────────────────────────────────────────────────

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """A successful GET's decoded body. ``None`` for 404."""
        response = await self.request(path, params=params)
        return self._decode(response, path)

    def _decode(self, response: httpx.Response, path: str) -> Any:
        if response.status_code == httpx.codes.NOT_FOUND:
            # Absent is a normal outcome — customers mistype ids constantly.
            return None

        self.raise_for_status(response, path)

        try:
            return response.json()
        except ValueError as exc:
            raise AdapterError(
                f"store returned a non-JSON body for GET {path} "
                f"(content-type {response.headers.get('content-type', 'unset')!r})"
            ) from exc

    @staticmethod
    def raise_for_status(response: httpx.Response, path: str) -> None:
        """Translate a failing status into the shared hierarchy.

        Each branch exists because a caller reacts differently to it; statuses
        handled identically are deliberately not separated.
        """
        status = response.status_code
        if status < 400:
            return

        if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            # Not retryable: repeating a rejected credential is how an
            # integration gets a merchant's firewall to block us.
            raise AdapterAuthError(
                f"store rejected our credentials on GET {path} (HTTP {status}). "
                "Check the token issued for this store."
            )

        if status == httpx.codes.TOO_MANY_REQUESTS:
            raise AdapterRateLimitedError(
                f"store is rate limiting us on GET {path}",
                retry_after_s=_retry_after(response),
            )

        if status >= 500:
            raise AdapterUnavailableError(f"store returned HTTP {status} for GET {path}")

        raise AdapterError(
            f"store returned HTTP {status} for GET {path}",
            details={"body": response.text[:200]},
        )


def _retry_after(response: httpx.Response) -> float | None:
    """``Retry-After`` in seconds, when the store sends a usable one.

    Honoured rather than ignored: our sync must never be the reason a merchant's
    production store falls over.
    """
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        # The HTTP-date form is legal but rare; backoff handles the fallback.
        return None


def _clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop unset parameters.

    Sending ``updated_since=None`` as the literal string "None" is a classic way
    to make a store's filter behave in a way neither side intended.
    """
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None}
