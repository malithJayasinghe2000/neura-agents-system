#!/usr/bin/env python3
"""Open question A11 — is the cloud `ROUTER` fast enough to sit on every turn?

    make router-probe                                    # the configured model
    make router-probe MODEL=meta-llama/llama-3.3-70b-instruct:free

**Why this exists.** Found on 2026-08-04 while running something else: two
`verify`-shaped structured calls against `nvidia/nemotron-nano-9b-v2:free` took
roughly **seven minutes each**, so a 20-call probe was abandoned rather than
completed. That model is configured as `CLOUD_MODEL_ROUTER`, and routing is on
the latency-critical path of **every** turn — so if it is really minutes per
call, `cloud-prod` is not a role map anybody can serve a shopper from, and the
Phase 1 exit criterion "evals green on both role maps" is unreachable for a
reason that has nothing to do with quality.

It is a *reasoning* model with neither `max_tokens` nor `reasoning_effort` set in
`cloud_prod()`, so it thinks without a budget — the gotcha already named in
AGENTS.md. This asks the only question that decides what to do about it:

    does capping the thinking budget make it usable, and does it still route?

## Why speed alone is not the measurement

Capping a reasoning model's budget is a **quality** change, not just a speed one:
a model cut off mid-thought can answer worse than one that never deliberated. So
every arm here also checks the answer. The five inputs below have one obvious
intent each — obvious to a person, which is the bar the router has to clear — and
an arm that gets faster while classifying worse has not fixed anything.

Latency is wall-clock per call, reported per arm rather than averaged into one
number, because a router with a good median and a two-minute tail is still a
router a shopper waits behind.

## What it does not do

It does not decide the role map. Five inputs are a screen, not a benchmark: the
golden suite is what measures routing accuracy, and running it on `cloud-prod`
costs roughly 190 model calls against a 50/day free tier (open question **E2b**).
This is the cheap thing that says whether that spend is worth planning at all.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field

from neura_agent_care.nodes.route import Route
from neura_agent_care.prompts import load_prompts
from neura_core import configure_logging, load_env
from neura_llm import ChatRequest, LLMClient, Message, ModelRole

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
OFF = "\033[0m"

#: Five shopper messages with one defensible intent each. Deliberately not the
#: hard cases: this asks whether a model can route at all under a budget cap, and
#: an ambiguous input would make a slow arm look wrong for the wrong reason.
CASES: tuple[tuple[str, str], ...] = (
    ("where is my order 1001?", "order_status"),
    ("do you have the hiking shoe in UK 9?", "product_qa"),
    ("how long do I have to return something?", "policy_qa"),
    ("I want to speak to a human about a complaint", "needs_person"),
    ("what is the capital of France?", "out_of_scope"),
)

#: Seconds a single routing call may take before the arm is abandoned. A router
#: is on the latency path of every turn; one that needs longer than this is not
#: a candidate, and waiting out five of them proves nothing new.
PER_CALL_TIMEOUT_S = 90.0


@dataclass(slots=True)
class Arm:
    """One configuration of the same model."""

    name: str
    note: str
    reasoning_effort: str | None = None
    max_tokens: int | None = None


ARMS = (
    Arm(name="as configured", note="no budget — what `cloud_prod()` does today"),
    Arm(
        name="reasoning_effort=none",
        note="ask it not to deliberate",
        reasoning_effort="none",
    ),
    Arm(name="max_tokens=512", note="hard ceiling instead", max_tokens=512),
)


@dataclass(slots=True)
class Outcome:
    latencies: list[float] = field(default_factory=list)
    correct: int = 0
    answered: int = 0
    timeouts: int = 0
    errors: int = 0

    @property
    def slowest(self) -> float:
        return max(self.latencies) if self.latencies else 0.0

    @property
    def median(self) -> float:
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        return ordered[len(ordered) // 2]


async def run_arm(llm: LLMClient, prompt: str, arm: Arm) -> Outcome:
    outcome = Outcome()

    for message, expected in CASES:
        request = ChatRequest(
            messages=[Message.system(prompt), Message.user(message)],
            temperature=0.0,
            reasoning_effort=arm.reasoning_effort,
            max_tokens=arm.max_tokens,
        )
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                llm.chat_structured(ModelRole.ROUTER, request, Route),
                timeout=PER_CALL_TIMEOUT_S,
            )
        except TimeoutError:
            # Counted, never scored. A call that never came back is not a
            # classification, and treating it as a wrong one would report a
            # slow model as an inaccurate one — the E6 mistake in a new hat.
            outcome.timeouts += 1
            elapsed = time.monotonic() - started
            print(f"    {YELLOW}!{OFF} {message[:40]:<42} timed out after {elapsed:.0f}s")
            continue
        except Exception as exc:
            outcome.errors += 1
            print(f"    {YELLOW}!{OFF} {message[:40]:<42} {type(exc).__name__}: {str(exc)[:60]}")
            continue

        elapsed = time.monotonic() - started
        outcome.answered += 1
        outcome.latencies.append(elapsed)
        got = result.value.intent
        ok = got == expected
        outcome.correct += int(ok)
        mark = f"{GREEN}✔{OFF}" if ok else f"{RED}✘{OFF}"
        print(f"    {mark} {message[:40]:<42} {got:<14} {elapsed:6.1f}s")

    return outcome


async def run(*, model: str | None, role_map: str) -> int:
    if model:
        os.environ["CLOUD_MODEL_ROUTER" if role_map != "ollama-dev" else "OLLAMA_MODEL_ROUTER"] = (
            model
        )

    llm = LLMClient.from_role_map_name(role_map)
    prompt = load_prompts()["route"]
    router = llm.model_for(ModelRole.ROUTER)

    print(f"\n  {BOLD}A11 — can this model hold the ROUTER role?{OFF}")
    print(f"  {DIM}router     {router}  ({role_map}){OFF}")
    print(f"  {DIM}cases      {len(CASES)} per arm · temperature 0.0{OFF}")
    print(f"  {DIM}timeout    {PER_CALL_TIMEOUT_S:g}s per call — longer than that is not a{OFF}")
    print(f"  {DIM}           candidate for a node on every turn{OFF}\n")

    results: dict[str, Outcome] = {}
    for arm in ARMS:
        print(f"  {BOLD}{arm.name}{OFF}  {DIM}({arm.note}){OFF}")
        results[arm.name] = await run_arm(llm, prompt, arm)
        print()

    print(f"  {BOLD}RESULT{OFF}")
    for arm in ARMS:
        outcome = results[arm.name]
        if outcome.answered == 0:
            detail = f"{YELLOW}not measured{OFF}"
        else:
            detail = (
                f"{outcome.correct}/{outcome.answered} routed · "
                f"median {outcome.median:.1f}s · slowest {outcome.slowest:.1f}s"
            )
        unfinished = outcome.timeouts + outcome.errors
        suffix = f"   {YELLOW}({unfinished} never answered){OFF}" if unfinished else ""
        print(f"    {arm.name:<24} {detail}{suffix}")

    print()
    usable = [
        arm.name
        for arm in ARMS
        if results[arm.name].answered == len(CASES) and results[arm.name].correct == len(CASES)
    ]
    if not usable:
        print(
            f"  {RED}No arm both answered and routed every case.{OFF} On this evidence the"
            f" model does not hold the ROUTER role — and capping its budget did not rescue it."
        )
        return 1

    print(
        f"  {GREEN}Usable on these five inputs:{OFF} {', '.join(usable)}."
        f"\n  {DIM}Five inputs are a screen, not a benchmark. Routing accuracy is a golden-suite"
        f" number, and the suite on this role map costs ~190 calls (E2b).{OFF}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role-map", default="cloud-prod")
    parser.add_argument("--model", default=None, help="Override the ROUTER model")
    args = parser.parse_args()

    load_env()
    configure_logging(level="ERROR", json_output=False)
    sys.exit(asyncio.run(run(model=args.model, role_map=args.role_map)))


if __name__ == "__main__":
    main()
