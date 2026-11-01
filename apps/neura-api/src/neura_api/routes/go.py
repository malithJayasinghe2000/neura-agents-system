"""A tap on a counted link. ADR-0074 §3 to §5.

    GET /go/{code}    count it, and send the shopper on to the shop's page

**Public, no key, no cookie.** The link is in a shop's Facebook post; whoever
taps it is a shopper we know nothing about, and we keep nothing about them
(§5, R118): one number per link per day. The phone's address is used to answer
and for nothing else, and uvicorn's access line, which would print it, is
dropped for this path by :class:`TapAddressFilter`; ours
(``RequestContextMiddleware``) logs the path and status only.

**Where it sends the shopper comes from the database, never from the request**
(§3): the function ``neura_follow_link()`` returns the product's page from the
shop's own catalogue, with the campaign labels. A code nobody made gets a plain
page, never a guess.

**A robot is sent on and not counted** (§5): link previews and search engines,
by their browser name, which is read here and not stored.

**``302`` and ``no-store``**, so every tap reaches us: a permanent redirect
would be remembered by the phone and skip the count.

Mounted without ``/v1``: in production ``go.fiveneurals.com/<code>`` is this
path (AD13, ``LINKS_BASE_URL``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from neura_agent_core.links import follow, is_robot

router = APIRouter(tags=["links"])

#: Every answer here: stored by no one, and never indexed.
_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}

#: A code nobody made, or a shop that left: said plainly, and nothing else.
_GONE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Link not active</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui,sans-serif;background:#ffffff;color:#0a0a0a;padding:16px;box-sizing:border-box}
p{margin:0;font-size:17px;text-align:center;line-height:1.5}
</style>
</head>
<body><p>This link is no longer active.</p></body>
</html>
"""

PREFIX = "/go/"


@router.get("/go/{code}", include_in_schema=False)
async def go(request: Request, code: str = Path(max_length=64)) -> Response:
    count = not is_robot(request.headers.get("user-agent"))
    async with request.app.state.database.follow_session() as session:
        address = await follow(session, code, count=count)
    if address is None:
        return HTMLResponse(_GONE, status_code=404, headers=_HEADERS)
    return RedirectResponse(address, status_code=302, headers=_HEADERS)


class TapAddressFilter(logging.Filter):
    """Drop uvicorn's access line for a tap: it prints the phone's address.

    uvicorn logs ``'%s - "%s %s HTTP/%s" %d'`` with the client's address first
    and the path third. Every other path keeps its line, unchanged.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        return not (isinstance(args, tuple) and len(args) >= 3 and str(args[2]).startswith(PREFIX))


def quiet_taps() -> None:
    """Fit :class:`TapAddressFilter` once to uvicorn's access logger."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, TapAddressFilter) for f in access.filters):
        access.addFilter(TapAddressFilter())


__all__ = ["PREFIX", "TapAddressFilter", "quiet_taps", "router"]
