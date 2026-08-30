"""Every installed agent must say what it answers — [ADR-0031] §2.

The dispatcher chooses between agents by reading these declarations, and shared
code never names an agent (``routes/agent.py`` does not know the word "care").
So a manifest that does not declare is an agent nobody can reach, and there is
nowhere else the mistake would surface: ``discover_agents`` catches a broken
manifest, logs it and **skips the agent**, so a validation failure removes the
agent from the API rather than announcing itself.

These run without a model, a database or a store.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from neura_agent_care.manifest import MANIFEST as CARE
from neura_agent_sell.manifest import MANIFEST as SELL
from neura_agent_sell.manifest import AgentManifest

INSTALLED = (CARE, SELL)

#: Topics SELL's own ``prompts/route.md`` sends to ``needs_person``. SELL must
#: not claim any of them, in either field.
SELL_SENDS_TO_A_PERSON = (
    "order",
    "delivery",
    "return",
    "refund",
    "exchange",
    "policy",
    "shipping",
    "track",
)


class TestEveryAgentDeclares:
    @pytest.mark.parametrize("manifest", INSTALLED, ids=lambda m: m.key)
    def test_it_says_what_it_answers(self, manifest: AgentManifest) -> None:
        assert manifest.handles.strip()

    @pytest.mark.parametrize("manifest", INSTALLED, ids=lambda m: m.key)
    def test_it_gives_between_three_and_five_examples(self, manifest: AgentManifest) -> None:
        assert 3 <= len(manifest.handles_examples) <= 5

    @pytest.mark.parametrize("manifest", INSTALLED, ids=lambda m: m.key)
    def test_every_example_is_a_real_question(self, manifest: AgentManifest) -> None:
        """A placeholder is worse than nothing: it satisfies the count and

        teaches the dispatcher an example no shopper would ever type.
        """
        for example in manifest.handles_examples:
            assert len(example.split()) >= 3, example


class TestTheShapeIsEnforced:
    """Required and bounded, so forgetting fails at import rather than quietly.

    ``discover_agents`` logs and skips a manifest that will not construct, so
    the loud failure has to happen here — in the model — or the agent simply
    disappears from the API with one log line nobody is reading.
    """

    def _manifest(self, **overrides: object) -> AgentManifest:
        base = SELL.model_dump()
        base.update(overrides)
        return AgentManifest(**base)  # type: ignore[arg-type]

    def test_fewer_than_three_examples_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            self._manifest(handles_examples=("one?", "two?"))

    def test_more_than_five_examples_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            self._manifest(handles_examples=tuple(f"question {n}?" for n in range(6)))

    def test_the_declaration_cannot_be_omitted(self) -> None:
        base = SELL.model_dump()
        del base["handles"]
        with pytest.raises(ValidationError):
            AgentManifest(**base)  # type: ignore[arg-type]


class TestTheTwoAgentsAreDistinguishable:
    """The dispatcher's whole job is telling these two apart.

    A13: CARE is the wider agent, and the expensive misroute is one-directional
    — a shopping question sent to CARE is answered, while an order question sent
    to SELL reaches a **person**. So the assertion that matters is on SELL.
    """

    @pytest.mark.parametrize("topic", SELL_SENDS_TO_A_PERSON)
    def test_sell_does_not_claim_what_it_hands_to_a_person(self, topic: str) -> None:
        declared = " ".join((SELL.handles, *SELL.handles_examples)).lower()
        assert topic not in declared, (
            f"SELL's declaration mentions {topic!r}, but SELL's own route.md sends "
            f"that to `needs_person`. Dispatching it to SELL costs the merchant a "
            f"human for a question CARE answers."
        )

    def test_no_example_is_claimed_by_two_agents(self) -> None:
        seen: dict[str, str] = {}
        for manifest in INSTALLED:
            for example in manifest.handles_examples:
                key = example.lower().strip()
                assert key not in seen, f"{manifest.key} and {seen[key]} both claim {example!r}"
                seen[key] = manifest.key
