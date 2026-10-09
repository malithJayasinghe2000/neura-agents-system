"""What a handed-over shopper reads. ADR-0055, the log's G44.

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
    "HANDOVER_WITHOUT_DETAILS",
    "PASS_EXPIRED_MESSAGE",
    "SIGN_IN_WITHOUT_DETAILS",
    "handover_message",
    "sign_in_message",
]
