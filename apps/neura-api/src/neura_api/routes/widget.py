"""Widget hosting — the line that makes overview.md §4 true.

[overview.md §4](../../../../../docs/architecture/overview.md) has listed
"widget hosting" among the API's responsibilities since it was written, and
nothing implemented it. ADR-0019 §2 decides it is served from our own origin
rather than pasted into a merchant's theme or pushed to a CDN, so that a fix
reaches every merchant on the next cache expiry instead of on the next re-paste.

    GET /v1/widget/widget.js     the element itself
    GET /v1/widget/pairs.js      ADR-0040's paired-suggestion block
    GET /v1/widget/snippet       the lines a merchant pastes, and the developer MCP's address
    GET /v1/widget/demo          a local harness, non-production only

**No authentication on any of them, on purpose.** The asset is public code — it
is served to every shopper on every merchant's site, and a `<script src>` is not
a CORS-governed request in the first place. Nothing here reads a tenant, so
there is nothing here to authorise. The credential appears only when the widget
*calls* the API, where the key's own origin lock decides (ADR-0014 §3).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from neura_api.developer_mcp import ENDPOINT as DEVELOPER_MCP_ENDPOINT
from neura_api.developer_mcp import MOUNT as DEVELOPER_MCP_MOUNT
from neura_api.widget import DEMO_HTML, PAIRS_JS, WIDGET_JS
from neura_core import NotFoundError, get_settings

router = APIRouter(prefix="/widget", tags=["widget"])

#: Five minutes. The merchant cannot re-paste to pick up a fix, so a long cache
#: is a bug that stays deployed; a short one costs a conditional request.
CACHE_CONTROL = "public, max-age=300"

SNIPPET = """<!-- NEURA chat -->
<script src="{base}/v1/widget/widget.js" async
        data-neura-key="{key}"></script>
"""

#: ADR-0040's block, and it takes one thing the chat widget does not: the ids of
#: the products the page is displaying. The merchant's template fills them in —
#: we are never told what they are for, and the attribute is named for what it
#: holds rather than for a cart, because every platform has a cart and every one
#: of them exposes it differently.
PAIRS_SNIPPET = """<!-- NEURA paired suggestions -->
<script src="{base}/v1/widget/pairs.js" async></script>
<neura-pairs data-neura-key="{key}"
             data-products="PRODUCT_IDS_HERE"></neura-pairs>
"""


@router.get(
    "/widget.js",
    summary="The embeddable chat widget",
    response_class=Response,
    responses={200: {"content": {"application/javascript": {}}}},
)
async def widget_js() -> Response:
    return Response(
        content=WIDGET_JS,
        media_type="application/javascript; charset=utf-8",
        headers={
            "Cache-Control": CACHE_CONTROL,
            # Served from the same origin as the API, so a browser that sniffs
            # this as something else would be executing it in our context.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/pairs.js",
    summary="The paired-suggestion block (ADR-0040)",
    response_class=Response,
    responses={200: {"content": {"application/javascript": {}}}},
)
async def pairs_js() -> Response:
    """A second public asset, served exactly as the first.

    **A separate file rather than more of `widget.js`**, and the reason is
    ADR-0040 §1: this is a different surface with a different consumer. A
    merchant who wants suggestions on a cart page and no chat box should not be
    made to ship a chat widget, and a shopper on that page should not download
    one.
    """
    return Response(
        content=PAIRS_JS,
        media_type="application/javascript; charset=utf-8",
        headers={
            "Cache-Control": CACHE_CONTROL,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/snippet", summary="The embed snippet for one public key")
async def snippet(
    key: Annotated[str, Query(description="The tenant's fn_pk_ key", max_length=128)] = "",
    base: Annotated[str, Query(description="Public base URL of this API", max_length=256)] = "",
) -> dict[str, str]:
    """What a merchant pastes into their theme.

    The key is **echoed, never validated**. Validating it would mean reading a
    credential on an unauthenticated endpoint, and telling an anonymous caller
    whether a key exists is an oracle for a value that is public but not
    guessable. A wrong key fails at the first turn, where the failure names
    itself.
    """
    settings = get_settings()
    origin = (base or settings.public_base_url).rstrip("/")
    shown_key = key or "fn_pk_live_…"
    return {
        "snippet": SNIPPET.format(base=origin, key=shown_key),
        "widget_url": f"{origin}/v1/widget/widget.js",
        # Both surfaces, because a merchant who wants one and not the other
        # should be able to see that they are separate pastes rather than
        # discovering it from a support thread. Additive: the two original
        # fields keep their names and their meaning.
        "pairs_snippet": PAIRS_SNIPPET.format(base=origin, key=shown_key),
        "pairs_url": f"{origin}/v1/widget/pairs.js",
        # What a developer's AI coding tool is given (ADR-0053 §6), made from
        # the same public address, so Help never builds an address of its own.
        "developer_mcp_url": f"{origin}{DEVELOPER_MCP_MOUNT}{DEVELOPER_MCP_ENDPOINT}",
    }


@router.get(
    "/demo",
    summary="A local harness for driving the widget (non-production only)",
    response_class=Response,
    include_in_schema=False,
)
async def demo(
    key: Annotated[str, Query(max_length=128)] = "",
    agent: Annotated[str, Query(max_length=32)] = "",
) -> Response:
    """The widget on a page, under the CSP a merchant would be asked to run.

    **404 in production.** It is a development tool, and an HTML page on the API
    origin that embeds a caller-supplied key is not something to leave reachable
    on a production host just because it is harmless today.
    """
    if get_settings().is_production:
        raise NotFoundError("Not found.")
    # The key lands in an attribute value, so anything that could close the
    # attribute is stripped rather than escaped — the alternative is trusting an
    # escaping function on the one page whose whole job is to load a script.
    safe_key = "".join(c for c in key if c.isalnum() or c in "_-")
    # Same treatment, same reason: it lands in an attribute value, and an agent
    # key is `[a-z]` in every manifest this will ever load.
    #
    # **Empty means dispatch**, and both halves of that had to change together.
    # This defaulted to `"care"` — and fell back to `"care"` when the parameter
    # was junk — so the demo page wrote `data-neura-agent="care"` into every
    # page it served. `widget.js` stopped choosing an agent on 2026-09-01
    # ([ADR-0031] §1); this did not, so the one page anybody actually opens in a
    # browser pinned every message to CARE and dispatch never ran. Found by the
    # project owner typing into the demo widget and getting the same agent for
    # everything, which is precisely the defect A13 records — reintroduced one
    # layer above the fix.
    safe_agent = "".join(c for c in agent if c.isalnum() or c in "_-")
    return Response(
        content=DEMO_HTML.replace("__KEY__", safe_key).replace("__AGENT__", safe_agent),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


__all__ = ["router"]
