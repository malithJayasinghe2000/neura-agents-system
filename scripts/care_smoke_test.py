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
from neura_core import Database, configure_logging, load_env
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


@dataclass(slots=True)
class Conversation:
    """Several turns in ONE thread — the thing `TURNS` above cannot express.

    **Every entry in `TURNS` gets `cnv_smoke_<index>`, a thread of its own**, so
    that suite is five one-message chats and not a conversation, despite this
    file's own docstring. [A20](../docs/open-questions.md) — found on a real
    storefront on 2026-09-02, where a conversation died at its *second* message
    after a handover — is invisible to it **by construction**, because nothing
    there ever sends a second message.

    Added 2026-09-19. These reuse one `thread_id`, so the checkpointer carries
    the history forward exactly as it does for a shopper in the widget.
    """

    label: str
    thread: str
    turns: tuple[Turn, ...]
    note: str = ""


CONVERSATIONS: tuple[Conversation, ...] = (
    Conversation(
        label="A20 — does the conversation survive a handover?",
        thread="cnv_smoke_multi_handover",
        note=(
            "The router was measured returning confidence 0.00 after any handover, and the "
            "ownership gate forces a handover on the commonest opening question. So message 2 "
            "is the one that matters: it must still be answered."
        ),
        turns=(
            Turn(
                label="1 · anonymous shopper names an order — forces the handover",
                message="where is my order 1?",
                authenticated=False,
                expect_escalation=True,
            ),
            Turn(
                label="2 · an ordinary question, AFTER the handover",
                message="what's your returns policy?",
                authenticated=False,
                expect_escalation=False,
                must_not_say=("14 days", "60 days"),
                note="A20 reproduces if this escalates, or comes back empty.",
            ),
        ),
    ),
    Conversation(
        label='CONTEXT — does the second message know what "it" is?',
        thread="cnv_smoke_multi_pronoun",
        note=(
            "`route` must write a RESOLVED `search_query`. A node reading `message` instead "
            "asks the catalogue about a subject that is not there — AGENTS.md's gotcha table."
        ),
        turns=(
            Turn(
                label="1 · a need, not a product name",
                message="I need something waterproof for hiking. What have you got?",
                authenticated=False,
            ),
            Turn(
                label="2 · a pronoun only the first message explains",
                message="how much is it?",
                authenticated=False,
                # **Added after the first run, which this arm let through.** It
                # was written with a `note` and no assertion, so the turn
                # escalated, the suite printed "held every conversation without
                # a caught failure", and the defect was visible only to someone
                # reading the replies. A check that reports green while the
                # thing it gates fails is this repository's house failure mode
                # and it does not get to happen in a file added to catch one.
                expect_escalation=False,
                note='Must answer about the product just named, not ask what "it" means.',
            ),
        ),
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


async def run(url: str, token: str, role_map: str) -> int:
    # **`role_map` is a parameter as of 2026-09-19, and it was hardcoded to
    # `ollama-dev` before.** That is the hole PROJECT_STATE records being closed
    # for the eval targets on 2026-09-12: a script that names one map itself
    # answers for that map whatever the caller meant, and the only route to a
    # cloud answer was to not use `make`. The default is unchanged, so a bare
    # `make care-check` runs exactly what it ran yesterday.
    llm = LLMClient.from_role_map_name(role_map)
    adapter = GenericAdapter(base_url=url, tenant_id=TENANT, token=token)
    database = Database.from_settings()

    print(f"\n  role map  {role_map}")
    print(f"  router    {llm.model_for(ModelRole.ROUTER)}")
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

    # ── The same agent, but as a CONVERSATION. ──────────────────────────────
    # One thread per conversation rather than one per message, which is the
    # only difference that matters and the reason A20 could not be seen above.
    for conversation in CONVERSATIONS:
        print(f"  {conversation.label}")
        print(f"    {DIM}{conversation.note}{OFF}")
        # **The history is carried by hand, exactly as `neura-api` carries it.**
        # `initial_state` defaults `history` to empty and the graph never reads
        # the checkpointer for it, so a thread_id alone buys continuity for
        # LangGraph and *nothing* for `route` — which is the one node that has to
        # resolve "it" into a product. `turns.py` loads it from
        # `conversations.history(...)` and passes `history=` on every turn;
        # omitting it here made CARE look broken on 2026-09-19 when the harness
        # was what was broken. Roles are `shopper`/`agent` because that is what
        # `Role` stores and what `route._render` prints back to the model.
        history: list[dict[str, str]] = []
        for position, turn in enumerate(conversation.turns, start=1):
            print(f'    {DIM}[{position}] shopper: "{turn.message}"{OFF}')
            identity = SessionIdentity(
                customer_external_id=customer_id if turn.authenticated else None
            )
            async with database.tenant_session(TENANT) as session:
                runtime = build_runtime(
                    tenant_id=TENANT,
                    conversation_id=conversation.thread,
                    adapter=adapter,
                    llm=llm,
                    capabilities=health.capabilities,
                    scopes=TOOL_SCOPES,
                    identity=identity,
                )
                final = await graph.ainvoke(
                    initial_state(
                        tenant_id=TENANT,
                        conversation_id=conversation.thread,
                        message=turn.message,
                        history=list(history),
                    ),
                    {"configurable": {CONFIG_KEY: runtime, "thread_id": conversation.thread}},
                )
            # An empty reply on a turn that did not escalate is A20's signature
            # and no existing assertion names it: `must_not_say` cannot catch a
            # string that is not there, and ADR-0020 makes silence a bug.
            if not str(final.get("reply", "")).strip() and not final.get("escalated"):
                print(f"    {tick(False)} the reply was EMPTY and the turn did not escalate")
                ok = False
            ok = _report(turn, final) and ok
            history.append({"role": "shopper", "content": turn.message})
            history.append({"role": "agent", "content": str(final.get("reply", ""))})
        print()

    # Nothing is left behind. A smoke script that accumulates conversation state
    # makes the next run's "resumed from checkpoint" mean something different.
    async with database.tenant_session(TENANT) as session:
        for index in range(len(TURNS)):
            await PostgresCheckpointer(session, TENANT).adelete_thread(f"cnv_smoke_{index}")
        for conversation in CONVERSATIONS:
            await PostgresCheckpointer(session, TENANT).adelete_thread(conversation.thread)
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
    parser.add_argument(
        "--role-map",
        default="ollama-dev",
        help="ollama-dev (free, local) or cloud-prod (spends API quota)",
    )
    args = parser.parse_args()

    # **Finding 8, still live here on 2026-09-19.** The hand-test scripts were
    # found ignoring `.env` on 2026-08-29 and all but three were fixed; this was
    # one of the three. It went unnoticed because `ollama-dev` needs nothing from
    # `.env` — `OLLAMA_BASE_URL` defaults to localhost — so the omission is
    # invisible until the first cloud run, which then fails claiming
    # `CLOUD_LLM_BASE_URL not set` while it sits in `.env` two directories up.
    # `load_env()` never overrides a real environment variable, so a per-process
    # `CLOUD_MODEL_*` override still wins.
    load_env()
    configure_logging(level="ERROR", json_output=False)
    sys.exit(asyncio.run(run(args.url, args.token, args.role_map)))


if __name__ == "__main__":
    main()
