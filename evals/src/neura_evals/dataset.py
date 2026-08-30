"""Golden datasets — the test cases an agent is scored against.

Cases live in YAML so they are reviewable in a pull request by someone who does
not read Python. That matters: the people best placed to say "no, a customer
would never phrase it like that" are support staff, not engineers.

Rules from docs/architecture/evaluation-strategy.md §2:

* Cases come from **real conversations** wherever possible. Invented cases test
  what we expect to happen, which is exactly the wrong thing to measure.
* Anything not from a real conversation is marked ``synthetic: true`` and is
  never counted as validation.
* ``out_of_scope`` cases matter as much as the happy paths — an agent that
  answers everything is worse than one that knows its limits.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The one intent this harness has a *rule* about.
#:
#: An adversarial case must assert `unauthorised_tool_calls`, or it is a
#: security case that would pass while a tool ran. Everything else is a label
#: the harness groups by and does not interpret.
ADVERSARIAL = "adversarial"


class Intent(StrEnum):
    """The intents **CARE** uses. Kept for callers that want the constants.

    **This is not the set of valid values, and `EvalCase.intent` is a plain
    `str`.** It used to be this enum, and adding agent #2 is what exposed the
    problem: SELL classifies into `recommend` / `compare` / `needs_person`, and
    a shared harness that could not parse them was a harness that knew one
    agent's vocabulary.

    That is the same coupling `neura-agent-core` is forbidden — the engine must
    not learn an agent's name — applied one package over and found late, because
    for one agent an enum and a vocabulary look identical.

    :data:`ADVERSARIAL` is deliberately outside this enum: it is the harness's
    own reserved word, not any agent's intent.
    """

    ORDER_STATUS = "order_status"
    PRODUCT_QA = "product_qa"
    POLICY_QA = "policy_qa"
    OUT_OF_SCOPE = "out_of_scope"
    ADVERSARIAL = "adversarial"


class Expectation(BaseModel):
    """What a correct response looks like.

    Every field is optional: a case asserts only what it is actually testing.
    Over-specifying makes tests brittle against phrasing changes that do not
    matter.
    """

    model_config = ConfigDict(extra="forbid")

    intent: str | None = None
    agent: str | None = Field(
        default=None,
        description=(
            "Which agent should have answered this message — [ADR-0031] §6.\n\n"
            "Only a dispatch case sets it. It is a plain `str` for the same reason "
            "`intent` is: the harness must not hold a list of agent keys, or it "
            "learns which agents exist and the third one becomes a refactor.\n\n"
            "**A single accuracy number over these hides the thing worth knowing.** "
            "The misroute is asymmetric — one direction is answered by the wrong "
            "agent, the other fetches a human — so `summarise` also reports the "
            "expected-to-chosen matrix, and that is where the cost is legible."
        ),
    )
    tools_called: list[str] | None = Field(
        default=None, description="Exact set of tools expected, order-insensitive"
    )
    tools_not_called: list[str] | None = Field(
        default=None, description="Tools that must NOT be invoked — the safety assertion"
    )
    must_contain: list[str] = Field(
        default_factory=list, description="Substrings required in the reply (case-insensitive)"
    )
    must_not_contain: list[str] = Field(default_factory=list)
    grounded: bool | None = Field(
        default=None,
        description="Every factual claim supported by retrieved context or tool output",
    )
    escalated: bool | None = None
    refused: bool | None = None
    blocked: bool | None = Field(
        default=None,
        description=(
            "The guard recognised a named attack and ended the turn without a person. "
            "Distinct from `escalated`, and the distinction is the point: both end "
            "without an answer, only one costs a human (ADR-0012). Assert `false` on "
            "benign cases as well — a dataset that only ever asserts `true` measures "
            "sensitivity and cannot see a guard that blocks real customers."
        ),
    )
    unauthorised_tool_calls: int | None = Field(
        default=None,
        description="For adversarial cases. Must be 0 — asserted against the audit log, not the reply text",
    )
    pii_leaked: bool | None = Field(
        default=None,
        description=(
            "Whether the agent's OWN outbound filter found personal data in the reply "
            "that nothing in the turn accounted for (security-model.md §6.3).\n\n"
            "Be precise about what this is evidence of. It is a regression check on "
            "that filter — it can fail, and it does when the filter stops running. It "
            "is NOT independent evidence that no leak occurred, because the thing "
            "reporting is the thing being asked about. The independent check is "
            "`must_not_contain` with a specific value, and `injection_005` uses it.\n\n"
            "Declared but never scored between milestones 1.4 and 1.12, which meant "
            "three security cases carried an assertion that did nothing."
        ),
    )


class SessionContext(BaseModel):
    """Who is asking, and what has already been proven about them.

    ``verified_customer_id`` is the difference between "may read this order" and
    "may not" — see docs/architecture/security-model.md §3.
    """

    model_config = ConfigDict(extra="forbid")

    verified_customer_id: str | None = None
    locale: str = "en"
    channel: str = "web"
    history: list[dict[str, str]] = Field(
        default_factory=list, description="Prior turns, oldest first"
    )


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    intent: str
    input: str
    expect: Expectation
    session: SessionContext = Field(default_factory=SessionContext)
    fixtures: list[str] = Field(
        default_factory=list, description="Fixture files providing store data for this case"
    )
    synthetic: bool = Field(
        default=False,
        description="Invented rather than taken from a real conversation. NEVER counted as validation.",
    )
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _adversarial_cases_must_assert_safety(self) -> EvalCase:
        """An adversarial case that does not assert on tool calls proves nothing.

        A reply can *sound* like a refusal while a tool was quietly invoked; only
        the audit-log assertion catches that.
        """
        if self.intent == ADVERSARIAL and self.expect.unauthorised_tool_calls is None:
            raise ValueError(
                f"adversarial case '{self.id}' must set expect.unauthorised_tool_calls "
                "(it should be 0) — asserting on reply text alone is not a safety test"
            )
        return self


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    cases: list[EvalCase]

    @property
    def synthetic_count(self) -> int:
        return sum(1 for c in self.cases if c.synthetic)

    @property
    def is_fully_synthetic(self) -> bool:
        return bool(self.cases) and self.synthetic_count == len(self.cases)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Dataset:
        seen: set[str] = set()
        duplicates = {c.id for c in self.cases if c.id in seen or seen.add(c.id)}  # type: ignore[func-returns-value]
        if duplicates:
            raise ValueError(f"duplicate case ids in '{self.name}': {sorted(duplicates)}")
        return self


def load_dataset(path: Path) -> Dataset:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.setdefault("name", path.stem)
    return Dataset.model_validate(raw)


def load_all(directory: Path) -> list[Dataset]:
    """Load every dataset in a directory, sorted by name for stable reports."""
    return [load_dataset(p) for p in sorted(directory.glob("*.yaml"))]
