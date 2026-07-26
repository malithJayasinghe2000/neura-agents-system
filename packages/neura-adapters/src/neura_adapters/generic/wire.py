"""The wire format of the Generic Commerce Interface.

**The spec is the canonical model.** A store's JSON response is a canonical
entity minus the fields only we can know — so there is no second vocabulary to
keep in sync, and adding a field to ``neura_domain`` changes the published spec
in the same commit (docs/architecture/adr/0009-generic-commerce-interface.md).

Three things stand between "the store's JSON" and "a canonical entity", and each
exists because of a specific way integrations fail:

* **Provenance is ours, not theirs.** A store cannot know its ``tenant_id`` or
  our ``neura_id``, and must not be trusted to assert ``platform``. Those fields
  are stripped from anything received and filled in here.
* **Unknown fields are dropped, not fatal.** A published spec that breaks when a
  store adds a field to its own JSON is a spec nobody can evolve. The original
  payload is preserved in ``raw``, so nothing is actually lost.
* **Unknown status values degrade to ``UNKNOWN``.** A single unrecognised status
  string must not make an order unreadable — an agent that cannot see the order
  at all is worse than one that says "I can't determine the status". The
  conformance tool reports the same condition as a warning, so it is visible
  rather than silently absorbed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

from neura_commerce import AdapterMappingError, HealthStatus
from neura_core import get_logger
from neura_domain import CanonicalEntity, Capability

log = get_logger(__name__)

#: The version of the published interface this client speaks.
SPEC_VERSION = "1.0"

#: Fields a store neither sends nor is believed about. See the module docstring.
PROVENANCE_FIELDS = frozenset({"neura_id", "tenant_id", "platform", "synced_at", "raw"})

#: Enum members used when a store sends a value we do not recognise, in
#: preference order. Every canonical status enum has one of these.
_FALLBACK_MEMBERS = ("UNKNOWN", "OTHER")


def _fallback_for(enum_cls: type[StrEnum]) -> str | None:
    for name in _FALLBACK_MEMBERS:
        member = enum_cls.__members__.get(name)
        if member is not None:
            return member.value
    return None


def _prune(value: Any, annotation: Any, *, path: str) -> Any:
    """Recursively drop unknown keys and downgrade unknown enum values.

    Type-guided rather than schema-guided: the canonical model is the only
    description of the wire format, so this cannot drift from it.
    """
    origin = get_origin(annotation)

    if origin in (Union, UnionType):
        variants = [a for a in get_args(annotation) if a is not type(None)]
        if value is None or len(variants) != 1:
            # An ambiguous union is left to Pydantic; guessing a member here
            # would be a mapping decision made without evidence.
            return value
        return _prune(value, variants[0], path=path)

    if origin in (list, set, frozenset, tuple):
        args = get_args(annotation)
        if args and isinstance(value, list):
            return [_prune(item, args[0], path=f"{path}[]") for item in value]
        return value

    if origin is dict:
        args = get_args(annotation)
        if len(args) == 2 and isinstance(value, dict):
            return {k: _prune(v, args[1], path=f"{path}.{k}") for k, v in value.items()}
        if value == []:
            # An empty map, sent by a language that cannot tell one from an
            # empty list. PHP's json_encode turns `[]` into a JSON array
            # whatever it meant, and most commerce platforms are written in PHP
            # — so refusing this would reject a majority of correct
            # implementations over a field nobody set. Non-empty lists still
            # fail, because those are genuinely the wrong shape.
            return {}
        return value

    if isinstance(annotation, type):
        if issubclass(annotation, StrEnum) and isinstance(value, str):
            if value in {member.value for member in annotation}:
                return value
            fallback = _fallback_for(annotation)
            if fallback is None:
                return value
            log.warning(
                "wire_enum_unmapped",
                field=path,
                enum=annotation.__name__,
                received=value,
                mapped_to=fallback,
            )
            return fallback

        if issubclass(annotation, BaseModel) and isinstance(value, dict):
            return _prune_fields(value, annotation, path=path)

    return value


def _prune_fields(payload: dict[str, Any], model: type[Any], *, path: str) -> dict[str, Any]:
    return {
        name: _prune(payload[name], field.annotation, path=f"{path}.{name}")
        for name, field in model.model_fields.items()
        if name in payload and name not in PROVENANCE_FIELDS
    }


def to_canonical[T: CanonicalEntity](
    model: type[T],
    payload: Any,
    *,
    neura_id: str,
    tenant_id: str,
    platform: str,
    synced_at: datetime,
) -> T:
    """Turn one store response into one canonical entity.

    Raises ``AdapterMappingError`` rather than returning something plausible: a
    half-mapped order produces a confidently wrong answer to a customer, which
    is the worst outcome available.
    """
    if not isinstance(payload, dict):
        raise AdapterMappingError(
            f"expected a JSON object for {model.__name__}, got {type(payload).__name__}"
        )

    data = _prune_fields(payload, model, path=model.__name__.lower())
    data.update(
        neura_id=neura_id,
        tenant_id=tenant_id,
        platform=platform,
        synced_at=synced_at,
        raw=payload,
    )

    try:
        return model.model_validate(data)
    except Exception as exc:
        raise AdapterMappingError(
            f"{model.__name__} payload does not conform to the interface: {exc}",
            details={"external_id": str(payload.get("external_id", "?"))},
        ) from exc


def to_wire[T: CanonicalEntity](entity: T) -> dict[str, Any]:
    """The inverse: what a conforming store should send for this entity.

    Used by the reference store and by the OpenAPI examples, so the documented
    shape is produced by the same rule the client parses.
    """
    return entity.model_dump(mode="json", exclude=set(PROVENANCE_FIELDS))


def parse_health(
    payload: Any,
    *,
    fallback_platform: str,
    latency_ms: int | None = None,
) -> HealthStatus:
    """Parse ``GET /health`` — the most consequential response a store sends.

    Capabilities declared here decide which tools the agent is given, so an
    unreadable health response is treated as an unusable store rather than
    defaulted to something permissive.

    Unrecognised capability strings are ignored with a warning. A store built
    against a later spec version must still be usable by this client; refusing
    the whole response over one unknown string would make the interface
    impossible to extend.
    """
    if not isinstance(payload, dict):
        raise AdapterMappingError(
            f"health response must be a JSON object, got {type(payload).__name__}"
        )

    known: set[Capability] = set()
    unknown: list[str] = []
    for raw_capability in payload.get("capabilities", []) or []:
        try:
            known.add(Capability(raw_capability))
        except ValueError:
            unknown.append(str(raw_capability))

    if unknown:
        log.warning("wire_capabilities_unknown", capabilities=unknown)

    # One spelling of "healthy", deliberately: `status: "ok"`. Accepting several
    # is how a contract becomes ambiguous, and ambiguity here decides whether a
    # merchant's store is treated as up.
    return HealthStatus(
        ok=str(payload.get("status", "")).lower() == "ok",
        platform=str(payload.get("platform") or fallback_platform),
        spec_version=str(payload.get("spec_version") or SPEC_VERSION),
        capabilities=frozenset(known),
        detail=payload.get("detail"),
        latency_ms=latency_ms,
    )


def spec_major(version: str) -> str:
    """Major component of a spec version. Compatibility is decided on this alone."""
    return version.split(".", 1)[0]
