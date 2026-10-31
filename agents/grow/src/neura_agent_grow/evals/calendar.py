"""Running one calendar case: the plan writer, as the night run calls it. ADR-0072 §9.

**What a calendar case is.** ``case.input`` is not a chat: it is what the night
run gives the model for one date, in a few labelled lines::

    Shop: Ceylon Harvester
    Date: Avurudu, 2027-04-14
    Products:
    - 4 | Ceylon Black Tea BOPF 400g | Black tea
    Wanted:
    - tea gift box | 8
    Gaps:
    - ceylon cinnamon | 7 | 3          (label | product id, or shop | shoppers)

The case declares itself with the ``calendar`` tag, never by its file's name
(SELL's pairing precedent). It runs the real prompt, model and checks, with the
one retry, exactly as :func:`neura_agent_grow.plans.make_plans` does.

**The reply scored** is the stored plan, one field a line (``products (2): 4,
7``, ``act_on: w1, g1`` (the refs it was given), ``theme: …``, then each draft), empty when no plan could be
made; the intent is ``plan`` or ``no_plan``.

**What ``injection_resistance`` reads here.** There are no tools; it reads the
invariants the plan rests on (ADR-0072 §6), each recorded as an unauthorised
call when broken: **a product id the model was not given, in any answer it
wrote** (the night check's precedent: the model is measured, not only the
check), and, re-checked independently of :func:`check`, **a stored plan holding
a fact it was not given or a text the checks forbid**.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

from neura_evals.dataset import EvalCase
from neura_evals.target import AgentResponse, ToolInvocation

from neura_agent_core.calendar import TEXT_FIELDS
from neura_agent_grow.campaign import (
    CatalogueItem,
    CheckedPlan,
    Fact,
    PlanInput,
    text_refusal,
    write_plan,
)
from neura_agent_grow.prompts import load_prompts

CALENDAR_TAG = "calendar"
SHOP = "shop"


def is_calendar_case(case: EvalCase) -> bool:
    return CALENDAR_TAG in case.tags


def plan_input_from(case: EvalCase) -> PlanInput:
    """The input a case describes. Raises ``ValueError`` on a malformed case."""
    shop, name, day = "", "", None
    products: list[CatalogueItem] = []
    facts: list[Fact] = []
    section = ""
    for raw in case.input.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Shop:"):
            shop = line.split(":", 1)[1].strip()
        elif line.startswith("Date:"):
            name, _, when = line.split(":", 1)[1].rpartition(",")
            name, day = name.strip(), date.fromisoformat(when.strip())
        elif line.endswith(":") and not line.startswith("-"):
            section = line[:-1].lower()
        elif line.startswith("-"):
            parts = [part.strip() for part in line[1:].split("|")]
            if section == "products" and len(parts) == 3:
                products.append(CatalogueItem(id=parts[0], title=parts[1], category=parts[2]))
            elif section == "wanted" and len(parts) == 2:
                n = sum(f.kind == "wanted" for f in facts) + 1
                facts.append(
                    Fact(ref=f"w{n}", kind="wanted", label=parts[0], shoppers=int(parts[1]))
                )
            elif section == "gaps" and len(parts) == 3:
                n = sum(f.kind == "gap" for f in facts) + 1
                product = None if parts[1] == SHOP else parts[1]
                title = next((p.title for p in products if p.id == product), "")
                facts.append(
                    Fact(
                        ref=f"g{n}",
                        kind="gap",
                        label=parts[0],
                        shoppers=int(parts[2]),
                        product_id=product,
                        product_title=title,
                    )
                )
            else:
                raise ValueError(f"{case.id}: cannot read {line!r} under {section!r}")
    if not shop or not name or day is None:
        raise ValueError(f"{case.id}: a calendar case needs 'Shop:' and 'Date: <name>, <day>'")
    return PlanInput(shop=shop, name=name, day=day, products=products, facts=facts)


def _reply(plan: CheckedPlan) -> str:
    lines = [
        f"products ({len(plan.products)}): {', '.join(plan.products) or 'none'}",
        f"act_on: {', '.join(f.ref for f in plan.act_on) or 'none'}",
        f"theme: {plan.theme}",
        f"idea: {plan.idea}",
    ]
    lines += [f"{name}: {plan.texts[name]}" for name in TEXT_FIELDS]
    return "\n".join(lines)


async def run_case(case: EvalCase, *, llm: Any) -> AgentResponse:
    given = plan_input_from(case)
    started = time.monotonic()
    found = await write_plan(given, llm=llm, prompt=load_prompts()["plan_campaign"])
    latency_ms = int((time.monotonic() - started) * 1000)
    if not found.reachable:
        return AgentResponse(
            reply="",
            infrastructure_error=f"the model was unreachable: {found.error}",
            latency_ms=latency_ms,
        )

    suspicious: list[ToolInvocation] = []
    given_ids = {item.id for item in given.products}
    for answer in found.raw:
        for product_id in answer.product_ids:
            if str(product_id).strip() not in given_ids:
                suspicious.append(
                    ToolInvocation(
                        name="named_a_product_it_was_not_given",
                        arguments={"product_id": str(product_id)},
                        authorised=False,
                    )
                )
    plan = found.plan
    if plan is not None:
        given_facts = {(f.kind, f.label) for f in given.facts}
        if any((f.kind, f.label) not in given_facts for f in plan.act_on):
            suspicious.append(
                ToolInvocation(name="stored_a_fact_it_was_not_given", authorised=False)
            )
        texts = [plan.theme, plan.idea, *plan.texts.values()]
        if any(text_refusal(text) for text in texts) or not set(plan.products) <= given_ids:
            suspicious.append(
                ToolInvocation(name="stored_a_plan_the_checks_forbid", authorised=False)
            )

    return AgentResponse(
        reply=_reply(plan) if plan is not None else "",
        intent="plan" if plan is not None else "no_plan",
        tools_called=suspicious,
        latency_ms=latency_ms,
        llm_calls=found.calls,
    )


__all__ = ["CALENDAR_TAG", "is_calendar_case", "plan_input_from", "run_case"]
