"""Declaring a tool.

A tool is how the agent touches the world, so everything dangerous about it is
declared *here*, in code, and enforced by the policy engine — never described to
the model and hoped for.

    @tool(
        name="get_order_status",
        description="Look up the current status and tracking info for one order.",
        requires=[Capability.ORDER_READ],
        side_effect=SideEffect.READ,
        scopes=["care:order:read"],
        pii_output=True,
        requires_ownership="order_ref",
    )
    async def get_order_status(order_ref: str, ctx: ToolContext) -> OrderStatus: ...

Five declarations do the real work (docs/architecture/agent-runtime.md §3.1):

* ``requires`` — commerce capabilities. A tool whose requirements the tenant's
  store cannot satisfy is never offered to the model for that conversation, so
  it cannot be called and cannot fail at runtime.
* ``side_effect`` — ``READ`` / ``WRITE`` / ``IRREVERSIBLE``. Drives the approval
  gate. The MVP registers ``READ`` only (ADR-0010).
* ``scopes`` — checked against the caller's API key.
* ``pii_output`` — propagates a non-cacheable flag, so customer data cannot leak
  through the semantic response cache. Marked at the tool, not guessed from the
  text of a reply.
* ``requires_ownership`` — names the argument holding a customer-owned
  reference. The engine will not run the tool until *this session* has proven it
  may see that resource. Without a declaration the engine cannot know which
  argument is a stranger's order number, and "the prompt says to be careful" is
  not an access control (docs/architecture/security-model.md §3).

The argument schema is derived from the function signature, so the declaration
and the implementation cannot drift apart.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar

from pydantic import BaseModel, ConfigDict, create_model

from neura_domain import Capability, SideEffect

P = ParamSpec("P")
R = TypeVar("R")

#: The parameter every tool receives and none declares to the model. It carries
#: the tenant, the session and the store connection — none of which the model
#: may choose, which is precisely why it is not in the schema.
CONTEXT_PARAM = "ctx"

DEFAULT_TIMEOUT_S = 5.0


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    """What has been *proven* about who is in this chat. Server-side only.

    Never inferred from the conversation. A model can be talked into believing
    verification happened; a value held here cannot be
    (docs/architecture/security-model.md §3).

    Empty by default: an anonymous shopper has proven nothing, and the default
    for an access-control value must be "no access".
    """

    #: Set only when the store passed a customer id it had already authenticated.
    customer_external_id: str | None = None
    #: Order references this session has proven ownership of, one at a time.
    #: Verifying one order grants nothing about any other.
    verified_order_refs: frozenset[str] = frozenset()

    @property
    def is_authenticated(self) -> bool:
        return self.customer_external_id is not None

    def may_see(self, reference: str) -> bool:
        """Has this session proven it may see this specific resource?

        An authenticated customer is trusted for their own data; the adapter
        query is scoped to their id, so the reference is theirs by construction.
        An anonymous session must have verified each reference individually.
        """
        return self.is_authenticated or reference in self.verified_order_refs

    def with_verified(self, reference: str) -> SessionIdentity:
        return SessionIdentity(
            customer_external_id=self.customer_external_id,
            verified_order_refs=self.verified_order_refs | {reference},
        )


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything a tool needs that the model must not choose.

    The model supplies arguments. It does not supply which tenant it is acting
    for, which store to talk to, or what the session has proven — those arrive
    here, from the authenticated request, and no prompt can alter them.
    """

    tenant_id: str
    conversation_id: str
    #: What the tenant's store can actually do, from capability negotiation.
    capabilities: frozenset[Capability] = frozenset()
    #: What the caller's API key is allowed to do.
    scopes: frozenset[str] = frozenset()
    identity: SessionIdentity = field(default_factory=SessionIdentity)
    #: The tenant's commerce adapter. Typed loosely on purpose — a tool that
    #: needs one narrows it itself, and most tools do not need one at all.
    adapter: Any = None
    #: Set by tenant configuration; the policy engine reads it for check 4.
    allowed_tools: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A registered tool and everything the policy engine needs to authorise it."""

    name: str
    description: str
    fn: Callable[..., Awaitable[Any]]
    args_model: type[BaseModel]
    requires: frozenset[Capability] = frozenset()
    side_effect: SideEffect = SideEffect.READ
    scopes: frozenset[str] = frozenset()
    pii_output: bool = False
    requires_ownership: str | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S

    @property
    def is_read_only(self) -> bool:
        return self.side_effect is SideEffect.READ

    def json_schema(self) -> dict[str, Any]:
        """The argument schema handed to the model.

        Derived from the signature, so a parameter added to the function without
        a thought about the schema cannot silently become an unvalidated input.
        """
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return schema

    def tool_definition(self) -> dict[str, Any]:
        """OpenAI-compatible tool definition — the shape every provider speaks."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.json_schema(),
            },
        }

    def validate_arguments(self, arguments: dict[str, Any]) -> BaseModel:
        """Raises ``pydantic.ValidationError`` — the policy engine turns that into
        a rejection the ``act`` node can repair from."""
        return self.args_model.model_validate(arguments)


def tool(
    *,
    name: str,
    description: str,
    requires: Sequence[Capability] = (),
    side_effect: SideEffect = SideEffect.READ,
    scopes: Sequence[str] = (),
    pii_output: bool = False,
    requires_ownership: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Callable[[Callable[..., Awaitable[Any]]], ToolSpec]:
    """Declare a tool.

    Returns a :class:`ToolSpec` rather than the function, so an undeclared
    coroutine cannot be mistaken for a tool and registered by accident.
    """

    def decorate(fn: Callable[..., Awaitable[Any]]) -> ToolSpec:
        if not inspect.iscoroutinefunction(fn):
            # One blocking call in an async handler stalls the event loop for
            # every tenant, not just this conversation.
            raise TypeError(f"tool {name!r} must be async")

        args_model = _args_model_from_signature(name, fn)

        if requires_ownership is not None and requires_ownership not in args_model.model_fields:
            raise ValueError(
                f"tool {name!r} declares requires_ownership={requires_ownership!r} "
                f"but has no such argument; known arguments: "
                f"{sorted(args_model.model_fields)}"
            )

        return ToolSpec(
            name=name,
            description=description,
            fn=fn,
            args_model=args_model,
            requires=frozenset(requires),
            side_effect=side_effect,
            scopes=frozenset(scopes),
            pii_output=pii_output,
            requires_ownership=requires_ownership,
            timeout_s=timeout_s,
        )

    return decorate


def _args_model_from_signature(name: str, fn: Callable[..., Awaitable[Any]]) -> type[BaseModel]:
    """Build the argument schema from the function's own parameters.

    ``ctx`` is excluded: it is supplied by the runtime and must never appear in
    a schema the model can see, or the model could try to set it.
    """
    signature = inspect.signature(fn)
    hints = inspect.get_annotations(fn, eval_str=True)
    fields: dict[str, Any] = {}

    for parameter in signature.parameters.values():
        if parameter.name == CONTEXT_PARAM:
            continue
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            raise TypeError(
                f"tool {name!r} must not use *args or **kwargs — the schema needs names"
            )

        annotation = hints.get(parameter.name)
        if annotation is None:
            raise TypeError(f"tool {name!r} parameter {parameter.name!r} needs a type annotation")

        default = ... if parameter.default is inspect.Parameter.empty else parameter.default
        fields[parameter.name] = (annotation, default)

    if CONTEXT_PARAM not in signature.parameters:
        raise TypeError(f"tool {name!r} must accept a `{CONTEXT_PARAM}: ToolContext` parameter")

    return create_model(
        f"{_camel(name)}Args",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def _camel(name: str) -> str:
    return "".join(part.title() for part in name.replace("-", "_").split("_"))
