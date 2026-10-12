"""What a handed-over shopper reads. ADR-0055, ADR-0062, the log's G44.

Every handover used to say *"I'm passing you to a colleague. They'll have
everything we've talked about"*, and nobody came: the dashboard cannot reply to a
shopper, and the chat lives only in the shopper's browser tab. A handover now
says that the assistant cannot help here and how to reach the shop, in the
shop's own contact details, typed once by the owner on Shop connection.

**It promises nothing**: not a person, not a time, not that the conversation is
passed on. With no details set, the sentence stops short and is still true.

Made here, below every agent, so there is one sentence: the turn service puts it
on the reply of every handover it releases (`neura_api.turns`), and the shared
`escalate` node and CARE's prompt file say the no-details form, so a path that
skips the turn service cannot say the old one.
"""

from __future__ import annotations

from neura_core.tenancy.models import TenantConfig

#: The sentence with nothing after it: the owner has not set any details yet.
HANDOVER_WITHOUT_DETAILS = "I can't help with this here. Please contact our store."


def handover_message(config: TenantConfig) -> str:
    """The handover sentence, naming the shop's email and phone as the owner set them."""
    details = [value for value in (config.contact_email, config.contact_phone) if value]
    if not details:
        return HANDOVER_WITHOUT_DETAILS
    return f"{HANDOVER_WITHOUT_DETAILS[:-1]}: {', '.join(details)}."


# ── ADR-0062: a handed-over shopper may leave an email (R31, the owner's words) ──
#
# The shop answers from its own email app; NEURA sends nothing. So every sentence
# says the store **can** answer, never that it **will**: NEURA cannot promise it.
# The contact line goes on a line of its own, because the chat box draws its
# email box between the first line and the rest (ADR-0062 §5, the approved
# mockup), and a client without the box still shows the whole text.

#: The first handover in a chat, to a shopper NEURA cannot reach: the chat box
#: shows its email box under this line (the reply's ``ask_email`` mark).
HANDOVER_ASK = "I can't answer this here. Leave your email so our store can answer you."

#: A shopper the shop can already reach: signed in (the shop holds their email),
#: or one who left an address earlier in the same chat.
HANDOVER_WITH_STORE = (
    "I can't answer this here. Your question is with our store, and they can answer you by email."
)

#: Under the email box when the address does not look like one.
WRONG_EMAIL = "Please check your email address."


def contact_line(config: TenantConfig) -> str | None:
    """*"Or contact our store: [email], [phone]."*, or nothing when the owner set no
    details (ADR-0055 §3's rule: the sentence is true with nothing set)."""
    details = [value for value in (config.contact_email, config.contact_phone) if value]
    if not details:
        return None
    return f"Or contact our store: {', '.join(details)}."


def handover_ask_message(config: TenantConfig) -> str:
    """The first handover in a chat, with the email box under its first line."""
    return _with_contact(HANDOVER_ASK, config)


def handover_with_store_message(config: TenantConfig) -> str:
    """A handover whose shopper the shop can already answer by email."""
    return _with_contact(HANDOVER_WITH_STORE, config)


def email_thanks(email: str) -> str:
    """What the chat box shows after *Send*: the address the shopper typed, so a
    mistyped one is seen at once."""
    return f"Thanks. Your question is with our store, and they can answer you at {email}."


def answer_email(shop: str, question: str | None) -> tuple[str, str]:
    """The subject and body the team member's own email app is filled with when
    they press *Answer by email* (ADR-0062 §7, approved with the mockup).

    *You asked us* tells a person whose address someone else typed why they got
    it (ADR-0046 §4). The gap is where the team member writes the answer; **the
    AI's unsent draft is never put in**: it was held back because it may be wrong.
    """
    subject = f"Your question to {shop}"
    asked = (
        f"You asked us in the chat on our website:\n\u201c{question}\u201d\n" if question else ""
    )
    return subject, f"Hello,\n\n{asked}\n\n\n{shop}"


def _with_contact(sentence: str, config: TenantConfig) -> str:
    line = contact_line(config)
    return sentence if line is None else f"{sentence}\n{line}"


#: What a shopper who is not signed in reads about an order (ADR-0057 §7, the
#: owner's words, accepted 2026-10-08). Not a handover: a person could not answer
#: it either without knowing who is asking.
SIGN_IN_WITHOUT_DETAILS = "Please sign in to your account so I can help with your orders."

#: What a signed-in shopper reads when their page's pass has run out (§5). No
#: link: they are signed in already, and a fresh page brings a fresh pass.
# S105 reads "PASS" as a password; these are words a shopper reads.
PASS_EXPIRED_MESSAGE = (
    "Your sign-in on this page has timed out. Please reload the page and ask again."  # noqa: S105
)


def sign_in_message(config: TenantConfig) -> str:
    """The sign-in sentence, then the shop's email and phone as the owner set
    them, so a shopper with no account (a guest) still has a way to ask."""
    details = [value for value in (config.contact_email, config.contact_phone) if value]
    if not details:
        return SIGN_IN_WITHOUT_DETAILS
    return f"{SIGN_IN_WITHOUT_DETAILS} Or contact our store: {', '.join(details)}."


__all__ = [
    "HANDOVER_ASK",
    "HANDOVER_WITHOUT_DETAILS",
    "HANDOVER_WITH_STORE",
    "PASS_EXPIRED_MESSAGE",
    "SIGN_IN_WITHOUT_DETAILS",
    "WRONG_EMAIL",
    "answer_email",
    "contact_line",
    "email_thanks",
    "handover_ask_message",
    "handover_message",
    "handover_with_store_message",
    "sign_in_message",
]
