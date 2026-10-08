"""Which shop addresses NEURA may call. ADR-0052 §3, finding G47.

Once a person can type the address of a shop's bridge, NEURA's own server calls
whatever was typed. Without a rule, anyone with a dashboard account could make
our server call **our own internal addresses** (a cloud provider's metadata
service, a database, an admin port) and read what comes back in the check's
result. That is server-side request forgery.

**In production** an address must be ``https://`` and its host must resolve only
to public internet addresses. **Outside production** (``NEURA_ENV`` is not
``production``) private addresses and ``http://`` are allowed, because the test
shops run on the developer's own machine. There is no setting that turns the
rule off in production.

Two layers. ``check_shop_address`` runs when an address is given (the check,
*Connect*, ``POST /v1/stores``) and says in plain words why one is refused.
**``outbound_transport`` is the rule itself**: in production every call NEURA
makes to a shop, and every webhook it sends, connects through it. It looks the
name up **once**, refuses it unless every answer is public, and connects to
exactly the address it checked, so a name that changes its answer between the
check and the connection (DNS rebinding, ADR-0052 §3's known limit, G47) or
the next day (G78) never reaches one of ours. Redirects are never followed
(``GenericClient``, the webhook client), so an allowed address cannot hand the
request on to a forbidden one, and no proxy is used: a proxy would look the
name up again itself.

The sentences in the errors below are shown to the shop owner as they are.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit

import anyio
import httpcore
import httpx

from neura_core import ValidationError, get_logger

log = get_logger(__name__)

ADDRESS_INVALID = "ADDRESS_INVALID"
ADDRESS_NOT_HTTPS = "ADDRESS_NOT_HTTPS"
ADDRESS_NOT_FOUND = "ADDRESS_NOT_FOUND"
ADDRESS_NOT_PUBLIC = "ADDRESS_NOT_PUBLIC"

#: Long enough for any real address, short enough that nobody pastes a page.
MAX_ADDRESS_LENGTH = 2048


async def check_shop_address(address: str, *, production: bool) -> str:
    """The address, tidied, if NEURA may call it. Raises ``ValidationError`` if not."""
    text = address.strip()
    parts = urlsplit(text)
    if (
        not text
        or len(text) > MAX_ADDRESS_LENGTH
        or parts.scheme not in ("https", "http")
        or not parts.hostname
    ):
        raise ValidationError(
            "That isn't a web address. It should look like https://yourshop.example/neura/v1",
            code=ADDRESS_INVALID,
        )
    if parts.username or parts.password:
        raise ValidationError(
            "The address must not contain a user name or a password.", code=ADDRESS_INVALID
        )

    if production:
        if parts.scheme != "https":
            raise ValidationError(
                "The address must start with https://, so your shop token travels encrypted.",
                code=ADDRESS_NOT_HTTPS,
            )
        for ip in await _resolve(parts.hostname, parts.port or 443):
            if not _is_public(ip):
                raise ValidationError(
                    "This address isn't on the public internet, so NEURA won't call it.",
                    code=ADDRESS_NOT_PUBLIC,
                )

    return text.rstrip("/")


async def check_webhook_address(address: str, *, production: bool) -> None:
    """Refuse a webhook address that is not on the public internet (G78).

    Only the host: whether it must be ``https://`` is the webhook repository's
    rule, with its own reason. Delivery is guarded again by ``outbound_transport``.
    """
    parts = urlsplit(address.strip())
    if not parts.hostname:
        raise ValidationError(
            "That isn't a web address. It should look like https://yourshop.example/hooks",
            code=ADDRESS_INVALID,
        )
    if production:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if not all(_is_public(ip) for ip in await _resolve(parts.hostname, port)):
            raise ValidationError(
                "This address isn't on the public internet, so NEURA won't call it.",
                code=ADDRESS_NOT_PUBLIC,
            )


def outbound_transport(*, production: bool) -> httpx.AsyncBaseTransport | None:
    """How NEURA's server reaches an address a shop gave it: its bridge, its webhooks.

    A new one per client: the client closes it. ``None`` outside production, where
    the test shops run on the developer's own machine (ADR-0052 §3).
    """
    return _PublicOnlyTransport() if production else None


def adapter_transport(*, production: bool) -> dict[str, httpx.AsyncBaseTransport]:
    """``outbound_transport`` as an adapter's settings: ``{"transport": …}`` in
    production, nothing (so the adapter's default) elsewhere. An adapter that
    cannot take a transport fails in production rather than connecting unguarded."""
    transport = outbound_transport(production=production)
    return {} if transport is None else {"transport": transport}


class _PublicOnlyTransport(httpx.AsyncHTTPTransport):
    """httpx's own transport, with a connection pool that dials only checked addresses.

    httpx takes no network backend of its own, so the pool it built is replaced
    by one with ``_PublicOnlyNetwork``. If httpx stops building a pool this way,
    this fails at once rather than connecting unguarded.
    """

    def __init__(self) -> None:
        super().__init__(trust_env=False)
        if not isinstance(getattr(self, "_pool", None), httpcore.AsyncConnectionPool):
            raise RuntimeError("httpx no longer builds its pool as expected; refusing to connect")
        limits = httpx.Limits()
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            network_backend=_PublicOnlyNetwork(),
        )


class _PublicOnlyNetwork(httpcore.AsyncNetworkBackend):
    """Looks the name up once, refuses it unless every answer is public, and
    connects to an address from that same answer. TLS still checks the
    certificate against the name (httpcore passes it as the server name)."""

    def __init__(self) -> None:
        self._network = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            with anyio.fail_after(timeout):
                found = await _addresses_of(host, port)
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout(f"looking up {host} took too long") from exc
        except (OSError, UnicodeError) as exc:
            raise httpcore.ConnectError(f"{host} could not be found") from exc
        if not found:
            raise httpcore.ConnectError(f"{host} could not be found")
        if not all(_is_public(ip) for ip in found):
            # A shop's own name answering one of ours is a mistake or an attack;
            # either way somebody should see it. The name only, never a token.
            log.warning("outbound_address_refused", host=host)
            raise httpcore.ConnectError(f"{host} is not on the public internet")

        failed: httpcore.ConnectError | None = None
        for ip in found:
            try:
                return await self._network.connect_tcp(
                    str(ip),
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.ConnectError as exc:
                failed = exc
        raise failed or httpcore.ConnectError(f"could not connect to {host}")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("a shop is never reached through a local socket")

    async def sleep(self, seconds: float) -> None:
        await self._network.sleep(seconds)


async def _addresses_of(
    host: str, port: int
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address a name answers, in its order, once each."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(ipaddress.ip_address(info[4][0]) for info in infos))


async def _resolve(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        found = await _addresses_of(host, port)
    except (socket.gaierror, UnicodeError) as exc:
        raise ValidationError(
            "We couldn't find that address. Check it for typing mistakes.",
            code=ADDRESS_NOT_FOUND,
        ) from exc
    if not found:
        raise ValidationError(
            "We couldn't find that address. Check it for typing mistakes.",
            code=ADDRESS_NOT_FOUND,
        )
    return found


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Reachable on the public internet, and nothing else.

    ``is_global`` already excludes loopback, private, link-local, shared
    (100.64.0.0/10), reserved and documentation ranges. Multicast is excluded on
    its own, and an IPv4 address dressed as IPv6 (``::ffff:127.0.0.1``) is judged
    as the IPv4 address it is.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast
