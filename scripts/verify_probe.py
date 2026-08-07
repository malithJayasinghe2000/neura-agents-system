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
    """What one arm produced.

    **``answered`` is the only honest denominator, and getting that wrong is how
    this file shipped a false result on 2026-08-04.** A run where the provider
    timed out is not a run where the verifier said anything. Dividing by
    ``attempted`` counted five unreachable calls as five missed fabrications and
    printed a confident verdict about a model that had not been asked — which is
    open question **E6** exactly, reintroduced in the reporting layer of the
    script written to avoid it. A "not measured" value has to be its own thing,
    everywhere, or it silently becomes a measurement.
    """

    refusals: int = 0
    attempted: int = 0
    api_calls: int = 0
    errors: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def answered(self) -> int:
        """Runs the model actually returned a verdict for."""
        return self.attempted - self.errors

    def wrong(self, *, expect_grounded: bool) -> int:
        """Verdicts that disagree with the correct answer. Errors are not verdicts."""
        return self.refusals if expect_grounded else self.answered - self.refusals


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


#: Seconds to wait between calls when the provider is a hosted free tier.
#:
#: Free tiers throttle per minute as well as per day, and the edge drops the
#: excess at the *connection* level rather than returning 429 — which arrives as
#: `APIConnectionError` and reads as "the network is broken". Measured
#: 2026-08-07: unpaced, the first two calls of each arm answered and the rest
#: never landed, which the reporting correctly refused to score. Pacing costs a
#: few minutes and buys a run that completes.
CLOUD_PACE_S = 8.0


async def run_condition(
    llm: LLMClient, prompt: str, condition: Condition, n: int, *, pace_s: float = 0.0
) -> Outcome:
    outcome = Outcome()
    draft = condition.draft or DRAFT
    for index in range(n):
        if pace_s and index:
            await asyncio.sleep(pace_s)
        try:
            verdict, attempts = await _ask(llm, prompt, condition.evidence, draft)
        except Exception as exc:
            # Counted, never scored as a refusal. A provider that refused to
            # answer is not a verifier that said no, and conflating them is the
            # E6 mistake — a dead server reported as agent failure.
            outcome.errors += 1
            outcome.attempted += 1
            print(f"    {YELLOW}!{OFF} run {index + 1}: {type(exc).__name__}: {str(exc)[:120]}")
            continue

        outcome.attempted += 1
        outcome.api_calls += attempts
        if not verdict.grounded:
            outcome.refusals += 1
            outcome.reasons.append(verdict.unsupported_claim or "(no claim quoted)")
        wrong = verdict.grounded is not condition.expect_grounded
        mark = f"{RED}✘{OFF}" if wrong else f"{GREEN}✔{OFF}"
        said = "grounded" if verdict.grounded else f"refused — {verdict.unsupported_claim[:80]}"
        print(f"    {mark} run {index + 1}: {said}")
    return outcome


async def run(*, role_map: str, model: str | None, n: int, pace_s: float | None) -> int:
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
    pace = CLOUD_PACE_S if pace_s is None and role_map != "ollama-dev" else (pace_s or 0.0)

    print(f"\n  {BOLD}A8 — verify stability under a meaning-free change{OFF}")
    print(f"  {DIM}verifier   {verifier}  ({role_map}){OFF}")
    print(
        f"  {DIM}runs       {n} per condition · temperature 0.0"
        + (f" · {pace:g}s between calls" if pace else "")
        + f"{OFF}"
    )
    print(f"  {DIM}claim      supported in BOTH conditions — every refusal is a false one{OFF}\n")

    results: dict[str, Outcome] = {}
    for condition in CONDITIONS:
        print(f"  {BOLD}{condition.name}{OFF}  {DIM}({condition.note}){OFF}")
        results[condition.name] = await run_condition(llm, prompt, condition, n, pace_s=pace)
        print()

    print(f"  {BOLD}RESULT{OFF}")
    total_calls = sum(o.api_calls for o in results.values())
    total_errors = sum(o.errors for o in results.values())

    for condition in CONDITIONS:
        outcome = results[condition.name]
        wrong = outcome.wrong(expect_grounded=condition.expect_grounded)
        label = "false refusals" if condition.expect_grounded else "missed fabrications"
        if outcome.answered == 0:
            body = f"    {YELLOW}not measured{OFF}   {condition.name}"
        else:
            marker = RED if wrong else GREEN
            body = f"    {marker}{wrong}/{outcome.answered}{OFF} {label}   {condition.name}"
        print(
            body
            + (
                f"   {YELLOW}({outcome.errors} never reached the model){OFF}"
                if outcome.errors
                else ""
            )
        )

    print(f"\n  {DIM}{total_calls} model calls answered.{OFF}")

    # Errors are checked BEFORE any interpretation, and they end the run. An
    # arm that did not complete cannot be compared with one that did, and a
    # partial arm dressed up as a result is worse than no run at all — it is
    # the 2026-07-31 failure where a dead Ollama was reported as intent
    # accuracy 0.00 (open question E6).
    if total_errors:
        print(
            f"  {YELLOW}{total_errors} run(s) never reached the model, so THIS IS NOT A"
            f" RESULT.{OFF}"
        )
        print(
            f"  {DIM}Re-run when the provider is healthy. Nothing above is comparable"
            f" with a complete run.{OFF}\n"
        )
        return 1

    a, b, added, contradicted = (results[c.name] for c in CONDITIONS)
    controls_caught = added.refusals + contradicted.refusals

    if controls_caught == 0:
        print(
            f"\n  {RED}THE PROBE IS NOT MEASURING ANYTHING ON THIS VERIFIER.{OFF} It called"
            f" both an invented delivery date and a contradicted status grounded, every time."
        )
        print(
            f"  {DIM}A model that says yes to everything scores a perfect 0 on A and B."
            f" Neither number above is evidence of stability — it is evidence this model"
            f" cannot hold the GUARD role (open question A10).{OFF}\n"
        )
        return 1

    if added.refusals == 0:
        print(
            f"\n  {RED}THIS VERIFIER MISSES ADDED FACTS.{OFF} It caught a contradicted status"
            f" {contradicted.refusals}/{contradicted.answered} times and let an invented"
            f" delivery date through every time."
        )
        print(
            f"  {DIM}That is the worse half to miss. Contradicting the evidence is a mistake"
            f" a shopper may spot; adding a plausible date to otherwise correct text is the"
            f" confident wrong answer this node exists to stop.{OFF}\n"
        )
        return 1

    swing = abs(b.wrong(expect_grounded=True) - a.wrong(expect_grounded=True))
    if swing >= max(1, a.answered // 2):
        print(
            f"\n  {RED}The verdict moved {a.refusals}/{a.answered} → {b.refusals}/{b.answered}"
            f" on a change that carries no meaning.{OFF}"
        )
        print(f"  {DIM}A8 reproduces on this verifier.{OFF}\n")
        return 1

    print(f"\n  {GREEN}Fit for the GUARD role on these strings.{OFF}")
    print(
        f"  {DIM}Both controls refused, and A and B agree — so the 0/{a.answered} above is"
        f" a verifier that can say no and chose not to, which is the only reading worth"
        f" anything. Evidence about THIS model and THESE strings, and nothing more.{OFF}\n"
    )
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
    parser.add_argument(
        "--pace-s",
        type=float,
        default=None,
        help=f"Seconds between calls. Defaults to 0 locally and {CLOUD_PACE_S:g} for a "
        "hosted provider, because free tiers throttle per minute and drop the excess "
        "at the connection level rather than returning 429.",
    )
    args = parser.parse_args()

    load_env()
    configure_logging(level="ERROR", json_output=False)
    sys.exit(
        asyncio.run(run(role_map=args.role_map, model=args.model, n=args.n, pace_s=args.pace_s))
    )


if __name__ == "__main__":
    main()
