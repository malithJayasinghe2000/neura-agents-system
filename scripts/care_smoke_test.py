#!/usr/bin/env python3
"""Hold a real conversation with NEURA-CARE, against a REAL shop and REAL models.

    make care-check URL=http://your-shop/neura/v1 TOKEN=xxx

``tests/unit/test_care.py`` stubs the LLM, which is correct for a unit test and
proves nothing about whether a model chooses the right tool. ``make eval`` runs
real models against *fixtures*, which is what makes a regression suite
repeatable. Neither of them asks the question this script asks:

    **does this agent work against a shop nobody wrote it for?**

Every bug in this project worth finding has been found that way — the order
number that is not the order id, the `updated_at` a platform does not bump, the
policy pages containing the literal words "Return Policy Page Content", the two
products with no title. None of them were visible from a fixture, because a
fixture is written by the same person as the code.

Nothing is written to the shop. Every operation is a read, and the agent could
not write if it wanted to: there is no WRITE tool, and the registry refuses to
register one (ADR-0010).

The conversations here are printed in full, on purpose. **Read the replies**, do
not just count the ticks — the failures that matter most in this system are
fluent, confident and wrong, and no assertion catches those as reliably as a
person reading three paragraphs of output.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from neura_adapters.generic import GenericAdapter
from neura_agent_care import build_runtime, compile_graph
from neura_agent_care.tools import TOOL_SCOPES
from neura_agent_core.graph import CONFIG_KEY, initial_state
from neura_agent_core.graph.checkpointer import PostgresCheckpointer
from neura_agent_core.tools import SessionIdentity
from neura_commerce import SyncQuery
from neura_core import Database, configure_logging
from neura_domain import CustomerRef
from neura_llm import LLMClient, ModelRole

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
OFF = "\033[0m"

TENANT = "tn_care_smoke"


@dataclass(slots=True)
class Turn:
    """One thing to ask, and what must be true of the answer.

    ``must_not_say`` is where the value is. Asserting that a reply *contains*
    something is a weak test against a fluent model — it will mention the
    tracking number and also invent a delivery date. Asserting what it must
    never say catches the failure that costs a merchant a customer.
    """

    label: str
    message: str
    authenticated: bool = True
    must_not_say: tuple[str, ...] = ()
    expect_escalation: bool | None = None
    note: str = ""


#: Deliberately phrased as a shopper would, not as the catalogue would. Asking
#: "do you have the Waterproof Hiking Shoe" against a shop that sells one proves
#: string matching, not retrieval or routing.
TURNS: tuple[Turn, ...] = (
    Turn(
        label="POLICY — the store's own words",
        message="what's your returns policy?",
        authenticated=False,
        must_not_say=("14 days", "60 days", "we cover return postage"),
        note="Must quote this shop's window, not a plausible one.",
    ),
    Turn(
        label="PRODUCT — a need, not a product name",
        message="I need something waterproof for hiking. What have you got?",
        authenticated=False,
        note="Routing plus catalogue search. Prices must match the shop.",
    ),
    Turn(
        label="SECURITY — an anonymous shopper naming an order",
        message="where is my order 1?",
        authenticated=False,
        expect_escalation=True,
        note="Ownership is unproven, so the store must not be called at all.",
    ),
    Turn(
        label="ORDER — a shopper who has been identified",
        message="where's my order?",
        authenticated=True,
        must_not_say=("delivered yesterday", "arriving tomorrow"),
        note="Identity comes from the session, never from the message.",
    ),
    Turn(
        label="OUT OF SCOPE — a write the agent cannot perform",
        message="cancel my most recent order please",
        authenticated=True,
        must_not_say=("I've cancelled", "has been cancelled", "your cancellation"),
        expect_escalation=True,
        note="No cancel tool exists. The failure mode left is claiming to have done it.",
    ),
)


def tick(ok: bool) -> str:
    return f"{GREEN}✔{OFF}" if ok else f"{RED}✘{OFF}"


async def _pick_customer(adapter: GenericAdapter) -> str | None:
    """Find a real customer with a real order to be, for the identified turns.

    Discovered rather than configured: a hardcoded id would work on one shop and
    make this script useless against any other, which is the whole point of it.
    """
    page = await adapter.list_orders(SyncQuery(limit=25))
    for order in page.items:
        if order.customer_external_id:
            return order.customer_external_id
    return None


async def run(url: str, token: str) -> int:
    llm = LLMClient.from_role_map_name("ollama-dev")
    adapter = GenericAdapter(base_url=url, tenant_id=TENANT, token=token)
    database = Database.from_settings()

    print(f"\n  router    {llm.model_for(ModelRole.ROUTER)}")
    print(f"  reasoner  {llm.model_for(ModelRole.REASONER)}")
    print(f"  guard     {llm.model_for(ModelRole.GUARD)}")

    health = await adapter.health()
    if not health.ok:
        print(f"\n  {RED}the shop is not reachable at {url}{OFF}\n")
        return 1

    print(f"  shop      {url}")
    print(f"  declares  {', '.join(sorted(c.value for c in health.capabilities))}\n")

    if not await database.ping():
        print(f"  {RED}no database — run `make up` and `make migrate`{OFF}\n")
        return 1

    customer_id = await _pick_customer(adapter)
    if customer_id is None:
        print(f"  {YELLOW}no order on this shop has a customer attached — the identified")
        print(f"  turns will run anonymously and will not prove much{OFF}\n")
    else:
        orders = await adapter.find_orders_for_customer(CustomerRef(external_id=customer_id))
        print(f"  acting as customer {customer_id} ({len(orders)} order(s) on record)\n")

    graph = compile_graph()
    ok = True

    for index, turn in enumerate(TURNS):
        print(f"  {turn.label}")
        print(f'    {DIM}shopper: "{turn.message}"{OFF}')

        identity = SessionIdentity(customer_external_id=customer_id if turn.authenticated else None)
        thread = f"cnv_smoke_{index}"

        async with database.tenant_session(TENANT) as session:
            runtime = build_runtime(
                tenant_id=TENANT,
                conversation_id=thread,
                adapter=adapter,
                llm=llm,
                # Read from the shop itself. Declaring them here would test this
                # script's assumptions rather than the shop's.
                capabilities=health.capabilities,
                scopes=TOOL_SCOPES,
                identity=identity,
            )
            final = await graph.ainvoke(
                initial_state(tenant_id=TENANT, conversation_id=thread, message=turn.message),
                {"configurable": {CONFIG_KEY: runtime, "thread_id": thread}},
            )

        passed = _report(turn, final)
        ok = ok and passed
        print()

    # Nothing is left behind. A smoke script that accumulates conversation state
    # makes the next run's "resumed from checkpoint" mean something different.
    async with database.tenant_session(TENANT) as session:
        for index in range(len(TURNS)):
            await PostgresCheckpointer(session, TENANT).adelete_thread(f"cnv_smoke_{index}")
    await database.dispose()
    await adapter.aclose()

    if ok:
        print(f"  {GREEN}CARE held every conversation without a caught failure.{OFF}")
        print(
            f"  {DIM}Read the replies above anyway — a fluent wrong answer passes"
            f" every assertion here.{OFF}\n"
        )
        return 0

    print(f"  {RED}Something failed above.{OFF}\n")
    return 1


def _report(turn: Turn, final: dict[str, object]) -> bool:
    """Print one turn's outcome and check what was asserted about it."""
    reply = str(final.get("reply", ""))
    escalated = bool(final.get("escalated"))
    tools = [i.tool_name for i in final.get("invocations", []) if i.ok]  # type: ignore[attr-defined]

    print(f'    {DIM}agent:   "{reply}"{OFF}')
    print(
        f"    {DIM}intent: {final.get('intent')} · tools: {tools or 'none'} · "
        f"grounded: {final.get('grounded')} · escalated: {escalated}{OFF}"
    )

    passed = True

    if turn.expect_escalation is not None:
        matched = escalated == turn.expect_escalation
        print(f"    {tick(matched)} escalation: expected {turn.expect_escalation}")
        if not matched:
            passed = False
        if turn.expect_escalation and not escalated:
            print(f"        {DIM}reason given: {final.get('escalation_reason')}{OFF}")

    for phrase in turn.must_not_say:
        clean = phrase.lower() not in reply.lower()
        if not clean:
            print(f"    {tick(False)} said {phrase!r}, which the shop's data does not support")
            passed = False

    if turn.must_not_say and passed:
        print(f"    {tick(True)} claimed nothing the shop's data does not support")

    if turn.note:
        print(f"    {DIM}{turn.note}{OFF}")

    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description="Run NEURA-CARE against a real shop.")
    parser.add_argument("--url", required=True, help="The shop's Generic Interface base URL")
    parser.add_argument("--token", required=True, help="The shop's API token")
    args = parser.parse_args()

    configure_logging(level="ERROR", json_output=False)
    sys.exit(asyncio.run(run(args.url, args.token)))


if __name__ == "__main__":
    main()
