"""Which tools exist, and which of them a given conversation may see.

Two separate questions, and conflating them is how an agent ends up offering a
tool that cannot work:

* **Registered** — the tool exists in this deployment. Process-wide.
* **Available** — the tenant's store declares the capabilities it needs, and
  tenant policy permits it. Per conversation.

A tool the store cannot satisfy is **never put in the model's context at all**.
That is stronger than rejecting the call afterwards: the model cannot propose
what it has never been shown, so there is no failed call to explain, no wasted
turn, and no "the tool exists but errors" support ticket. It also removes a
class of prompt-injection target — you cannot talk a model into calling a tool
it does not know about.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from neura_agent_core.tools.spec import ToolContext, ToolSpec
from neura_core import get_logger
from neura_domain import Capability, SideEffect

log = get_logger(__name__)


class ToolRegistrationError(Exception):
    """A tool cannot be registered. Raised at import time, not call time."""


class ToolRegistry:
    """The tools one deployment knows about."""

    def __init__(self, tools: Iterable[ToolSpec] = ()) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for spec in tools:
            self.register(spec)

    def register(self, spec: ToolSpec) -> ToolSpec:
        """Add a tool. Refuses duplicates and anything that can mutate a store.

        The side-effect refusal is ADR-0010 made structural. The approval queue
        that a ``WRITE`` tool requires does not exist, so a ``WRITE`` tool
        registered today would be a tool that runs with no approval at all — the
        exact failure the ADR exists to prevent. Better to fail at import, in
        front of the developer adding it, than at runtime in front of a shopper.
        """
        if spec.name in self._tools:
            raise ToolRegistrationError(
                f"tool {spec.name!r} is already registered; names are how the model "
                "refers to tools, so they must be unique"
            )

        if spec.side_effect is not SideEffect.READ:
            raise ToolRegistrationError(
                f"tool {spec.name!r} declares side_effect={spec.side_effect.value!r}, but the "
                "MVP registers READ tools only. A WRITE tool needs the approval queue, which "
                "does not exist yet — see docs/architecture/adr/0010-read-only-mvp-tools.md."
            )

        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def available_for(self, ctx: ToolContext) -> list[ToolSpec]:
        """The tools this conversation may actually use.

        Filtered by what the store can do and what the tenant permits. The
        result is what goes in the model's context — nothing else exists as far
        as the model is concerned.
        """
        available = [
            spec
            for spec in self._tools.values()
            if self._satisfied(spec, ctx.capabilities) and self._permitted(spec, ctx)
        ]

        withheld = len(self._tools) - len(available)
        if withheld:
            # "Tool exists but the agent never calls it" is a listed gotcha in
            # AGENTS.md. This log line is how it gets diagnosed in one look.
            log.info(
                "tools_filtered",
                tenant_id=ctx.tenant_id,
                available=sorted(spec.name for spec in available),
                withheld=sorted(set(self._tools) - {spec.name for spec in available}),
            )

        return available

    def definitions_for(self, ctx: ToolContext) -> list[dict[str, object]]:
        """Tool definitions in the shape every OpenAI-compatible provider speaks."""
        return [spec.tool_definition() for spec in self.available_for(ctx)]

    @staticmethod
    def _satisfied(spec: ToolSpec, capabilities: frozenset[Capability]) -> bool:
        return spec.requires <= capabilities

    @staticmethod
    def _permitted(spec: ToolSpec, ctx: ToolContext) -> bool:
        # `None` means the tenant has expressed no preference, which is not the
        # same as an empty allow-list meaning "no tools".
        return ctx.allowed_tools is None or spec.name in ctx.allowed_tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._tools.values())

    def __contains__(self, name: object) -> bool:
        return name in self._tools
