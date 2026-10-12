#!/usr/bin/env python3
"""Does the AI still answer after a handover's words are in the chat? ADR-0062 §12, G103.

    uv run python scripts/handover_history_check.py --url http://shop/neura/v1 --token ... \\
        --role-map cloud-prod [--runs 3]

Every reply is stored in the conversation, the fixed handover sentence too, and the
router reads the history on the shopper's next message. A20 measured what that can
do: the old handover words in the history made CARE's router score 0.00 on every
later message (on a small local model). ADR-0062 changed those words, so this asks
the question again, for CARE and SELL, on a real shop and real models:

    a handover's words in the history, then an ordinary question: is it answered?

Each case is run with the new words in the history (the first handover's *ask*, and
the *your question is with our store* sentence), and once with no history at all as
the control. **Nothing is written to the shop** (every tool reads; ADR-0010) and
nothing to the database: the graph runs in memory, as the eval harness runs it, with
the history the turn service would load.

Read the replies, not only the ticks.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from neura_adapters.generic import GenericAdapter
from neura_agent_care.manifest import MANIFEST as CARE
from neura_agent_care.serving import build_runner as care_runner
from neura_agent_core.serving import AgentRunner, TurnRequest
from neura_agent_sell.manifest import MANIFEST as SELL
from neura_agent_sell.serving import build_runner as sell_runner
from neura_core import configure_logging, load_env, new_id
from neura_core.ids import CONVERSATION
from neura_core.tenancy import TenantConfig, handover_ask_message, handover_with_store_message
from neura_llm import LLMClient, ModelRole

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
OFF = "\033[0m"

TENANT = "tn_handover_history_check"

#: The shop's details as an owner would set them, so the history holds the
#: contact line as well, exactly as the turn service writes it.
CONTACT = TenantConfig(contact_email="hello@yourshop.example", contact_phone="+94 11 234 5678")
HANDED_OVER = "Can you cancel my order and refund it?"


@dataclass(frozen=True, slots=True)
class Case:
    agent: str
    question: str
    history: str  # "ask", "with_store" or "none"


CASES = [
    Case("care", "Do you have green tea?", "ask"),
    Case("care", "Do you have green tea?", "with_store"),
    Case("care", "Do you have green tea?", "none"),
    Case("sell", "I'd like a tea for the morning. What do you suggest?", "ask"),
    Case("sell", "I'd like a tea for the morning. What do you suggest?", "with_store"),
    Case("sell", "I'd like a tea for the morning. What do you suggest?", "none"),
]


def history_for(kind: str) -> list[dict[str, str]]:
    if kind == "none":
        return []
    words = handover_ask_message(CONTACT) if kind == "ask" else handover_with_store_message(CONTACT)
    return [{"role": "shopper", "content": HANDED_OVER}, {"role": "agent", "content": words}]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--role-map", default="cloud-prod")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--only", default="", help="one case, as agent:history, e.g. sell:ask (no control then)"
    )
    args = parser.parse_args()
    cases = [c for c in CASES if not args.only or f"{c.agent}:{c.history}" == args.only]

    load_env()
    configure_logging()
    llm = LLMClient.from_role_map_name(args.role_map)
    adapter = GenericAdapter(base_url=args.url, tenant_id=TENANT, token=args.token)
    capabilities = (await adapter.health()).capabilities
    runners: dict[str, tuple[AgentRunner, frozenset[str]]] = {
        "care": (care_runner(), CARE.scopes),
        "sell": (sell_runner(), SELL.scopes),
    }

    print(f"\n  role map  {args.role_map}   router {llm.model_for(ModelRole.ROUTER)}")
    print(f"  {DIM}a handover's words in the history, then an ordinary question{OFF}\n")

    answered: dict[tuple[str, str], int] = {}
    try:
        for case in cases:
            runner, scopes = runners[case.agent]
            runs = 1 if case.history == "none" else args.runs
            for _ in range(runs):
                outcome = await runner.run(
                    TurnRequest(
                        tenant_id=TENANT,
                        conversation_id=new_id(CONVERSATION),
                        message=case.question,
                        adapter=adapter,
                        llm=llm,
                        capabilities=capabilities,
                        scopes=scopes,
                        history=history_for(case.history),
                    )
                )
                ok = not outcome.escalated and bool(outcome.reply.strip())
                key = (case.agent, case.history)
                answered[key] = answered.get(key, 0) + (1 if ok else 0)
                mark = f"{GREEN}✔ answered{OFF}" if ok else f"{RED}✘ handed over{OFF}"
                reply = " ".join(outcome.reply.split())[:110]
                print(f"  {case.agent:<4} {case.history:<10} {mark}  {DIM}{reply}{OFF}")
    finally:
        await adapter.aclose()

    print()
    failed = False
    for case in cases:
        runs = 1 if case.history == "none" else args.runs
        got = answered.get((case.agent, case.history), 0)
        print(f"  {case.agent:<4} {case.history:<10} {got} of {runs} answered")
        failed = failed or (case.history != "none" and got < runs)
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
