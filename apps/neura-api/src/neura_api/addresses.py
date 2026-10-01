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

Checked before **every** call NEURA makes to a typed address (the check, and
*Connect*), not once when it is typed: a name can be pointed somewhere else
later. Redirects are never followed (``GenericClient``), so an allowed address
cannot hand the request on to a forbidden one.

**Known limit (ADR-0052 §3):** resolving a name here and connecting to it
afterwards resolves it twice, so a name that changes its answer in between (DNS
rebinding) could still slip through. Closing it means connecting to the exact
address that was checked, which the HTTP client cannot do simply today; it is
recorded as open rather than hidden.

The sentences in the errors below are shown to the shop owner as they are.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from neura_core import ValidationError

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


async def _resolve(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise ValidationError(
            "We couldn't find that address. Check it for typing mistakes.",
            code=ADDRESS_NOT_FOUND,
        ) from exc
    found = [ipaddress.ip_address(info[4][0]) for info in infos]
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
