#!/usr/bin/env python3
"""Ask SELL one question and watch every step it takes.

    make sell-ask Q="I need a waterproof jacket under 150" URL=http://your-shop/neura/v1 TOKEN=xxx

The sibling of ``make care-ask``, and it exists for a reason specific to this
agent: **until it was written, SELL had never been pointed at a real
catalogue.** Every measurement of it — the 0.43 escalation precision, the four
failures in A14, the whole of `evals/` — ran against `store.json`, four invented
products written to exercise the harness. A recommender graded only on fixtures
is graded on the imagination of whoever wrote them.

## What it shows that CARE's version cannot

CARE answers *about* a thing the shopper already named. SELL has to **choose**,
and the choosing happens in two places that are easy to confuse:

* **`plan` chooses the lookups.** Which search, with which query. The query
  string is printed, because it is the difference between finding the socks and
  finding three jackets — measured on 2026-08-27, where a weak model searched
  badly and the failure was diagnosed as a drafting problem for a day.
* **`shortlist` chooses what may be recommended**, in code. It enforces the
  price ceiling, caps the candidates, and decides whether "we do not carry that"
  may be said at all. **Anything it drops, the composer never sees** — so a
  product missing from the reply is usually a shortlist decision, not a model
  one, and the SHORTLIST line is where to look first.

**`promises` is the fabrication check.** `respond` refuses to send a draft
naming a product that is not on that list, so a persuaded composer still cannot
invent a product. The line is printed on every run, including the ones that go
well, because it is the guarantee rather than a diagnostic.

``CUSTOMER=<id>`` is accepted for symmetry and changes almost nothing here:
**SELL reads no customer record at all.** A catalogue is public. That asymmetry
with CARE is the point of ADR-0023, and seeing the same flag do nothing is a
faster way to learn it than reading the ADR.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any

from neura_adapters.generic import GenericAdapter
from neura_agent_core.graph import CONFIG_KEY, initial_state
from neura_agent_core.rag import PostgresVectorStore, Retriever
from neura_agent_core.tools import SessionIdentity
from neura_agent_sell import build_runtime, compile_graph
from neura_agent_sell.tools import TOOL_SCOPES
from neura_commerce import AdapterError
from neura_core import Database, configure_logging, load_env
from neura_llm import LLMClient, ModelRole

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
OFF = "\033[0m"

TENANT = "tn_sell_ask"

#: Shown in every error this script prints. A shape to copy, not a real host —
#: naming the store this happens to be developed against would put a platform
#: name in code outside the adapter layer, which rule 1 forbids.
EXAMPLE_URL = "http://<your-shop>/neura/v1"

#: What each node is for, in one line, printed as it runs. Read by someone
#: trying to understand the agent, for whom a node name alone assumes the
#: understanding they came here for.
WHAT_IT_DOES = {
    "guard": "recognise a named attack · tokenise personal data (no model runs here)",
    "blocked": "refuse and log a security event — no person, no tools, no model",
    "route": "is this a recommendation? · pull out the budget and the attributes",
    "retrieve": "search the indexed catalogue and policies",
    "plan": "choose which catalogue lookups would answer this",
    "act": "authorise each lookup in code, then run the allowed ones",
    "shortlist": "decide IN CODE what may be recommended — price ceiling, cap, honest miss",
    "decline": "out of scope, and nobody needed — a fixed message, no model",
    "no_match": "this store genuinely does not carry it — a fixed message, no model",
    "compose": "draft a shortlist from the evidence, attributing every claim",
    "verify": "a second model checks every claim against that evidence",
    "respond": "send it — after checking the draft names no product the shortlist withheld",
    "escalate": "hand to a person, with everything they need",
}


def _role_map_name() -> str:
    """Which role map these hand-runs use — the configured one, by default.

    **Was hardcoded to `ollama-dev`, and that is a usability bug rather than a
    safety one.** Found 2026-08-28: the operator set `NEURA_ROLE_MAP=cloud-prod`
    in `.env` precisely so their laptop would stop running inference, and these
    scripts kept every model local anyway — silently, because nothing printed
    which map was in force.

    Deliberately *unlike* `neura-eval`, which pins `ollama-dev` on purpose so a
    suite can never cost money by accident. This is a single interactive
    question typed by a person who chose the setting, the models in use are
    printed on every run, and honouring `.env` is the least surprising thing it
    can do. `NEURA_ROLE_MAP=ollama-dev make ...` overrides it either way.
    """
    from neura_core import get_settings

    return get_settings().role_map


def _wrap(text: str, indent: str = "        ") -> str:
    """Reflow for a terminal without importing anything."""
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > 76:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    lines.append(current)
    return "\n".join(f"{indent}{line}" for line in lines)


def _products(context: str) -> list[str]:
    """The product headings out of a rendered shortlist, for a one-line summary.

    Deliberately shallow: the full evidence is printed below it, and this line
    exists so that "which products got through?" is answerable at a glance
    rather than by reading four paragraphs of merchant prose.
    """
    return [
        line.split(":", 1)[1].strip()
        for line in context.splitlines()
        if line.startswith("Product ")
    ]


def _show(node: str, update: dict[str, Any], elapsed_ms: int, runtime: Any) -> None:
    """Print what one node did."""
    print(f"  {BOLD}{node.upper()}{OFF} {DIM}— {WHAT_IT_DOES.get(node, '')}  ({elapsed_ms}ms){OFF}")

    if node == "guard":
        if update.get("blocked"):
            print(f"      matched     {RED}{update.get('block_reason', '?')}{OFF}")
            print(f"      {DIM}the reply names no rule — a block must not be an oracle{OFF}")
        elif tokens := update.get("redactions"):
            print(f"      redacted    {CYAN}{', '.join(tokens)}{OFF}")
            print(f"      model sees  {update.get('message', '')!r}")
        else:
            print(f"      {DIM}no rule matched · no personal data found{OFF}")

    elif node == "route":
        confidence = update.get("intent_confidence", 0.0)
        print(f"      intent      {CYAN}{update.get('intent')}{OFF}  confidence {confidence:.2f}")
        if resolved := update.get("search_query"):
            print(f"      the need    {resolved!r}")
        entities = update.get("entities") or {}
        # Printed separately from the rest, because these two are the constraints
        # `shortlist` will enforce in code further down, and seeing them here is
        # what makes that enforcement legible when it happens.
        if ceiling := entities.get("max_price"):
            print(
                f"      budget      {CYAN}{ceiling}{OFF} {DIM}(enforced in code, not asked of a model){OFF}"
            )
        if attributes := entities.get("required_attributes"):
            print(f"      must have   {attributes.replace('|', ', ')}")
        if named := entities.get("named_products"):
            print(f"      named       {named.replace('|', ', ')}")

    elif node == "retrieve":
        sources = update.get("sources") or []
        print(f"      found       {sources or 'nothing'}")
        if note := update.get("retrieval_note"):
            print(f"      {DIM}note: {note}{OFF}")

    elif node == "plan":
        offered = [s.name for s in runtime.registry.available_for(runtime.ctx)]
        print(f"      offered     {DIM}{', '.join(offered)}{OFF}")
        calls = update.get("proposed_calls", [])
        if not calls:
            # The failure mode A14 spent a session on. Named here rather than
            # printed as an empty list, because `shortlist` will shortly report
            # this as "the catalogue could not be searched" — which reads as an
            # outage and is not one.
            print(f"      chose       {RED}nothing{OFF}")
            print(f"      {DIM}no lookup means no shortlist; this turn will escalate{OFF}")
        for call in calls:
            print(f"      chose       {CYAN}{call.get('name')}{OFF}({call.get('arguments')})")

    elif node == "act":
        for decision in update.get("decisions", []):
            allowed = decision.outcome.value == "allow"
            mark = f"{GREEN}allowed{OFF}" if allowed else f"{RED}{decision.outcome.value}{OFF}"
            gate = f" at check '{decision.check.value}'" if decision.check else ""
            print(f"      policy      {decision.tool_name} → {mark}{gate}")
            if decision.reason:
                print(f"      {DIM}            {decision.reason}{OFF}")
        for invocation in update.get("invocations", []):
            if invocation.ok:
                print(f"      store said  {DIM}({invocation.latency_ms}ms){OFF}")
                print(f"{DIM}{_wrap(str(invocation.value)[:700])}{OFF}")

    elif node == "shortlist":
        promises = update.get("promises")
        context = update.get("context", "")
        if promises:
            print(
                f"      may recommend {GREEN}{len(promises)}{OFF}: {CYAN}{', '.join(promises)}{OFF}"
            )
            for heading in _products(context):
                print(f"      {DIM}  · {heading}{OFF}")
            print(f"      {DIM}the composer sees these and nothing else{OFF}")
        elif update.get("escalated"):
            print(f"      {RED}nothing to recommend, and the catalogue was not read{OFF}")
        else:
            # The honest miss. Distinct from the line above, and the distinction
            # is the product's central claim: "we do not carry that" is a
            # statement about the whole store, and may only be made when the
            # whole store was actually consulted (sell.md §2.3).
            print(
                f"      {YELLOW}nothing survived — the store was asked and does not carry it{OFF}"
            )

    elif node in ("compose", "no_match", "decline"):
        if draft := update.get("draft", ""):
            print(f"      draft       {DIM}(not sent yet — verify has not seen it){OFF}")
            print(f"{_wrap(draft)}")
        if reply := update.get("reply", ""):
            print(f"      {DIM}a fixed message — no model wrote this{OFF}")
            print(f"{_wrap(reply)}")

    elif node == "verify":
        grounded = update.get("grounded")
        mark = f"{GREEN}every claim supported{OFF}" if grounded else f"{RED}NOT grounded{OFF}"
        print(f"      verdict     {mark}")
        print(f"      {DIM}{update.get('verify_reason', '')}{OFF}")

    elif node == "escalate":
        print(f"      reason      {YELLOW}{update.get('escalation_reason')}{OFF}")

    if node in ("route", "plan", "shortlist") and update.get("escalated"):
        print(f"      {YELLOW}→ escalating: {update.get('escalation_reason')}{OFF}")

    print()


async def _ask(
    question: str,
    url: str,
    token: str,
    customer: str | None,
    retriever: Retriever | None,
) -> int:
    llm = LLMClient.from_role_map_name(_role_map_name())
    adapter = GenericAdapter(base_url=url, tenant_id=TENANT, token=token)

    try:
        health = await adapter.health()
    except AdapterError as exc:
        print(f"\n  {RED}could not reach the shop at {url!r}{OFF}")
        print(f"  {DIM}{exc}{OFF}\n")
        print(f'  {DIM}try:  make sell-ask Q="..." URL={EXAMPLE_URL} TOKEN=$TOKEN{OFF}\n')
        return 1

    if not health.ok:
        print(f"\n  {RED}the shop is not reachable at {url}{OFF}\n")
        return 1

    print(f"\n  {BOLD}shopper{OFF}   {question!r}")
    if customer:
        # Said plainly rather than accepted silently. SELL reads no customer
        # record, so a reader who passed this flag expecting the CARE behaviour
        # should be told it did nothing before they conclude it is broken.
        print(
            f"  {DIM}customer {customer} — noted, and SELL reads no customer record (ADR-0023){OFF}"
        )
    else:
        print(f"  {DIM}anonymous, which is correct: a catalogue is public{OFF}")
    print(
        f"  {DIM}router {llm.model_for(ModelRole.ROUTER)} · reasoner"
        f" {llm.model_for(ModelRole.REASONER)} · verifier {llm.model_for(ModelRole.GUARD)}"
        f" · guard: no model{OFF}\n"
    )

    runtime = build_runtime(
        tenant_id=TENANT,
        conversation_id="cnv_ask",
        adapter=adapter,
        llm=llm,
        # Read from the shop, not declared here. What the agent can do is decided
        # by what the store says it supports.
        capabilities=health.capabilities,
        scopes=TOOL_SCOPES,
        identity=SessionIdentity(customer_external_id=customer),
        retriever=retriever,
    )

    graph = compile_graph()

    started = time.perf_counter()
    last = started
    final: dict[str, Any] = {}

    async for event in graph.astream(
        initial_state(tenant_id=TENANT, conversation_id="cnv_ask", message=question),
        {"configurable": {CONFIG_KEY: runtime, "thread_id": "cnv_ask"}},
        stream_mode="updates",
    ):
        for node, update in event.items():
            now = time.perf_counter()
            _show(node, update or {}, int((now - last) * 1000), runtime)
            last = now
            final.update(update or {})

    total_ms = int((time.perf_counter() - started) * 1000)

    print(f"  {BOLD}{'─' * 74}{OFF}")
    if final.get("escalated"):
        print(f"  {YELLOW}HANDED TO A PERSON{OFF} — {final.get('escalation_reason')}\n")
    elif final.get("blocked"):
        print(f"  {RED}BLOCKED{OFF} — a named attack, ended without a person\n")
    else:
        print(f"  {GREEN}ANSWERED{OFF}\n")
    print("  the shopper sees:")
    print(f"{_wrap(str(final.get('reply', '')), indent='      ')}\n")

    # Printed on every run, not only the interesting ones. This is the guarantee
    # `respond` enforces — a draft naming a product outside this list is not
    # sent — and a guarantee shown only when it fires reads as a diagnostic.
    if promises := final.get("promises"):
        print(f"  {DIM}the reply could name only: {', '.join(promises)}{OFF}")
        print(f"  {DIM}anything else would have been withheld by `respond`, in code.{OFF}\n")

    if handoff := final.get("handoff"):
        print(f"  {DIM}and a person receives:{OFF}")
        for line in str(handoff).splitlines():
            print(f"  {DIM}    {line}{OFF}")
        print()

    usage = final.get("usage", {})
    spend = f" · {usage['tokens']} tokens" if usage.get("tokens") else ""
    print(
        f"  {DIM}total {total_ms}ms · tool calls used {runtime.budget.calls_used}"
        f"/{runtime.budget.max_tool_calls}{spend}{OFF}\n"
    )

    await adapter.aclose()
    return 0


async def run(question: str, url: str, token: str, customer: str | None) -> int:
    """Open a tenant-scoped session, build the retriever, then ask.

    Degrades rather than refuses when the database is down: SELL answers from
    tool results, so a catalogue lookup still works without pgvector, and
    requiring Postgres before you can ask one question would make this useless
    exactly when you are debugging something else.
    """
    database = Database.from_settings()
    llm = LLMClient.from_role_map_name(_role_map_name())

    try:
        reachable = await database.ping()
    except Exception:
        reachable = False

    if not reachable:
        print(
            f"\n  {YELLOW}no database — running without retrieval.{OFF}"
            f"\n  {DIM}catalogue tools still work; indexed text will not be searched."
            f"\n  start it with `make up && make migrate`.{OFF}"
        )
        try:
            return await _ask(question, url, token, customer, None)
        finally:
            await database.dispose()

    try:
        async with database.tenant_session(TENANT) as session:
            retriever = Retriever(PostgresVectorStore(session), llm, tenant_id=TENANT)
            return await _ask(question, url, token, customer, retriever)
    finally:
        await database.dispose()


def main() -> None:
    # **Before anything reads a setting.** `roles.py` resolves cloud models
    # through raw `os.getenv`, so a `.env` that has not been loaded leaves the
    # whole cloud map "not configured" — which is what these three scripts did,
    # invisibly, for as long as they hardcoded `ollama-dev` and never needed it.
    load_env()
    parser = argparse.ArgumentParser(description="Ask SELL one question, and watch it think.")
    parser.add_argument("--url", required=True, help="The shop's Generic Interface base URL")
    parser.add_argument("--token", required=True, help="The shop's API token")
    parser.add_argument(
        "--as-customer",
        default=None,
        help="Accepted for symmetry with care-ask. SELL reads no customer record.",
    )
    parser.add_argument("question", help="What the shopper types")
    args = parser.parse_args()

    if not args.url.startswith(("http://", "https://")):
        print(
            f"\n  {RED}--url must start with http:// or https:// — got {args.url!r}{OFF}\n"
            f'  {DIM}try:  make sell-ask Q="..." URL={EXAMPLE_URL} TOKEN=$TOKEN{OFF}\n',
            file=sys.stderr,
        )
        sys.exit(2)

    if not args.token.strip():
        print(
            f"\n  {RED}--token is empty{OFF}\n"
            f"  {DIM}the shop issues this token; it lives in that shop's .env as"
            f" NEURA_API_TOKEN.{OFF}\n"
            f"  {DIM}  TOKEN=$(grep '^NEURA_API_TOKEN=' <shop>/.env "
            f"| cut -d= -f2- | tr -d '\"'){OFF}\n",
            file=sys.stderr,
        )
        sys.exit(2)

    configure_logging(level="ERROR", json_output=False)
    sys.exit(asyncio.run(run(args.question, args.url, args.token, args.as_customer)))


if __name__ == "__main__":
    main()
