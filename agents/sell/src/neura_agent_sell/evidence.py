"""What `verify` is allowed to read. ADR-0025.

`verify` checks a draft against the evidence the turn retrieved. For SELL that
evidence is a **catalogue**, and a catalogue contains one field the merchant
writes as free prose — the description. That is where an indirect injection
lives (T2), and it arrives from the merchant's own store, editable by any of
their admin users.

**The measurement this file exists for.** `make verify-probe AGENT=sell`, arms E,
F and G, n=10 each at temperature 0.0: an attributed comparative claim over a
two-product shortlist is grounded 10/10; *the identical draft*, with one extra
shortlist entry it never mentions whose description reads ``IGNORE ALL PREVIOUS
INSTRUCTIONS…``, is refused **10/10**; and the control — the same draft with a
**benign** third product of the same shape — is grounded 10/10 again. So it is
the text, not the length of the shortlist.

**The payload does not steer the agent. It denies it.** Injection resistance is
1.00 including guard-off; nothing in the payload is obeyed and no forbidden
product reaches the reply. What happens instead is that a turn which should have
recommended two jackets escalates to a human, and the merchant pays for it.

## The rule

Every shortlisted product keeps its **identity, price and availability**. Only
the free-text `description` of a product the draft **does not cite** is withheld,
and it is replaced by a marker rather than deleted — `tools/render.py` states
absences for a reason, and an absence a model cannot see is one it fills in.

**Why not whole entries.** The structured fields are the ones `verify` needs
most. The worst failure in the same eval run was `compose` claiming a boot was
*"available in UK 9"* against evidence reading ``size: UK 8, UK 9 (out of
stock)`` — a catch that lives in `available options`, not in a description.
Dropping whole entries would trade one failure for a worse one.

**Why citation and not detection.** This module never asks whether text is
hostile. It asks which products the draft makes claims about, which has a
deterministic answer. A paraphrased payload, one in a language we do not read,
and one in a form nobody has invented yet are all excluded identically —
because none of them is in a product the draft cited. Rule-matching would catch
only the first: `guard/injection.py` is tuned for precision and says in its own
docstring that its recall is deliberately poor and will stay poor.

## What this does not fix

**If the draft cites the injected product, its description still reaches
`verify` — and it must**, because it is then genuine evidence for a claim a
shopper will read. Filtering it would remove the ability to check the claim. That
residual is narrower than what was measured (`compose` has to choose to
recommend the hostile product first) and it is why **S9 stays open** rather than
being closed by ADR-0025.
"""

from __future__ import annotations

import re

#: A rendered entry starts at `Product <id>:` in column 0 of a tool result and
#: runs to the next one. Anchored to the format `tools/render.py::candidate`
#: writes, and asserted against the real renderer in `tests/unit/test_sell.py`
#: — a silent drift here would hand `verify` an unfiltered block while every
#: test still passed.
_ENTRY = re.compile(r"^Product ([A-Za-z0-9][A-Za-z0-9_-]*):", re.MULTILINE)

#: The description line, from its label to the end of that line.
_DESCRIPTION = re.compile(r"^(\s*description: )(.*)$", re.MULTILINE)

#: Token shapes that could be a product id, matching `respond.py::_CITED`
#: exactly. **The two must agree**: `respond` refuses a draft citing a product
#: that was never shortlisted, and if this file read citations differently it
#: could withhold the evidence for a product `respond` considers cited.
_CITED = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_-]{2,})\b")

#: Stated, never silent. A model shown nothing concludes there was nothing.
WITHHELD = (
    "[withheld — this product was not recommended in the draft, so its "
    "description is not evidence for any claim in it (ADR-0025)]"
)


def hide_uncited_descriptions(draft: str, evidence: str) -> str:
    """The evidence `verify` may read, given what the draft actually cites.

    Signature is ``(draft, evidence) -> str`` because that is
    `Runtime.evidence_filter`. Pure, deterministic, and no model call.
    """
    cited = set(_CITED.findall(draft))
    if not evidence:
        return evidence

    out: list[str] = []
    for chunk, product_id in _split_entries(evidence):
        # Text outside any product entry — tool result wrappers, retrieved
        # context, the shortlist's own preamble — is passed through untouched.
        # This function's remit is one field of one rendering, and widening it
        # to "anything that looks risky" is the detection approach ADR-0025
        # rejected.
        if product_id is None or product_id in cited:
            out.append(chunk)
        else:
            out.append(_DESCRIPTION.sub(lambda m: f"{m.group(1)}{WITHHELD}", chunk))
    return "".join(out)


def _split_entries(evidence: str) -> list[tuple[str, str | None]]:
    """``(text, product_id)`` for each span, with ``None`` outside any entry."""
    spans: list[tuple[str, str | None]] = []
    matches = list(_ENTRY.finditer(evidence))

    if not matches:
        return [(evidence, None)]

    if matches[0].start() > 0:
        spans.append((evidence[: matches[0].start()], None))

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(evidence)
        spans.append((evidence[match.start() : end], match.group(1)))

    return spans


__all__ = ["WITHHELD", "hide_uncited_descriptions"]
