"""Catching a promise the agent cannot keep.

Open question **A9(3)**, and the part of A9 that a groundedness judge is
structurally incapable of finding. Measured on the live shop, 2026-07-29 — asked
about returning a swimsuit, CARE replied:

    "Your swimsuit is in the 30-day return window, but we cannot accept returns
     for hygiene reasons. Let me know your order number and I'll send you a
     prepaid return label."

It refuses the return and offers to process it in the same breath, and it
promises a future action in a turn that has no later. There is no second turn, no
notification service, and no WRITE tool (ADR-0010). The promise is simply false.

**Groundedness cannot see this, and that is the whole point.** The store's Return
Policy is written in the first person — *"We will send a prepaid label"* — so the
model re-voiced the merchant's own prose as its own commitment, and every word of
it *is* supported by the evidence. A judge asked "is this claim in the evidence?"
answers yes, correctly. A promise is not a claim about the world.

That is also why this can be measured **without a judge**, which matters: open
question E2 says the judge cannot complete a run on a free tier, and the 1.12
decision made "the next attempt at A8 or A9" the trigger for paying. This half of
A9 does not need one — the defect is invisible to groundedness by construction,
so a groundedness score would not move whichever way this check goes. What moves
is escalation, and that is measured mechanically.

**`compose.md` already forbids this in bold, and the model did it anyway.** Rule
3 — *if your safety argument is "the prompt says not to", you have no argument* —
was written about authorisation, and 2026-07-29 showed it generalises to
correctness. A prompt is guidance; this is a check.

## The line the rules draw, and why it is drawn there

**First person singular only.** "I'll send you a label" is the agent committing.
"We will send a prepaid label once the return is approved" is the *merchant's*
process, quoted from a policy page — grounded, true, and useful. Banning "we"
would refuse a large fraction of correct policy answers, and "we" is genuinely
ambiguous between the store and the assistant. "I" is not ambiguous.

**Only actions that happen outside this turn.** "I can see your order shipped" is
present tense and true. "I'll check that for you" is not, because there is no
later in which to check. The verb list is what separates them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from neura_agent_core.guard.injection import Rule, normalise


def _re(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.VERBOSE)


#: Things that happen after this turn ends, or somewhere other than this reply.
#: Deliberately excludes `see`, `confirm`, `tell`, `explain`, `show`, `help` and
#: `find` — all of which the agent genuinely can do, in this turn, right now.
_OUT_OF_BAND = r"""
    send | email | e-mail
  | notify | alert | remind | contact | chase | follow \s+ up | get \s+ back
  | arrange | process | issue | refund | cancel | reschedule | book | schedule
  | reserve | apply | update | remove | add | forward | escalate | raise
  | log | file | investigate | verify | check | look \s+ into | look \s+ up
  | sort \s+ (?: it | this | that ) \s+ out
"""

#: Words that, standing immediately before one of the verbs above, prove it is
#: being used as a **noun**. This is the whole difference between "I'll process
#: the refund" and "I can explain how the returns *process* works".
#:
#: Every one of these was found by the benign half of `tests/unit/test_promises.py`
#: rather than by thinking about it. An ecommerce agent says "your order",
#: "the process", "a file" and "the log" constantly, and the first draft of this
#: rule flagged four clean drafts because of it — the exact over-refusal that
#: made the 2026-07-30 attempt score worse than doing nothing.
_DETERMINER = r"the | your | my | our | its | their | a | an | this | that | each | every | any"

#: Up to three words may sit between the commitment and the verb ("I'll happily
#: send…"), and **none of them may be a determiner**, which is what stops the
#: match reaching a noun.
_FILLER = rf"(?: \s+ (?! (?: {_DETERMINER} ) \b ) [\w'-]+ ){{0,3}}"

PROMISE_RULES: Final[tuple[Rule, ...]] = (
    Rule(
        name="first_person_promise",
        # "I'll send…", "let me check…", "I'm going to arrange…"
        #
        # No exemption for "let me know". It does not need one: `know` is not an
        # out-of-band verb, and the determiner guard stops the match running on
        # into "your **order** number". That matters more than it looks — the
        # sentence that raised A9(3) contains "Let me know your order number"
        # AND "I'll send you a prepaid return label", so a rule that fired on
        # the first half would have been right for entirely the wrong reason.
        pattern=_re(
            rf"""
            \b (?: i \s* (?: \u2019 | ' )? ll
                 | i \s+ will
                 | i \s* (?: \u2019 | ' )? m \s+ going \s+ to
                 | i \s+ shall
                 | i \s+ can
                 | i \s+ could
                 | let \s+ me
                 | allow \s+ me \s+ to
              )
            {_FILLER}
            \s+ \b (?: {_OUT_OF_BAND} ) \b
            """
        ),
        rationale=(
            "There is no later turn, no notification service and no WRITE tool, so a "
            "first-person commitment to act is false whatever the evidence says."
        ),
    ),
    Rule(
        name="offer_of_a_service_that_does_not_exist",
        # "Would you like me to check?", "Shall I email you when it's back?",
        # "Would you like to be notified?" — measured in milestone 1.11, twice.
        pattern=_re(
            rf"""
            \b (?: would \s+ you \s+ like \s+ me \s+ to
                 | do \s+ you \s+ want \s+ me \s+ to
                 | shall \s+ i
                 | should \s+ i
                 | happy \s+ to
              )
            {_FILLER}
            \s+ \b (?: {_OUT_OF_BAND} ) \b
            |
            \b (?: would \s+ you \s+ like | do \s+ you \s+ want | shall \s+ we )
            \b [^.!?\n]{{0,30}}
            \b (?: to \s+ be \s+ )? (?: notified | alerted | contacted | reminded | updated )
            \b
            """
        ),
        rationale=(
            "An offer is a promise with a question mark. Nothing in the MVP can notify "
            "anyone, so accepting the offer would strand the shopper waiting."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class Promise:
    """A commitment the agent cannot honour."""

    rule: str
    #: Safe to log and to put in a handoff — names the rule, never quotes the
    #: draft. The draft is already in the handoff packet in full.
    detail: str


def find_promises(draft: str) -> list[Promise]:
    """Every unkeepable commitment in a draft. Deterministic; no model.

    Returns a list rather than a bool so a handoff can say *which* rule fired —
    "the reply promised to send something" is a different conversation for a
    support person than "the reply offered a notification we do not have".
    """
    if not draft.strip():
        return []
    normalised = normalise(draft)
    return [
        Promise(rule.name, f"the reply {_PHRASING[rule.name]}")
        for rule in PROMISE_RULES
        if rule.matches(normalised)
    ]


_PHRASING: Final[dict[str, str]] = {
    "first_person_promise": "commits to doing something after this turn ends",
    "offer_of_a_service_that_does_not_exist": "offers a follow-up the system cannot perform",
}


__all__ = ["PROMISE_RULES", "Promise", "find_promises"]
