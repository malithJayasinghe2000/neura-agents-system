"""Reversible PII tokenisation, and the vault that makes it reversible.

security-model.md §6.1: personal data is replaced with tokens *before* anything
reaches a model, the mapping is held server-side for the turn, and the reply is
rehydrated on the way out.

```
"I'm jane@example.com, ship to 42 Hill St"
        │  redact()      — in `guard`, before any model call
"I'm [EMAIL_1], ship to [ADDRESS_1]"
        │                 the model reasons over tokens
        │  rehydrate()   — in `respond`, for this shopper only
"Thanks — your order is going to 42 Hill St"
```

**Why this is worth doing when the local tier makes it unnecessary.** Under the
sovereign tier nothing leaves the merchant's own infrastructure and none of this
matters. Under the cloud tier the `REASONER` is a third-party API, and the
difference between sending "jane@example.com" and sending "[EMAIL_1]" is the
difference between a data-processing agreement that is easy to sign and one that
is not (blueprint-v2.md §4.3).

**The vault never touches the database.** It lives on :class:`Runtime`, which is
per-turn and explicitly the home of everything that cannot be checkpointed. That
falls out well: the checkpoint written after every node holds the *redacted*
message, so a conversation resumed from Postgres a day later cannot re-expose
what was tokenised. It is also what security-model.md §6.2 asks for — token maps
live for the session, never long-term — without any deletion code to forget to
write.

## Precision over recall, and what that costs

Every detector here is deliberately narrow, because the two errors are not
symmetric in the way the naive reading suggests:

* A **false negative** sends a phone number to a cloud model that was already
  going to receive the whole conversation. Bad, and no worse than today.
* A **false positive** replaces an order number with `[PHONE_1]`, and the lookup
  fails. The shopper is told we cannot find their order. That is a broken
  product, and it is silent.

So a bare eleven-digit run is *not* treated as a phone number, because a
merchant's order references look exactly like one. A phone number must carry
structure a reference does not — a `+`, a leading zero, or separators.

## What is deliberately not detected

* **National identity numbers.** The formats are jurisdictional and this project
  has not chosen a geography (open question B3). A pattern guessed now would be
  wrong for wherever the first merchant turns out to be.
* **Names.** Not detectable without a model, and a model is what the guard does
  not have (ADR-0011). "Jane" is also a product name, a colour and a brand.
* **Anything inside tool results or retrieved documents.** Those carry the
  merchant's own customer data, and redacting them would break the order lookups
  that are most of what CARE does. The control there is the ownership gate, which
  decides whether the data may be fetched at all — see §3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

#: The shape a token takes. Chosen to survive a language model intact: square
#: brackets and an underscore-joined uppercase word are copied verbatim far more
#: reliably than <angle> or {curly} forms, which models rewrite into markup.
TOKEN: Final = "[{kind}_{index}]"  # noqa: S105 — a redaction placeholder, not a credential

#: Matches any token this module produces. Used to check whether a draft carries
#: a token the vault does not know — the failure mode where a model invents
#: `[EMAIL_7]` and rehydration would otherwise leave it in the reply.
TOKEN_RE: Final = re.compile(r"\[(EMAIL|PHONE|CARD|ADDRESS)_(\d+)\]")


# ── Detectors ────────────────────────────────────────────────────────────────

_EMAIL: Final = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]*[a-zA-Z]\b")

#: A payment card, subject to Luhn below. The check digit is what separates a
#: card from a 16-digit order reference, and without it this detector would be a
#: machine for breaking order lookups.
_CARD_CANDIDATE: Final = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")

#: "card ending 4242". The last four digits alone are not a payment credential,
#: but they are the thing a shopper types, and the phrase around them makes the
#: match unambiguous.
_CARD_LAST4: Final = re.compile(r"(?i)\bcard\s+(?:number\s+)?ending(?:\s+in)?\s+(\d{4})\b")

#: Three alternatives, each requiring structure a bare number does not have.
_PHONE: Final = re.compile(
    r"""
    (?<![\w.])
    (
        \+\d[\d\s().-]{7,17}\d          # international, e.g. +94 71 234 5678
      | \(?0\d{1,4}\)?[\s.-]\d{3,4}[\s.-]?\d{3,4}   # national, leading zero
      | \d{3}[\s.-]\d{3,4}[\s.-]\d{3,4}             # separated groups
    )
    (?![\w.])
    """,
    re.VERBOSE,
)

#: A street address: a house number, at least one word, then a street type.
#: The intermediate word is what stops "2 Way Speaker" and "3 Piece Set"
#: matching — both of which the first draft of this pattern happily redacted.
_ADDRESS: Final = re.compile(
    r"""
    \b \d{1,5} [a-zA-Z]? \s+
    (?: [A-Za-z][\w'-]* \s+ ){1,3}
    (?: street|st|road|rd|avenue|ave|lane|ln|drive|close|court|crescent
      | terrace|boulevard|blvd|place|gardens|mawatha )
    \b \.?
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _luhn(digits: str) -> bool:
    """The check digit every payment card carries and no order number does."""
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


@dataclass(slots=True)
class PiiVault:
    """One turn's redaction map. Server-side, in memory, never persisted.

    Tokens are **stable within a turn**: the same email mentioned twice gets
    `[EMAIL_1]` both times, so the model can tell that two mentions are one
    person. They are not stable across turns, and deliberately — a token that
    survived would be a durable identifier for the thing it was meant to hide.
    """

    _by_value: dict[str, str] = field(default_factory=dict)
    _by_token: dict[str, str] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self._by_token)

    @property
    def tokens(self) -> list[str]:
        """The tokens issued, in issue order. Safe to log and to checkpoint —
        `[EMAIL_1]` tells a reader that an email was present without telling
        them whose."""
        return list(self._by_token)

    def _token_for(self, kind: str, value: str) -> str:
        if existing := self._by_value.get(value):
            return existing
        index = self._counts.get(kind, 0) + 1
        self._counts[kind] = index
        token = TOKEN.format(kind=kind, index=index)
        self._by_value[value] = token
        self._by_token[token] = value
        return token

    def redact(self, text: str) -> str:
        """Replace every detected value with a token.

        Order matters and is not arbitrary. Emails go first so that a phone-like
        digit run inside one is not carved out of it; cards before phones,
        because a Luhn-valid sixteen-digit number written with spaces satisfies
        the phone pattern too, and a card is the more serious thing to mistake.
        """
        if not text:
            return text

        text = _EMAIL.sub(lambda m: self._token_for("EMAIL", m.group(0)), text)
        text = _CARD_LAST4.sub(
            lambda m: m.group(0).replace(m.group(1), self._token_for("CARD", m.group(1))), text
        )
        text = _CARD_CANDIDATE.sub(self._maybe_card, text)
        text = _PHONE.sub(self._maybe_phone, text)
        text = _ADDRESS.sub(lambda m: self._token_for("ADDRESS", m.group(0)), text)
        return text

    def _maybe_card(self, match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if not (13 <= len(digits) <= 19 and _luhn(digits)):
            # Not a card. Almost certainly an order or tracking reference, and
            # redacting it would break the lookup the shopper actually wants.
            return raw
        return self._token_for("CARD", raw)

    def _maybe_phone(self, match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if not 9 <= len(digits) <= 15:
            return raw
        return self._token_for("PHONE", raw)

    def rehydrate(self, text: str) -> str:
        """Put the real values back, for this shopper, at the last moment.

        A token the vault does not know is left **as written**, not guessed at
        and not silently deleted. A model that invented `[EMAIL_9]` has produced
        a reply referring to something that does not exist, and a visible
        `[EMAIL_9]` in a draft is a bug report; a quietly removed one is a
        sentence that has changed meaning with nobody the wiser.
        """
        if not text or not self._by_token:
            return text
        return TOKEN_RE.sub(lambda m: self._by_token.get(m.group(0), m.group(0)), text)

    def knows(self, value: str) -> bool:
        """Did this value arrive from the shopper this turn?

        Used by the outbound filter: contact details in a reply are fine when
        the shopper supplied them, and are a leak when they came from nowhere.
        """
        return value in self._by_value


# ── Outbound scanning (security-model.md §6.3, threat T10) ───────────────────


@dataclass(frozen=True, slots=True)
class Leak:
    """Personal data in an outbound reply that nothing in the turn accounts for."""

    kind: str
    #: Never the value itself. This string goes to logs and to the handoff.
    detail: str


def find_leaks(reply: str, *, evidence: str, vault: PiiVault) -> list[Leak]:
    """Scan a finished reply for personal data it has no right to contain.

    Two rules, both deterministic, both narrow:

    * **A payment card number may never appear in a reply.** There is no
      legitimate turn in which CARE reads a card number back to anybody, so
      there is no false positive to weigh. This is also the one leak that would
      matter immediately.
    * **An email address or phone number must appear in the evidence or in the
      vault.** If the shopper typed it, or the store returned it under an
      ownership check that already passed, it is theirs. If it appears in
      neither, the model either invented it — a fabricated support address is a
      real support failure — or carried it from text that was not evidence, which
      is exactly threat T10.

    Note what this is *not*: it is not a check that the data belongs to the right
    customer. That decision is made earlier and in code, by the ownership gate
    (§3), which is where it can be made correctly. A filter reading a finished
    sentence cannot tell whose address it is.
    """
    leaks: list[Leak] = []

    for match in _CARD_CANDIDATE.finditer(reply):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            leaks.append(Leak("card", "a payment card number appears in the reply"))

    for kind, pattern in (("email", _EMAIL), ("phone", _PHONE)):
        for match in pattern.finditer(reply):
            value = match.group(0)
            if kind == "phone" and not 9 <= len(re.sub(r"\D", "", value)) <= 15:
                continue
            if vault.knows(value) or value in evidence:
                continue
            leaks.append(
                Leak(kind, f"an {kind} address appears in the reply but in no evidence for it")
                if kind == "email"
                else Leak(kind, "a phone number appears in the reply but in no evidence for it")
            )

    return leaks


__all__ = ["TOKEN_RE", "Leak", "PiiVault", "find_leaks"]
