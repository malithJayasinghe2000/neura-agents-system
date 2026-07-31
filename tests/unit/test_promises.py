"""The promise detector's balanced corpus.

Open question A9(3). Thirty drafts that promise something the agent cannot do,
thirty that do not — **equal by construction**, for the reason
`tests/unit/test_guard.py` spells out at length: a corpus assembled from failures
measures sensitivity and cannot measure specificity, and reading it as overall
quality is how a change that makes things worse ships with a number attached.

The two halves are not symmetric in what they cost:

* **A false positive escalates a good answer.** That is the failure mode of the
  reverted 2026-07-30 attempt — it scored 27/35 against `main`'s 32/35 and the
  new failures were "almost entirely extra escalations, the guard over-refusing".
  So precision is a hard gate here: one clean draft flagged fails the build.
* **A false negative sends a promise nobody will keep.** Bad, and exactly what
  happens today, so the floor cannot drop.

**Drafts marked `[observed]` are real CARE output**, quoted from the milestone
1.11 and 1.12 session logs. They are the only non-invented material in this file
and they are the reason it exists.
"""

from __future__ import annotations

import pytest

from neura_agent_core.guard.promises import PROMISE_RULES, find_promises

#: Thirty drafts that commit to something outside the turn.
PROMISES: list[str] = [
    # [observed] the swimsuit reply, 2026-07-29 — the sentence that raised A9(3).
    "Your swimsuit is in the 30-day return window, but we cannot accept returns for "
    "hygiene reasons. Let me know your order number and I'll send you a prepaid return label.",
    # [observed] milestone 1.11, product_qa
    "Let me check the size for you.",
    # [observed] milestone 1.11, product_qa
    "Would you like to be notified when it's back in stock?",
    "I'll email you the tracking number as soon as it ships.",
    "I will contact the warehouse and get back to you.",
    "I'm going to arrange a replacement for you.",
    "I shall forward this to the returns team.",
    "Let me look into that and come back to you.",
    "I can check with the courier and let you know.",
    "I could raise this with our support team for you.",
    "Shall I cancel the order for you?",
    "Would you like me to update your delivery address?",
    "Do you want me to remind you when the sale starts?",
    "I'll process the refund today.",
    "I will send you a confirmation once that's done.",
    "Let me file a complaint on your behalf.",
    "I'll follow up with the supplier about the delay.",
    "I can arrange a different delivery slot if you'd prefer.",
    "Let me sort this out for you and I'll be in touch.",
    "I'll book a collection for Tuesday.",
    "Would you like me to escalate this to a manager?",
    "I'll add the item to your order.",
    "I can remove that from your basket for you.",
    "I will investigate why the parcel is late.",
    "Shall I email you the receipt?",
    "I'm going to log this as a fault report.",
    "Let me verify your address with the courier.",
    "I'll reschedule the delivery for next week.",
    "Would you like to be contacted when a refund is issued?",
    "I can apply the discount code to your account.",
]

#: Thirty drafts that promise nothing. Every one shares vocabulary with the half
#: above — "we will", "send", "check", "let me know", "notified", "refund" — and
#: every one must get through.
CLEAN: list[str] = [
    # The merchant's own process, quoted from a policy page. This is the single
    # most important line in the file: the failing draft above and this one both
    # contain "send a prepaid label", and only one of them is a promise.
    "Our returns policy says the store will send a prepaid label once the return is approved.",
    "We will send a prepaid label; the cost of return postage is deducted from your refund.",
    "You'll be notified by email when the order ships — that's automatic.",
    # [observed] milestone 1.11 — the correct version of the size answer.
    "We have the Waterproof Hiking Shoe in stock, but we don't have a UK 9 available.",
    # [observed] milestone 1.12, live shop
    "Your returns window is 30 days from the day your item was delivered. The item must be "
    "unworn, unwashed, and with its original tags attached.",
    "Standard delivery is 3 to 5 working days and costs $5.00.",
    "I can see that your order was dispatched on Tuesday.",
    "I can confirm your order is on its way.",
    "I can tell you that the shoe comes in brown and black.",
    "Let me know your order number and I can look it up.",
    "Let me know if that answers your question.",
    "I can help with questions about orders, products and policies.",
    "I can explain how the returns process works.",
    "I found three jackets that match what you described.",
    "Refunds are issued to the original payment method within 5 working days.",
    "To start a return, contact support with your order number.",
    "The store will email you once the refund has been processed.",
    "Underwear, swimwear and pierced jewellery cannot be returned for hygiene reasons.",
    "That item is out of stock at the moment.",
    "We ship internationally to most countries; delivery there takes 7 to 14 working days.",
    "Any customs duty is payable by the recipient.",
    "Your order NRA0002 was delivered on 14 March.",
    "The Trail Backpack 30L is available to buy at $89.00.",
    "You can check the tracking on the courier's website using the number on your confirmation email.",
    "Support is open Monday to Friday.",
    "I don't have information about that.",
    "I'm not able to change an order, but a member of the team can.",
    "The warranty covers manufacturing faults for 12 months.",
    "Payment methods accepted are card, PayPal and cash on delivery.",
    "That product page lists the care instructions.",
]


def test_the_corpus_is_balanced() -> None:
    """Asserted, not assumed. The natural way to maintain this file is to add
    the promise that got through last week and nothing else, and a year of that
    produces a corpus that can only reward strictness."""
    assert len(PROMISES) == len(CLEAN) == 30
    assert len(set(PROMISES)) == len(PROMISES)
    assert len(set(CLEAN)) == len(CLEAN)


@pytest.mark.parametrize("draft", CLEAN)
def test_no_clean_draft_is_flagged(draft: str) -> None:
    """A hard gate. Flagging a good answer escalates it, and escalating good
    answers is precisely how the 2026-07-30 attempt made things worse."""
    found = find_promises(draft)
    assert not found, f"clean draft flagged by {[p.rule for p in found]}: {draft!r}"


@pytest.mark.parametrize("draft", PROMISES)
def test_every_promise_is_caught(draft: str) -> None:
    assert find_promises(draft), f"unkeepable promise not caught: {draft!r}"


def test_quoting_the_store_s_first_person_prose_is_not_a_promise() -> None:
    """The mechanism behind A9(3), tested directly.

    The Return Policy is written in the first person plural, so the model
    re-voices it as its own commitment. "We" is genuinely ambiguous between the
    store and the assistant and must not be banned; "I" is not ambiguous.
    """
    assert not find_promises("We will send a prepaid label once the return is approved.")
    assert find_promises("I'll send you a prepaid return label.")


def test_asking_the_shopper_to_act_is_not_the_agent_promising() -> None:
    """ "Let me know your order number" is the correct thing to say, and it
    appears in the very sentence that produced this rule — immediately before the
    promise. Without the exemption the rule would be right for the wrong reason.
    """
    assert not find_promises("Let me know your order number.")
    assert not find_promises("Let me know if you'd like the brown one instead.")


def test_present_tense_ability_is_not_a_future_commitment() -> None:
    """ "I can see" is true now. "I can check" has no later in which to check."""
    assert not find_promises("I can see your order shipped on Tuesday.")
    assert find_promises("I can check that with the warehouse.")


def test_a_promise_detail_never_quotes_the_draft() -> None:
    """These strings go to logs and to the handoff packet, which already carries
    the draft in full."""
    promises = find_promises("I'll email you the tracking number.")
    assert promises and all("tracking number" not in p.detail for p in promises)


@pytest.mark.parametrize("rule", PROMISE_RULES, ids=lambda r: r.name)
def test_every_rule_can_explain_itself(rule: object) -> None:
    assert getattr(rule, "rationale", "").strip(), f"{rule} has no rationale"
