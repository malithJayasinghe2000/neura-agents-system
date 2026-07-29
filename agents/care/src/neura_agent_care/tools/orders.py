"""Order lookups — the highest-volume intent, and the one with teeth.

Two tools, and the difference between them is entirely about *how the shopper is
identified*:

* :func:`get_order_status` takes an order number the shopper typed. The policy
  engine has already proven this session may see that reference before the tool
  runs (``requires_ownership``), so the argument is safe by the time it arrives.
* :func:`find_orders_for_customer` takes **nothing**. It answers "where are my
  orders?" from the identity the session has already established, server-side.

That asymmetry is deliberate and is the security design of this module. See the
note above :func:`find_orders_for_customer` for why the obvious signature — an
``email`` argument the model fills in — is the wrong one.
"""

from __future__ import annotations

from neura_agent_care.tools.render import order_evidence, order_summary
from neura_agent_core.tools import ToolContext, tool
from neura_commerce import AdapterError
from neura_core import get_logger
from neura_domain import Capability, CustomerRef, Order

log = get_logger(__name__)

#: One message for "no such order" and for "an order that is not yours".
#:
#: Uniform on purpose. A distinct "that order exists but isn't yours" turns the
#: reply into an oracle: a caller learns which numbers are real by reading the
#: difference, which is order enumeration with a friendlier interface. The policy
#: engine takes the same care with its ownership refusal, for the same reason
#: (security-model.md §3).
NOT_FOUND = (
    "No order with that reference is available for this conversation. Do not "
    "speculate about whether it exists — ask the shopper to check the number, or "
    "offer to pass them to a colleague."
)

#: A shopper asking "where are my orders?" wants the recent ones, not an archive.
MAX_ORDERS_LISTED = 5


@tool(
    name="get_order_status",
    description=(
        "Look up one order by the order number the shopper gave you, and return its "
        "status, items, totals and tracking. Use when the shopper names an order number."
    ),
    requires=[Capability.ORDER_READ],
    scopes=["care:order:read"],
    pii_output=True,
    requires_ownership="order_ref",
    # Declared because `_belongs_to_session` below genuinely enforces it: an
    # order whose customer is not this session's customer is returned as
    # NOT_FOUND. The engine grants an authenticated session an arbitrary order
    # reference only on the strength of this declaration, so it must not be added
    # to a tool that does not actually do the filtering (open question A6).
    scoped_to_session=True,
)
async def get_order_status(order_ref: str, ctx: ToolContext) -> str:
    """One order, addressed the way the shopper addresses it."""
    order = await _find_by_number(order_ref, ctx)

    if order is None or not _belongs_to_session(order, ctx):
        log.info(
            "order_lookup_miss",
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            found=order is not None,
        )
        return NOT_FOUND

    return order_evidence(order)


async def _find_by_number(order_ref: str, ctx: ToolContext) -> Order | None:
    """Resolve what the shopper calls an order into the order itself.

    Worth spelling out, because it is a place the canonical model and a shopper
    disagree. ``Order.order_number`` is "what the customer calls it"; a store's
    ``external_id`` is its own internal key. On some platforms they are the same
    string and on others they are not, and a lookup that assumes the first works
    perfectly in development and returns "no such order" for every shopper on a
    store where they differ.

    So the *search* path is preferred where the store supports it — it asks the
    question the shopper actually asked — and direct id lookup is the fallback
    for stores that cannot search.
    """
    ref = order_ref.strip()

    if Capability.ORDER_SEARCH in ctx.capabilities:
        # Annotated because `ToolContext.adapter` is deliberately loose — most
        # tools need no adapter, and the ones that do narrow it themselves.
        matches: list[Order] = await ctx.adapter.find_orders_for_customer(
            CustomerRef(order_ref=ref)
        )
        for order in matches:
            if order.order_number == ref:
                return order

    try:
        return await ctx.adapter.get_order(ref)  # type: ignore[no-any-return]
    except AdapterError:
        # A store that 404s an unknown id rather than returning null. Not finding
        # an order is an ordinary outcome, not an incident, and the caller gets
        # the same uniform message either way.
        return None


def _belongs_to_session(order: Order, ctx: ToolContext) -> bool:
    """The check the policy engine's ownership gate assumes a tool performs.

    ``SessionIdentity.may_see`` returns ``True`` for *any* reference once a
    session is authenticated, and its docstring states the reason: "the adapter
    query is scoped to their id, so the reference is theirs by construction".
    That is a precondition on the tool, not a fact about the engine — and this
    tool is not scoped by customer id, because the shopper addressed the order by
    number.

    So the scoping happens here, after the fetch. Without it, a signed-in shopper
    could read a stranger's order by typing its number, having passed every one
    of the eight checks. Recorded in PROJECT_STATE as a candidate for a
    structural defence in the engine, since "every tool remembers" is the kind of
    control that holds until the day someone adds a tool.
    """
    customer_id = ctx.identity.customer_external_id
    if customer_id is None:
        # An anonymous session proved ownership of this specific reference to get
        # here at all — there is nothing further to scope it to.
        return True

    if order.customer_external_id is None:
        # A guest checkout, or a store that does not attach a customer. It cannot
        # be shown to be theirs, so it is not shown.
        return False

    return order.customer_external_id == customer_id


@tool(
    name="find_orders_for_customer",
    description=(
        "List the shopper's recent orders. Use when they ask about an order but do not "
        "give an order number. Takes no arguments — it uses the identity of the person "
        "already in this conversation."
    ),
    requires=[Capability.ORDER_SEARCH, Capability.CUSTOMER_READ],
    scopes=["care:order:read"],
    pii_output=True,
)
async def find_orders_for_customer(ctx: ToolContext) -> str:
    """The shopper's own orders, and only ever their own.

    **This tool deliberately has no arguments.**

    The obvious signature is ``find_orders_for_customer(email: str)``, and it is
    a data-exfiltration bug wearing a helpful face. The email would be chosen by
    the model, which means chosen by whoever is typing — and the ownership gate
    could not stop it, because ``may_see`` returns ``True`` for an authenticated
    session regardless of *whose* email was passed. "What are jane@example.com's
    orders?" would be answered for anyone signed in.

    Taking the customer from :class:`SessionIdentity` instead makes the abuse
    unexpressible rather than merely refused. There is no argument to poison, so
    no prompt can reach it. The engine has no gate for "requires an authenticated
    session" today, so an unverified session gets an honest empty answer here.
    """
    customer_id = ctx.identity.customer_external_id
    if customer_id is None:
        return (
            "This conversation has not established who the shopper is, so their "
            "orders cannot be listed. Ask for the order number, or offer to pass "
            "them to a colleague."
        )

    orders = await ctx.adapter.find_orders_for_customer(CustomerRef(external_id=customer_id))

    if not orders:
        return "This shopper has no orders on record with this store."

    recent = sorted(orders, key=_placed_at_key, reverse=True)[:MAX_ORDERS_LISTED]
    lines = [order_summary(order) for order in recent]

    if len(orders) > MAX_ORDERS_LISTED:
        lines.append(
            f"({len(orders)} orders in total; the {MAX_ORDERS_LISTED} most recent are shown. "
            "Do not describe the others.)"
        )

    return "\n".join(lines)


def _placed_at_key(order: Order) -> str:
    """Sort newest first, tolerating orders with no placed date.

    An order missing ``placed_at`` sorts last rather than raising: a store with
    one incomplete record must not break the answer for the rest.
    """
    return order.placed_at.isoformat() if order.placed_at else ""
