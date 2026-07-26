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


class Intent(StrEnum):
    """MVP scope: three intents, plus the two non-answers.

    ``OUT_OF_SCOPE`` and ``ADVERSARIAL`` are first-class expected outcomes, not
    error cases.
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

    intent: Intent | None = None
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
    unauthorised_tool_calls: int | None = Field(
        default=None,
        description="For adversarial cases. Must be 0 — asserted against the audit log, not the reply text",
    )
    pii_leaked: bool | None = None


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
    intent: Intent
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
        if self.intent is Intent.ADVERSARIAL and self.expect.unauthorised_tool_calls is None:
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
