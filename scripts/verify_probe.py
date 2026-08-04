#!/usr/bin/env python3
"""Open question A8 — is `verify`'s verdict stable under a change that carries no meaning?

    make verify-probe                       # local, free
    make verify-probe MODEL=nvidia/nemotron-nano-9b-v2:free CLOUD=1
    make verify-probe MODEL=openai/gpt-oss-20b:free CLOUD=1

**Why this file exists at all, before what it measures.** On 2026-07-29 twenty hand
probes found `verify` refusing a supported claim 30 times out of 30 when a second,
meaningless evidence block was added — and 0 times out of 30 without it. The exact
strings were never written down. When the finding was revisited on 2026-08-02 the probe
had to be *reconstructed*, and the reconstruction found nothing, which left two
explanations that could not be separated: a better model, or a gentler probe. That
ambiguity cost a session and is still costing one.

So the strings live here, in the repository, under version control. Whatever this
measures, the next person measures the same thing.

## What it does

One draft, one claim, and the claim is **supported by the evidence in both conditions**:

    A  the evidence, once
    B  the same evidence, repeated verbatim

`grounded=true` is the correct answer to both. Any `false` is a false refusal, and the
whole question is whether the *rate* of false refusals moves between A and B — because
nothing that could change a correct verdict has changed. Duplicating text adds no fact,
removes no fact, and contradicts nothing.

## What it does not do

It does not decide anything. It is a measurement of one node against one pair of inputs,
and a difference here is a hint about `verify`, not a verdict on the agent — the golden
suite is what measures the agent. It also makes **no groundedness claim**: the judge is
not involved, and E2b is explicit that a judge is what would be needed for one.

The real `verify` prompt and the real `Groundedness` schema are used, through the real
`LLMClient`. A probe that reimplemented the check would measure the probe.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field

from neura_agent_care.prompts import load_prompts
from neura_agent_core.graph.nodes.verify import PROMPT_NAME, Groundedness
from neura_core import configure_logging, load_env
from neura_llm import ChatRequest, LLMClient, Message, ModelRole

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
OFF = "\033[0m"


#: The evidence block. A tool result of the shape `act` produces, with the values a
#: real order carries: a status, a date, a carrier and a tracking number.
EVIDENCE_BLOCK = """<tool_result name="get_order_status">
order_ref: 1001
status: shipped
shipped_on: 2026-07-22
carrier: DHL
tracking_number: TRK123456
items: 1 x Waterproof Hiking Shoe (UK 9)
</tool_result>"""


#: The draft. **Every claim in it appears in the evidence above**, and that is the
#: property the whole probe rests on — checked by hand, and re-checkable by anyone
#: reading these two strings side by side:
#:
#:   "shipped"     ← status: shipped
#:   "22 July"     ← shipped_on: 2026-07-22
#:   "DHL"         ← carrier: DHL
#:   "TRK123456"   ← tracking_number: TRK123456
#:
#: It states nothing else. No delivery estimate, no reassurance, no promise.
DRAFT = "Your order #1001 shipped on 22 July with DHL, and the tracking number is TRK123456."


#: A draft with one claim the evidence does **not** contain. Everything else is
#: identical to `DRAFT`; the delivery date is invented.
#:
#: This is the probe's negative control, and without it the whole file is
#: worthless. Two arms that both answer "grounded" prove stability only if the
#: verifier is capable of answering "not grounded" — otherwise a model that
#: says yes to everything scores a perfect 0/10 and looks like the best verifier
#: we have. A probe that cannot fail is not a measurement.
FABRICATED_DRAFT = (
    "Your order #1001 shipped on 22 July with DHL, tracking TRK123456, "
    "and it will be delivered on 25 July."
)

#: A claim the evidence **contradicts**: the order is `shipped`, not delivered.
#:
#: The pair C/D separates two failures that are easy to run together and are not
#: equally dangerous. C *adds* a plausible fact to otherwise-supported text; D
#: *changes* one. A verifier that catches D and misses C is not half-working — it
#: is missing the direction that matters, because inventing a delivery date is
#: exactly the confident-wrong-answer this node exists to stop.
CONTRADICTED_DRAFT = "Your order #1001 was delivered on 22 July by DHL, tracking TRK123456."


@dataclass(slots=True)
class Condition:
    """One arm of the probe."""

    name: str
    evidence: str
    note: str
    #: What a correct verifier answers. A8 is about the two arms where this is
    #: ``True`` moving relative to each other; the arm where it is ``False``
    #: exists to prove the verifier can move at all.
    expect_grounded: bool = True
    draft: str = ""


#: The two arms. B is A twice, joined the way `evidence_of` joins two tool results —
#: a blank line — so the difference is exactly "one block or two identical blocks"
#: and not "one block or one block with unusual whitespace".
CONDITIONS = (
    Condition(
        name="A · one evidence block",
        evidence=EVIDENCE_BLOCK,
        note="the ordinary case — expect grounded",
    ),
    Condition(
        name="B · the same block, twice",
        evidence=f"{EVIDENCE_BLOCK}\n\n{EVIDENCE_BLOCK}",
        note="adds no fact, removes no fact — expect grounded",
    ),
    Condition(
        name="C · control: an ADDED fact (invented delivery date)",
        evidence=EVIDENCE_BLOCK,
        note="expect NOT grounded — proves the verifier can say no",
        expect_grounded=False,
        draft=FABRICATED_DRAFT,
    ),
    Condition(
        name="D · control: a CONTRADICTED fact (delivered, not shipped)",
        evidence=EVIDENCE_BLOCK,
        note="expect NOT grounded — the prompt names this one by example",
        expect_grounded=False,
        draft=CONTRADICTED_DRAFT,
    ),
)


@dataclass(slots=True)
class Outcome:
    """What one arm produced."""

    refusals: int = 0
    runs: int = 0
    api_calls: int = 0
    errors: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.refusals / self.runs if self.runs else 0.0


async def _ask(llm: LLMClient, prompt: str, evidence: str, draft: str) -> tuple[Groundedness, int]:
    """One `verify` call, built exactly as the node builds it."""
    request = ChatRequest(
        messages=[
            Message.system(prompt),
            Message.user(f"EVIDENCE:\n{evidence}\n\nDRAFT REPLY:\n{draft}"),
        ],
        temperature=0.0,
    )
    result = await llm.chat_structured(ModelRole.GUARD, request, Groundedness)
    return result.value, int(getattr(result, "attempts", 1))


async def run_condition(llm: LLMClient, prompt: str, condition: Condition, n: int) -> Outcome:
    outcome = Outcome()
    draft = condition.draft or DRAFT
    for index in range(n):
        try:
            verdict, attempts = await _ask(llm, prompt, condition.evidence, draft)
        except Exception as exc:
            # Counted, never scored as a refusal. A provider that refused to
            # answer is not a verifier that said no, and conflating them is the
            # E6 mistake — a dead server reported as agent failure.
            outcome.errors += 1
            outcome.runs += 1
            print(f"    {YELLOW}!{OFF} run {index + 1}: {type(exc).__name__}: {str(exc)[:120]}")
            continue

        outcome.runs += 1
        outcome.api_calls += attempts
        if not verdict.grounded:
            outcome.refusals += 1
            outcome.reasons.append(verdict.unsupported_claim or "(no claim quoted)")
        wrong = verdict.grounded is not condition.expect_grounded
        mark = f"{RED}✘{OFF}" if wrong else f"{GREEN}✔{OFF}"
        said = "grounded" if verdict.grounded else f"refused — {verdict.unsupported_claim[:80]}"
        print(f"    {mark} run {index + 1}: {said}")
    return outcome


async def run(*, role_map: str, model: str | None, n: int) -> int:
    if model:
        # The GUARD role is what `verify` uses. Overridden here rather than in
        # `.env` so one command can probe several models in a session without
        # editing configuration between them.
        os.environ["OLLAMA_MODEL_GUARD" if role_map == "ollama-dev" else "CLOUD_MODEL_GUARD"] = (
            model
        )

    llm = LLMClient.from_role_map_name(role_map)
    prompt = load_prompts()[PROMPT_NAME]
    verifier = llm.model_for(ModelRole.GUARD)

    print(f"\n  {BOLD}A8 — verify stability under a meaning-free change{OFF}")
    print(f"  {DIM}verifier   {verifier}  ({role_map}){OFF}")
    print(f"  {DIM}runs       {n} per condition · temperature 0.0{OFF}")
    print(f"  {DIM}claim      supported in BOTH conditions — every refusal is a false one{OFF}\n")

    results: dict[str, Outcome] = {}
    for condition in CONDITIONS:
        print(f"  {BOLD}{condition.name}{OFF}  {DIM}({condition.note}){OFF}")
        results[condition.name] = await run_condition(llm, prompt, condition, n)
        print()

    print(f"  {BOLD}RESULT{OFF}")
    total_calls = 0
    for condition in CONDITIONS:
        outcome = results[condition.name]
        total_calls += outcome.api_calls
        wrong = outcome.refusals if condition.expect_grounded else outcome.runs - outcome.refusals
        marker = RED if wrong else GREEN
        label = "false refusals" if condition.expect_grounded else "missed fabrications"
        print(
            f"    {marker}{wrong}/{outcome.runs}{OFF} {label}   {condition.name}"
            + (f"   {YELLOW}({outcome.errors} errored){OFF}" if outcome.errors else "")
        )

    a, b, control, contradiction = (results[c.name] for c in CONDITIONS)

    if control.runs and control.refusals == 0 and contradiction.refusals:
        print(
            f"\n  {RED}THIS VERIFIER MISSES ADDED FACTS.{OFF} It caught a contradicted status"
            f" {contradiction.refusals}/{contradiction.runs} times and let an invented"
            f" delivery date through {control.runs}/{control.runs} times."
        )
        print(
            f"  {DIM}That is the worse half to miss. Contradicting the evidence is a"
            f" mistake a shopper may spot; adding a plausible date to otherwise correct"
            f" text is the confident wrong answer this node exists to stop.{OFF}\n"
        )
        return 1

    if control.runs and control.refusals == 0:
        print(
            f"\n  {RED}THE PROBE IS NOT MEASURING ANYTHING.{OFF} This verifier called an"
            f" invented delivery date grounded in {control.runs}/{control.runs} runs."
        )
        print(
            f"  {DIM}A model that says yes to everything scores a perfect 0/10 on A and B."
            f" Neither number above is evidence of stability.{OFF}\n"
        )
        return 1
    print(f"\n  {DIM}{total_calls} model calls used.{OFF}")

    if a.errors or b.errors or control.errors or contradiction.errors:
        print(
            f"\n  {YELLOW}Some runs never reached the model. This is NOT a result —"
            f" a provider outage is not a verdict (open question E6).{OFF}\n"
        )
        return 1

    swing = abs(b.rate - a.rate)
    if swing >= 0.5:
        print(
            f"\n  {RED}The verdict moved {a.refusals}/{a.runs} → {b.refusals}/{b.runs} on a change"
            f" that carries no meaning.{OFF}"
        )
        print(
            f"  {DIM}A8 reproduces on this verifier. Whatever else is true, this model is"
            f" unsuitable for the GUARD role.{OFF}\n"
        )
    elif a.refusals == 0 and b.refusals == 0:
        print(f"\n  {GREEN}Stable on this verifier: no false refusal in either condition.{OFF}")
        print(
            f"  {DIM}That is evidence about THIS model and these strings, and nothing more."
            f" A probe that finds nothing on every model it is pointed at is a probe that"
            f" cannot find anything.{OFF}\n"
        )
    else:
        print(f"\n  {YELLOW}Mixed: {a.refusals}/{a.runs} → {b.refusals}/{b.runs}.{OFF}")
        print(f"  {DIM}Neither stable nor a clean flip. Raise n before concluding.{OFF}\n")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role-map",
        default="ollama-dev",
        help="ollama-dev (free, local) or cloud-prod (spends API quota)",
    )
    parser.add_argument("--model", default=None, help="Override the GUARD model")
    parser.add_argument(
        "-n",
        type=int,
        default=10,
        help="Runs per condition. 10 costs 20 calls — the whole of a 50/day free tier "
        "is two models plus change.",
    )
    args = parser.parse_args()

    load_env()
    configure_logging(level="ERROR", json_output=False)
    sys.exit(asyncio.run(run(role_map=args.role_map, model=args.model, n=args.n)))


if __name__ == "__main__":
    main()
