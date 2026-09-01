"""Choosing which agent answers one shopper message — [ADR-0031] §3.

The shopper types into one box and never picks a service. This is the code that
picks for them.

**It knows no agent's name.** Candidates arrive as declarations lifted from their
own manifests, the prompt is rendered from those declarations, and the schema is
built from the keys it was handed. A dispatcher containing ``if the question is
about products`` would put agent names in shared code — the same failure as a
platform name outside ``neura-adapters`` (AGENTS.md rule 1).

**It decides a destination, not a permission.** Whether the chosen agent may
actually be used is `Tenant.may_use`, in code, one layer up. A model that picks
an agent the shop has not bought changes nothing about what runs — ADR-0031 §4
sends that turn to a person.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal, cast

from pydantic import BaseModel, Field, create_model

from neura_core import get_logger
from neura_dispatch.prompts import load_prompts, revision
from neura_llm import ChatRequest, ChatResponse, LLMClient, Message, ModelRole

log = get_logger(__name__)

PROMPT_NAME = "dispatch"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One agent the dispatcher may choose, as its own manifest describes it.

    Built from ``AgentManifest.handles`` and ``handles_examples`` rather than
    from ``description``: a description is written for a merchant deciding what
    to buy, and every one of them reduces to "helps shoppers".
    """

    key: str
    handles: str
    examples: tuple[str, ...] = ()

    def render(self) -> str:
        lines = [f"### {self.key}", self.handles]
        if self.examples:
            lines.append("")
            lines.append("Questions it takes:")
            lines += [f"- {example}" for example in self.examples]
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Decision:
    """Which agent was chosen, and what it cost to choose.

    ``agent`` is never a key outside the candidate set: the schema constrains
    the model to the keys it was given, and a response that somehow escapes that
    is rejected in :func:`choose` rather than trusted.
    """

    agent: str | None
    confidence: float = 0.0
    #: No model was called — there was only one candidate, so there was nothing
    #: to choose. Reported so a run can say how much of it was actually measured.
    trivial: bool = False
    reason: str = ""
    prompt_revision: str = ""
    responses: tuple[ChatResponse, ...] = field(default=())

    @property
    def dispatched(self) -> bool:
        return self.agent is not None


class NoCandidatesError(ValueError):
    """Asked to choose with an empty candidate set.

    Raised rather than returning ``None``, because the two are different
    failures: "the shop has no agents enabled" is a provisioning fault to be
    fixed, and "the model would not pick one" is a dispatch outcome to be
    measured. Collapsing them would hide the first inside the second's rate.
    """


@lru_cache(maxsize=64)
def _schema_for(keys: tuple[str, ...]) -> type[BaseModel]:
    """A response model whose ``agent`` field admits only these keys.

    Built per candidate set rather than declared once with ``agent: str``,
    because a free-string field lets the model answer with an agent that does
    not exist and turns a routing question into a validation question. The
    structured-output layer already knows how to make a model satisfy an enum;
    this hands it one.

    Cached on the key tuple: a deployment has a handful of distinct sets, and
    rebuilding a pydantic model per shopper message is pure waste.
    """
    return create_model(
        "Dispatch",
        agent=(
            cast(type, Literal[keys]),
            Field(description="The key of the one service that should answer this message."),
        ),
        confidence=(
            float,
            Field(ge=0.0, le=1.0, description="How sure you are. Do not inflate it."),
        ),
    )


def _render(message: str, history: list[dict[str, str]] | None) -> str:
    """The message and its recent context, delimited as untrusted.

    The delimiter does not make the content safe — a shopper can type the
    closing tag too. It makes the boundary *visible*: to a human reading the
    trace, and to the model, whose prompt says everything inside is material to
    route rather than instructions to follow (security-model.md §2.3).
    """
    parts = []
    if history:
        turns = "\n".join(f"{t.get('role', '?')}: {t.get('content', '')}" for t in history[-6:])
        parts.append(f"<untrusted_previous_turns>\n{turns}\n</untrusted_previous_turns>")
    parts.append(f"<untrusted_customer_message>\n{message}\n</untrusted_customer_message>")
    return "\n\n".join(parts)


def _catalogue(candidates: tuple[Candidate, ...]) -> str:
    return "\n\n".join(c.render() for c in candidates)


async def choose(
    llm: LLMClient,
    message: str,
    candidates: tuple[Candidate, ...],
    history: list[dict[str, str]] | None = None,
) -> Decision:
    """Pick the agent that should answer ``message``.

    One model call on the ``ROUTER`` role — the role built for "classify this
    message", and one that every role map already fills, so this adds no
    configuration ([ADR-0031] §7). The cost is a second classification on a
    dispatched turn, since the chosen agent's own ``route`` runs afterwards; it
    is measured on the dispatch suite rather than estimated.
    """
    if not candidates:
        raise NoCandidatesError("cannot dispatch with no candidate agents")

    if len(candidates) == 1:
        # Nothing to choose. A single-agent shop must behave exactly as it did
        # before the dispatcher existed: no new latency, no new cost, no new
        # failure mode — and no model call to fail.
        only = candidates[0]
        return Decision(
            agent=only.key,
            confidence=1.0,
            trivial=True,
            reason="one agent enabled — nothing to choose",
        )

    keys = tuple(c.key for c in candidates)
    schema = _schema_for(keys)
    request = ChatRequest(
        messages=[
            Message.system(
                f"{load_prompts()[PROMPT_NAME]}\n\n## The services\n\n{_catalogue(candidates)}"
            ),
            Message.user(_render(message, history)),
        ],
        temperature=0.0,
    )

    result = await llm.chat_structured(ModelRole.ROUTER, request, schema)
    chosen = cast(str, getattr(result.value, "agent", None))
    confidence = float(getattr(result.value, "confidence", 0.0) or 0.0)

    if chosen not in keys:
        # The schema should have made this unreachable. Checked anyway, because
        # "should be unreachable" is how a free-text agent key gets trusted into
        # a route lookup — and the honest outcome is no dispatch, not a guess.
        log.warning("dispatch_returned_unknown_agent", agent=chosen, candidates=list(keys))
        return Decision(
            agent=None,
            reason=f"model chose {chosen!r}, which is not one of {list(keys)}",
            prompt_revision=revision(),
            responses=(result.response,),
        )

    log.info(
        "dispatch_chosen",
        agent=chosen,
        confidence=confidence,
        candidates=list(keys),
        cost_usd=str(result.response.cost_usd),
    )
    return Decision(
        agent=chosen,
        confidence=confidence,
        prompt_revision=revision(),
        responses=(result.response,),
    )


__all__ = ["Candidate", "Decision", "NoCandidatesError", "choose"]
