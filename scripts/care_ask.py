#!/usr/bin/env python3
"""Ask CARE one question and watch every step it takes.

    make care-ask Q="where is my order?" URL=http://your-shop/neura/v1 TOKEN=xxx
    make care-ask Q="do you deliver to Ireland?" URL=... TOKEN=... CUSTOMER=385

``make care-check`` runs a fixed script and tells you pass or fail. This is the
other tool you want: **one question, and the whole pipeline printed as it
happens** — what the router decided, what the planner asked for, what the policy
engine allowed, what the store returned, what the model drafted, and whether the
verifier let it through.

It is a debugging and explanation tool, and it exists because "why did it say
that?" is the question ADR-0004 chose an explicit graph in order to be able to
answer. A graph you cannot watch is an agent loop with extra steps.

Two things it shows that nothing else does:

* **Where the time goes.** Each node is timed. On a local model the answer is
  usually "the reasoner", and that is a product decision waiting to happen, not
  a detail.
* **Which tools the model was even offered.** A tool the store's capabilities do
  not support is never put in front of the model, so "why didn't it check stock?"
  is often answered by the OFFERED line rather than by anything about the model.

``CUSTOMER=<id>`` runs the turn as an identified shopper. Without it you are
anonymous, which is what a shopper in a chat window is until the store says
otherwise — and it is the difference between an order lookup and a refusal.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any

from neura_adapters.generic import GenericAdapter
from neura_agent_care import build_runtime, compile_graph
from neura_agent_care.tools import TOOL_SCOPES
from neura_agent_core.graph import CONFIG_KEY, initial_state
from neura_agent_core.rag import PostgresVectorStore, Retriever
from neura_agent_core.tools import SessionIdentity
from neura_commerce import AdapterError
from neura_core import Database, configure_logging
from neura_llm import LLMClient, ModelRole

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
OFF = "\033[0m"

TENANT = "tn_care_ask"

#: Shown in every error this script prints. A shape to copy, not a real host —
#: naming the store this happens to be developed against would put a platform
#: name in code outside the adapter layer, which rule 1 forbids and the CI grep
#: catches. Your shop's actual URL is whatever it serves the Generic Interface on.
EXAMPLE_URL = "http://<your-shop>/neura/v1"

#: What each node is for, in one line, printed as it runs. This script is read
#: by someone trying to understand the agent, and a node name alone assumes they
#: already do.
WHAT_IT_DOES = {
    "guard": "recognise a named attack · tokenise personal data (no model runs here)",
    "blocked": "refuse and log a security event — no person, no tools, no model",
    "route": "classify the question · resolve pronouns · pull out the order number",
    "retrieve": "search the indexed catalogue and policies",
    "plan": "choose which store lookups would answer this",
    "act": "authorise each lookup in code, then run the allowed ones",
    "triage": "is the turn still answerable?",
    "compose": "draft a reply from the evidence, and only the evidence",
    "verify": "a second model checks every claim against that evidence",
    "respond": "send it",
    "escalate": "hand to a person, with everything they need",
}


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


def _show(node: str, update: dict[str, Any], elapsed_ms: int, runtime: Any) -> None:
    """Print what one node did."""
    print(f"  {BOLD}{node.upper()}{OFF} {DIM}— {WHAT_IT_DOES.get(node, '')}  ({elapsed_ms}ms){OFF}")

    if node == "guard":
        # The two things a reader needs: which rule fired, and what the model is
        # about to be shown instead of what the shopper typed. Token names only —
        # printing the values back would undo the point of the node.
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
            print(f"      asking      {resolved!r}")
        if entities := update.get("entities"):
            print(f"      extracted   {entities}")

    elif node == "retrieve":
        sources = update.get("sources") or []
        print(f"      found       {sources or 'nothing'}")
        if note := update.get("retrieval_note"):
            print(f"      {DIM}note: {note}{OFF}")

    elif node == "plan":
        offered = [s.name for s in runtime.registry.available_for(runtime.ctx)]
        chosen = [c.get("name") for c in update.get("proposed_calls", [])]
        print(f"      offered     {DIM}{', '.join(offered)}{OFF}")
        print(f"      chose       {CYAN}{chosen or 'no lookup needed'}{OFF}")

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
                print(f"{DIM}{_wrap(str(invocation.value)[:600])}{OFF}")

    elif node == "compose":
        print(f"      draft       {DIM}(not sent yet — verify has not seen it){OFF}")
        print(f"{_wrap(update.get('draft', ''))}")

    elif node == "verify":
        grounded = update.get("grounded")
        mark = f"{GREEN}every claim supported{OFF}" if grounded else f"{RED}NOT grounded{OFF}"
        print(f"      verdict     {mark}")
        print(f"      {DIM}{update.get('verify_reason', '')}{OFF}")

    elif node == "escalate":
        print(f"      reason      {YELLOW}{update.get('escalation_reason')}{OFF}")

    if node in ("route", "plan", "triage") and update.get("escalated"):
        print(f"      {YELLOW}→ escalating: {update.get('escalation_reason')}{OFF}")

    print()


async def _ask(
    question: str,
    url: str,
    token: str,
    customer: str | None,
    retriever: Retriever | None,
) -> int:
    llm = LLMClient.from_role_map_name("ollama-dev")
    adapter = GenericAdapter(base_url=url, tenant_id=TENANT, token=token)

    try:
        health = await adapter.health()
    except AdapterError as exc:
        # Caught rather than allowed to propagate, because the traceback is not
        # the useful part. The commonest way to arrive here is a mistyped or
        # placeholder `URL=`, and the raw failure is forty lines of httpx frames
        # ending in a chained exception whose one relevant sentence is at the
        # very bottom. A developer running this by hand should be told what to
        # type instead.
        print(f"\n  {RED}could not reach the shop at {url!r}{OFF}")
        print(f"  {DIM}{exc}{OFF}\n")
        print(f'  {DIM}try:  make care-ask Q="..." URL={EXAMPLE_URL} TOKEN=$TOKEN{OFF}\n')
        return 1

    if not health.ok:
        print(f"\n  {RED}the shop is not reachable at {url}{OFF}\n")
        return 1

    who = f"customer {customer}" if customer else "an anonymous shopper (nothing proven)"
    print(f"\n  {BOLD}shopper{OFF}   {question!r}")
    print(f"  {DIM}asking as {who}")
    # The GUARD *role* is labelled "verifier" here because since milestone 1.12
    # that is the only node using it. The `guard` node has no model at all —
    # printing a model name beside it would tell the reader the opposite of what
    # ADR-0011 decided.
    print(
        f"  router {llm.model_for(ModelRole.ROUTER)} · reasoner {llm.model_for(ModelRole.REASONER)}"
        f" · verifier {llm.model_for(ModelRole.GUARD)} · guard: no model{OFF}\n"
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

    # No checkpointer: one question, one process, nothing to resume.
    graph = compile_graph()

    started = time.perf_counter()
    last = started
    final: dict[str, Any] = {}

    # `updates` streaming gives one event per node — which is exactly the
    # explanation this script exists to print.
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
        print("  the shopper sees:")
    else:
        print(f"  {GREEN}ANSWERED{OFF}\n")
        print("  the shopper sees:")
    print(f"{_wrap(str(final.get('reply', '')), indent='      ')}\n")

    if handoff := final.get("handoff"):
        print(f"  {DIM}and a person receives:{OFF}")
        for line in str(handoff).splitlines():
            print(f"  {DIM}    {line}{OFF}")
        print()

    print(
        f"  {DIM}total {total_ms}ms · tool calls used {runtime.budget.calls_used}"
        f"/{runtime.budget.max_tool_calls}{OFF}\n"
    )

    await adapter.aclose()
    return 0


async def run(question: str, url: str, token: str, customer: str | None) -> int:
    """Open a tenant-scoped session, build the retriever, then ask.

    Retrieval is wired here rather than left out, because omitting it makes this
    script disagree with the agent it claims to explain: the served graph has a
    retriever, and a tools-only run answers some questions worse for a reason
    that appears nowhere in the output except one dim "retrieval not configured".

    **It degrades rather than refuses.** A shopper's question about an order
    needs a tool, not the catalogue, and requiring Postgres to be up before you
    can ask one would make this tool useless exactly when you are debugging
    something else. If the database is unreachable the run continues and says so
    — which is also what the `retrieve` node does at runtime.
    """
    database = Database.from_settings()
    llm = LLMClient.from_role_map_name("ollama-dev")

    try:
        reachable = await database.ping()
    except Exception:
        reachable = False

    if not reachable:
        print(
            f"\n  {YELLOW}no database — running without retrieval.{OFF}"
            f"\n  {DIM}tools still work; indexed catalogue and policy text will not be"
            f" searched.\n  start it with `make up && make migrate`.{OFF}"
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
    parser = argparse.ArgumentParser(description="Ask CARE one question, and watch it think.")
    parser.add_argument("--url", required=True, help="The shop's Generic Interface base URL")
    parser.add_argument("--token", required=True, help="The shop's API token")
    parser.add_argument("--as-customer", default=None, help="Run as an identified customer id")
    parser.add_argument("question", help="What the shopper types")
    args = parser.parse_args()

    # Checked here, before anything opens a socket. `URL=...` copied verbatim
    # out of a set of instructions is the commonest way to run this wrongly, and
    # an argument fault should be reported as one rather than as a transport
    # error thrown from four frames inside an HTTP library.
    if not args.url.startswith(("http://", "https://")):
        print(
            f"\n  {RED}--url must start with http:// or https:// — got {args.url!r}{OFF}\n"
            f'  {DIM}try:  make care-ask Q="..." URL={EXAMPLE_URL} TOKEN=$TOKEN{OFF}\n',
            file=sys.stderr,
        )
        sys.exit(2)

    if not args.token.strip():
        print(
            f"\n  {RED}--token is empty{OFF}\n"
            # No path to a particular shop here, deliberately. Rule 1 caught the
            # first version of this line: naming the test store in a help string
            # is exactly how a platform name leaks out of the adapter layer, and
            # a help message is no more exempt than a tool call is.
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
