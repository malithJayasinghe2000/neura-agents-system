"""What a turn actually saw, captured while it ran — [ADR-0034].

A graded turn is only worth promoting to an eval case if the case can be *run*
again, and a case can only be run again if the boundary the turn crossed can be
reproduced. [ADR-0032](../../../../docs/architecture/adr/0032-a-graded-turn-becomes-an-eval-case.md)
built promotion and left that unsolved; on 2026-09-06 the gap was measured — two
of three failures in the first real suite were the agent answering correctly
about the July fixture shop while the assertion came from the merchant's.

**The rejected fix is the one that looks obvious.** Rebuilding the case's store
afterwards from ``synced_entities`` reconstructs history from present state: for
the first case tried, *every* cited entity had already moved between the grade
and the attempt. It also cannot reproduce the boundary — the merchant's search
returned three products for a two-word query that this repository's fixture
matcher answers with none — so it fixes the data and leaves the case failing.

So evidence is **captured at turn time or not at all**, and this module is that
capture, its storage shape, and its replay.

## What is in a bundle, and what is deliberately not

Successful adapter calls with canonical arguments and canonical results; the
tools that ran, by name; retrieved context and its sources; the canonical
entities seen; a content fingerprint per entity; the store's declared
capabilities; the store id; the prompt revision; when it was captured.

**Failed calls are not recorded.** Replaying a transport error would freeze one
afternoon's network into a permanent assertion.

**``raw`` never enters a bundle.** It is the merchant platform's own payload, and
a fixture carrying it would put a platform's field names into an agent package —
[AGENTS.md](../../../../AGENTS.md) rule 1. It is stripped at capture, not at
export, so it is never written down at all.

## Two rules that look like details and are not

**A replay mismatch raises.** An adapter call the bundle does not hold is an
error naming what was asked and what was recorded. Returning an empty page
instead would be indistinguishable from a shop that stocks nothing, which is the
exact failure this module exists to remove, one layer further down.

**Nothing here is ever serialised into a response.** A bundle holds a merchant's
catalogue and the arguments a tool was called with. It travels from the recorder
to one database row and stops. It is not on ``TurnOutcome``, so no REST body, no
WebSocket frame and no progress event can carry it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from neura_core import get_logger
from neura_domain import Capability, InventoryLevel

log = get_logger(__name__)

#: Bumped when the bundle's shape changes in a way that makes an older row
#: unreplayable. Recorded on every bundle so a mismatch is a clear refusal
#: rather than a confusing failure three layers into a graph.
#:
#: **2 (2026-09-06)** — ``pii_output`` replaced a hard-coded list of tool names.
#: A version-1 row cannot answer *"did a PII-bearing tool run?"* except by that
#: list, which was agent knowledge living in the engine, so those rows are
#: refused at promotion rather than read optimistically.
#:
#: **3 (2026-09-06)** — retrieval records ``diagnosis`` and ``top_score``, the
#: two members of a result the ``retrieve`` node reads and this did not capture.
#: Purely additive: a version-2 bundle replays correctly, because both fields
#: default to what a non-empty result carries.
SCHEMA_VERSION = 3

#: Provenance the fixture loader fills in, and refuses to accept from a file. It
#: is stripped from every exported entity for the same reason `evals/store.py`
#: refuses it: those fields are ours to assign, and a fixture asserting them
#: would be asserting something no boundary checked.
#:
#: ``raw`` is not provenance — it is worse, and is dropped at capture (module
#: docstring). ``locale`` and ``external_id`` are deliberately absent from this
#: set: the first changes what a correct answer *is*, and the second is the
#: identifier every agent reasons with.
PROVENANCE_FIELDS = frozenset({"tenant_id", "neura_id", "platform", "synced_at"})

#: Dropped alongside provenance, and for a stronger reason.
PLATFORM_PAYLOAD_FIELDS = frozenset({"raw"})

#: Adapter methods whose results a bundle may hold. An allowlist rather than a
#: denylist: a method added to the protocol later is not silently recorded into
#: a file that goes to git, it fails the test that pins this set.
RECORDABLE = frozenset(
    {
        "get_product",
        "search_products",
        "list_products",
        "list_categories",
        "get_inventory",
        "get_policies",
    }
)

#: Never recorded, whatever a tool asks for. These return a person's orders or a
#: person themselves, and a promoted case is a file in a git repository.
#: `promotion` refuses a bundle whose turn touched a `pii_output` tool as well —
#: this is the second of the two gates, at the layer that would do the writing.
PII_METHODS = frozenset({"get_order", "list_orders", "find_orders_for_customer", "get_customer"})

#: Shapes that must never reach a file in this repository. Deliberately crude
#: and deliberately broad: a false positive costs one refused promotion and a
#: false negative costs a published secret.
_CREDENTIAL_PATTERNS = (
    re.compile(r"\b(?:bearer|token|secret|password|passwd|api[_-]?key)\b", re.I),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\b[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
)


class EvidenceError(RuntimeError):
    """A bundle cannot be captured, exported or replayed."""


class ReplayMismatch(EvidenceError):  # noqa: N818 - named for what it is, not its base
    """A promoted case asked for something its turn never asked for.

    Raised rather than answered with an empty result, because an empty result is
    indistinguishable from a shop that stocks nothing — and a case failing for
    *that* reason is the defect [ADR-0034] exists to remove.
    """


class RecordedCall(BaseModel):
    """One successful adapter call: what was asked, and what came back.

    ``result`` is the canonical object as ``neura_domain`` serialises it, with
    provenance and ``raw`` already gone. There is no platform anywhere in it.
    """

    model_config = ConfigDict(extra="forbid")

    method: str
    key: str = Field(description="Stable hash of method + arguments; the replay lookup key")
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None


class RetrievalEvidence(BaseModel):
    """What retrieval returned, and what it was asked."""

    model_config = ConfigDict(extra="forbid")

    query: str
    context: str = ""
    sources: list[str] = Field(default_factory=list)
    #: Why the result was empty, when it was. The ``retrieve`` node copies this
    #: into ``retrieval_note``, so a replay that dropped it would answer a
    #: different question from the one the human graded.
    diagnosis: str | None = None
    #: Logged rather than branched on, and captured anyway: a replay that has to
    #: invent a number is a replay that has stopped being a recording.
    top_score: float = 0.0

    @property
    def chunks_present(self) -> bool:
        return bool(self.context.strip() or self.sources)


class EvidenceBundle(BaseModel):
    """Everything needed to run one graded turn again.

    Immutable by convention and by storage: there is no update path, and
    ``ShadowEvidenceRepository.record`` refuses a second bundle for a turn.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    #: Which store's boundary this is. Internal scoping only — the data model
    #: permits several stores per tenant, and two of them may use the same
    #: `external_id` for different products. Never exported (`export_fixture`).
    store_id: str
    capabilities: list[str] = Field(default_factory=list)
    prompt_revision: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    calls: list[RecordedCall] = Field(default_factory=list)
    #: Successful tool invocations by name. Provenance only — **never** the
    #: input to a safety decision, because a name means nothing to this package.
    tools: list[str] = Field(default_factory=list)
    #: Whether any successful tool on this turn declared ``pii_output``.
    #:
    #: **Read from `ToolSpec.pii_output`, never from a list of names.** The
    #: earlier version held three tool names in this module, which is agent
    #: knowledge in the engine (AGENTS.md: *"neura_agent_core must not learn your
    #: agent's name"*) and, worse, a list that a new agent's PII-bearing tool
    #: would not be on. A tool that declares the flag is refused at promotion
    #: with no edit here — which is the only version of this rule that stays
    #: true as agents are added.
    pii_output: bool = False
    retrieval: RetrievalEvidence | None = None

    #: Canonical documents seen this turn, by fixture section name. What an
    #: exported fixture is made of, and where inventory is derived from.
    entities: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    #: ``"<section>:<external_id>" -> fingerprint``. Compared against the synced
    #: copy at promotion time, so a shop that moved refuses rather than failing
    #: later for a reason that looks like a regression (ADR-0032 §12).
    source_fingerprints: dict[str, str] = Field(default_factory=dict)

    def content_hash(self) -> str:
        """This bundle's identity — a hash over the artefact it exports to.

        **Taken over the exported file's own content, not over this model.**
        That distinction is not academic: the first version hashed
        ``model_dump()``, so adding one optional field to ``RetrievalEvidence``
        silently invalidated every artefact already written — the recomputed
        hash gained a ``"diagnosis": null`` the file on disk did not have, and a
        promoted case failed its integrity check having never been touched.

        Hashing the file's content instead makes the address a property of the
        bytes, which is what "content-addressed" has to mean for it to survive
        the schema evolving.
        """
        return content_hash_of(_replay_content(_artefact_payload(self)))

    @property
    def is_empty(self) -> bool:
        """Nothing to replay.

        A bundle with no successful call and no retrieval replays as a shop with
        nothing in it, which is :class:`ReplayMismatch`'s failure arriving by a
        route that does not raise. Promotion refuses it.
        """
        return not self.calls and not (self.retrieval and self.retrieval.chunks_present)


#: The exported keys a replay actually reads, and therefore the ones the
#: content hash covers. Everything else in an artefact is commentary:
#: ``_note`` is for a human, and ``_captured_at`` is a clock reading rather than
#: content — including it would give two captures of an identical shop two
#: artefacts, defeating the sharing §4 exists for. ``store_id`` is not in an
#: artefact at all (§7).
REPLAY_KEYS = (
    "schema_version",
    "capabilities",
    "prompt_revision",
    "calls",
    "tools",
    "pii_output",
    "retrieval",
    "entities",
    "source_fingerprints",
    "inventory",
)


def _replay_content(payload: dict[str, Any]) -> dict[str, Any]:
    """The hashable content of an artefact, taken straight from the file.

    Keys absent from an older artefact stay absent rather than being defaulted
    in — that is precisely what keeps a version-2 file's hash stable once
    version 3 adds a field.
    """
    return {key: payload[key] for key in REPLAY_KEYS if key in payload}


def content_hash_of(identity: dict[str, Any]) -> str:
    """The one hash function, so a writer and a reader cannot disagree.

    Defined once and used by :meth:`EvidenceBundle.content_hash` and by
    :func:`read_artefact`'s verification. Two implementations of "the same"
    hash is how a content address stops addressing its content.
    """
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def call_key(method: str, arguments: dict[str, Any]) -> str:
    """The replay lookup key for one call.

    Arguments are normalised through JSON with sorted keys, so a dict built in a
    different order is the same call. Anything unserialisable is stringified
    rather than dropped — a key that silently ignored an argument would make two
    different calls collide, and the replay would then answer confidently with
    the wrong thing.
    """
    material = json.dumps(
        {"method": method, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def fingerprint(document: dict[str, Any]) -> str:
    """A content fingerprint for one canonical entity.

    Same construction as ``synced_entities.fingerprint`` in spirit — a hash over
    the business content — and computed here rather than read from that table,
    because at turn time the entity came from the store and not from the sync.
    """
    material = json.dumps(_strip(document), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def _strip(document: dict[str, Any]) -> dict[str, Any]:
    """Provenance and platform payload out; everything a shopper's answer rests on in.

    ``external_id`` and ``locale`` survive deliberately — see PROVENANCE_FIELDS.

    **Recursive, and that is not a detail.** A recorded ``search_products``
    result is a ``Page`` whose *items* are the products, so stripping only the
    top level left ``raw`` — a merchant platform's own payload, with its own
    field names — inside every product of every recorded call. Caught by
    `test_raw_and_provenance_are_gone_and_the_rest_survives` rather than by
    review, which is the argument for that test existing.
    """
    return {
        key: _strip_value(value)
        for key, value in document.items()
        if key not in PROVENANCE_FIELDS and key not in PLATFORM_PAYLOAD_FIELDS
    }


def _strip_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _strip(value)
    if isinstance(value, list):
        return [_strip_value(item) for item in value]
    return value


def contains_credential(payload: Any) -> str | None:
    """The first credential-shaped string in a payload, or ``None``.

    Used as a refusal at promotion time. A fixture is a file in a repository and
    a repository is forever, so this errs toward refusing.
    """
    rendered = json.dumps(payload, sort_keys=True, default=str)
    for pattern in _CREDENTIAL_PATTERNS:
        if match := pattern.search(rendered):
            return match.group(0)
    return None


# ── Capture ──────────────────────────────────────────────────────────────────


class RecordingAdapter:
    """Wraps a store connection and records what the turn asked it.

    Structural, not inherited: it satisfies ``CommerceAdapter`` by having the
    methods, the same way an adapter conforms to the published spec. Everything
    it does not record it forwards untouched, so wrapping a store can never
    change what a shopper is told.

    **Recording happens on every turn**, because shadow mode is resolved *after*
    the graph has run (`agent-runtime.md` §6) and the turn that turns out to be
    worth grading cannot be known in advance. The cost is bounded by the tool
    ceiling and the bundle is discarded when the turn was not shadowed.
    """

    def __init__(self, adapter: Any, *, store_id: str) -> None:
        self._adapter = adapter
        self._store_id = store_id
        self._calls: dict[str, RecordedCall] = {}
        self._entities: dict[str, dict[str, dict[str, Any]]] = {}
        self._tools: list[str] = []
        self._pii_output = False
        self._retrieval: RetrievalEvidence | None = None

    def __getattr__(self, name: str) -> Any:
        """Anything not recorded is the store's own attribute, unchanged."""
        return getattr(self._adapter, name)

    # ── The recorded surface ─────────────────────────────────────────────────

    async def get_product(self, external_id: str) -> Any:
        return await self._record("get_product", {"external_id": external_id})

    async def search_products(self, query: Any) -> Any:
        return await self._record("search_products", {"query": _dump(query)}, query)

    async def list_products(self, query: Any, cursor: Any = None) -> Any:
        return await self._record(
            "list_products", {"query": _dump(query), "cursor": _dump(cursor)}, query, cursor
        )

    async def list_categories(self) -> Any:
        return await self._record("list_categories", {})

    async def get_inventory(self, variant_external_ids: list[str]) -> Any:
        return await self._record(
            "get_inventory",
            {"variant_external_ids": list(variant_external_ids)},
            list(variant_external_ids),
        )

    async def get_policies(self) -> Any:
        return await self._record("get_policies", {})

    # ── Everything a person owns is forwarded and NOT recorded ───────────────
    #
    # Explicit rather than inherited through `__getattr__`, so that "an order is
    # never written into a bundle" is visible here rather than being a property
    # of an allowlist somewhere else.

    async def get_order(self, external_id: str) -> Any:
        return await self._adapter.get_order(external_id)

    async def list_orders(self, query: Any, cursor: Any = None) -> Any:
        return await self._adapter.list_orders(query, cursor)

    async def find_orders_for_customer(self, ref: Any) -> Any:
        return await self._adapter.find_orders_for_customer(ref)

    async def get_customer(self, external_id: str) -> Any:
        return await self._adapter.get_customer(external_id)

    # ── Notes the caller adds ────────────────────────────────────────────────

    def note_tools(self, names: list[str], *, pii_output: bool = False) -> None:
        """Which tools ran, and whether any of them returns customer data.

        ``pii_output`` arrives as a bool rather than being looked up here,
        because the tool registry belongs to the agent and this package must not
        acquire a way to ask it questions by name.
        """
        self._tools = list(names)
        self._pii_output = pii_output

    def note_retrieval(
        self,
        query: str,
        context: str,
        sources: list[str],
        *,
        diagnosis: str | None = None,
        top_score: float = 0.0,
    ) -> None:
        self._retrieval = RetrievalEvidence(
            query=query,
            context=context,
            sources=sources,
            diagnosis=diagnosis,
            top_score=top_score,
        )

    # ── The result ───────────────────────────────────────────────────────────

    def bundle(
        self,
        *,
        capabilities: frozenset[Capability] | None = None,
        prompt_revision: str | None = None,
    ) -> EvidenceBundle:
        entities = {
            section: list(items.values()) for section, items in sorted(self._entities.items())
        }
        fingerprints = {
            f"{section}:{item.get('external_id')}": fingerprint(item)
            for section, items in entities.items()
            for item in items
        }
        return EvidenceBundle(
            store_id=self._store_id,
            capabilities=sorted(c.value for c in (capabilities or frozenset())),
            prompt_revision=prompt_revision,
            calls=list(self._calls.values()),
            tools=list(self._tools),
            pii_output=self._pii_output,
            retrieval=self._retrieval,
            entities=entities,
            source_fingerprints=fingerprints,
        )

    async def _record(self, method: str, arguments: dict[str, Any], *call_args: Any) -> Any:
        result = await getattr(self._adapter, method)(*call_args)
        key = call_key(method, arguments)
        self._calls[key] = RecordedCall(
            method=method, key=key, arguments=arguments, result=_dump(result)
        )
        self._collect(result)
        return result

    def _collect(self, result: Any) -> None:
        """File every canonical entity the call returned, by fixture section."""
        for entity in _entities_in(result):
            section = _SECTIONS.get(type(entity).__name__)
            if section is None:
                continue
            document = _strip(_dump(entity) or {})
            if external_id := document.get("external_id"):
                self._entities.setdefault(section, {})[str(external_id)] = document


class RecordingRetriever:
    """The retrieval half of the boundary, recorded into the same bundle.

    Wraps the real retriever and writes what it returned onto the adapter's
    recorder, so one bundle holds both halves. Separate objects because they are
    separate collaborators in the runtime, one recorder because a case that
    replayed its tools and re-ran its retrieval would be running against half a
    shop that no longer matches the half it replayed.
    """

    def __init__(self, retriever: Any, recorder: RecordingAdapter) -> None:
        self._retriever = retriever
        self._recorder = recorder

    def __getattr__(self, name: str) -> Any:
        return getattr(self._retriever, name)

    async def search(self, query: str, **kwargs: Any) -> Any:
        result = await self._retriever.search(query, **kwargs)
        try:
            self._recorder.note_retrieval(
                query=query,
                context=result.as_context() if result else "",
                sources=list(result.sources) if result else [],
                diagnosis=getattr(result, "diagnosis", None),
                top_score=float(getattr(result, "top_score", 0.0) or 0.0),
            )
        except Exception as exc:  # pragma: no cover - recording must never break a turn
            # A shopper's answer must not depend on whether we managed to write
            # evidence about it. The cost of failing here is one unpromotable
            # turn, and that is the correct trade.
            log.warning("evidence_retrieval_note_failed", error=str(exc))
        return result


#: Canonical class name -> the fixture section that holds it. The fixture format
#: is what an eval reads, and it is grouped by section rather than by type name.
_SECTIONS = {
    "Product": "products",
    "Category": "categories",
    "Policy": "policies",
}


def _dump(value: Any) -> Any:
    """Canonical JSON for anything the adapter returns.

    ``raw`` and provenance are removed *here*, at capture, rather than at export
    — so a platform's own payload is never written down at all rather than being
    written down and filtered later.
    """
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return _strip(value.model_dump(mode="json"))
    if isinstance(value, list | tuple):
        return [_dump(item) for item in value]
    if hasattr(value, "items") and hasattr(value, "model_dump"):  # pragma: no cover - defensive
        return _dump(value.model_dump(mode="json"))
    if hasattr(value, "items"):
        return {key: _dump(item) for key, item in value.items()}
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _entities_in(result: Any) -> list[Any]:
    """Canonical entities inside an adapter result, whatever its shape."""
    if result is None:
        return []
    if isinstance(result, list | tuple):
        return [item for item in result if isinstance(item, BaseModel)]
    items = getattr(result, "items", None)
    if isinstance(items, list):
        return [item for item in items if isinstance(item, BaseModel)]
    return [result] if isinstance(result, BaseModel) else []


# ── Export ───────────────────────────────────────────────────────────────────


def export_artefact(bundle: EvidenceBundle) -> dict[str, Any]:
    """The platform-neutral artefact a promoted case ships with.

    It carries **both halves**: the recorded calls a replay answers from, and the
    canonical entities a human can read to see what the case actually rests on.
    One file rather than two, because a replay artefact and a readable fixture
    that could drift apart would eventually disagree, and the one nobody reads
    would be the one deciding the test.

    ``store_id`` is dropped here and nowhere else is it dropped, so an exported
    file cannot say which of a tenant's stores it came from ([ADR-0034] §7).
    The stored bundle keeps it, and the hash recorded here is the stored
    bundle's, so the row and the file stay tied together.

    Refuses rather than filters when it finds something that must not be in a
    repository: a filter that silently removed a credential would leave nobody
    knowing one had been captured.
    """
    if secret := contains_credential(bundle.model_dump(mode="json")):
        raise EvidenceError(
            f"evidence contains a credential-shaped value ({secret!r}); refusing to export"
        )
    if bundle.pii_output:
        raise EvidenceError(
            "a tool declaring `pii_output` ran on this turn; a promoted case is a file "
            "in git and customer data may not be (ADR-0034 §8)"
        )
    if bundle.schema_version < 2:
        raise EvidenceError(
            f"evidence was captured under schema {bundle.schema_version}, which predates "
            "the `pii_output` flag and therefore cannot say whether a PII-bearing tool "
            "ran. Refusing rather than assuming it did not."
        )

    return _artefact_payload(bundle)


def _artefact_payload(bundle: EvidenceBundle) -> dict[str, Any]:
    """The artefact's bytes, with no refusals applied.

    Separate from :func:`export_artefact` because ``content_hash`` needs the
    payload and must not raise on a bundle nobody is exporting yet.
    """
    payload: dict[str, Any] = {
        "_note": (
            "Captured from a real graded turn — ADR-0034. Not hand-written and not "
            "reconstructed. Provenance, platform payload and store id are absent by "
            "construction; external_id and locale are kept because a correct answer "
            "depends on them."
        ),
        "_captured_at": bundle.captured_at.isoformat(),
        "schema_version": bundle.schema_version,
        "capabilities": list(bundle.capabilities),
        "prompt_revision": bundle.prompt_revision,
        "calls": [call.model_dump(mode="json") for call in bundle.calls],
        "tools": list(bundle.tools),
        "pii_output": bundle.pii_output,
        "retrieval": bundle.retrieval.model_dump(mode="json") if bundle.retrieval else None,
        "entities": {
            section: [_strip(item) for item in items] for section, items in bundle.entities.items()
        },
        "source_fingerprints": dict(bundle.source_fingerprints),
    }
    if inventory := derive_inventory(bundle):
        payload["inventory"] = inventory

    # Last, and over the payload itself: the address has to be a property of
    # what the file contains.
    payload["_content_hash"] = content_hash_of(_replay_content(payload))
    return payload


def load_artefact(payload: dict[str, Any]) -> EvidenceBundle:
    """An exported artefact back into a replayable bundle.

    ``store_id`` comes back empty because it was never written — replay does not
    read it, and reconstructing one would be inventing a fact the file
    deliberately does not carry.
    """
    return EvidenceBundle(
        schema_version=int(payload.get("schema_version", SCHEMA_VERSION)),
        store_id="",
        capabilities=list(payload.get("capabilities") or []),
        prompt_revision=payload.get("prompt_revision"),
        captured_at=datetime.fromisoformat(payload["_captured_at"])
        if payload.get("_captured_at")
        else datetime.now(UTC),
        calls=[RecordedCall.model_validate(call) for call in payload.get("calls") or []],
        tools=list(payload.get("tools") or []),
        pii_output=bool(payload.get("pii_output", False)),
        retrieval=RetrievalEvidence.model_validate(payload["retrieval"])
        if payload.get("retrieval")
        else None,
        entities=dict(payload.get("entities") or {}),
        source_fingerprints=dict(payload.get("source_fingerprints") or {}),
    )


def derive_inventory(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    """Stock levels, from the canonical variants that carry them.

    There is no ``inventory`` entity type — stock rides on each variant as
    ``in_stock`` and ``stock_quantity``, in the canonical model, in the synced
    document and in the fixture format alike. A fixture without this section
    silently disables the availability tool, so it is derived rather than
    omitted.
    """
    levels: list[dict[str, Any]] = []
    for product in bundle.entities.get("products", []):
        for variant in product.get("variants") or []:
            external_id = variant.get("external_id")
            if not external_id:
                continue
            levels.append(
                InventoryLevel(
                    variant_external_id=str(external_id),
                    quantity=int(variant.get("stock_quantity") or 0),
                    in_stock=bool(variant.get("in_stock")),
                ).model_dump(mode="json")
            )
    return levels


#: Where a promoted case's artefact lives, relative to an agent's fixture
#: directory. Content-addressed, so two cases that replay the same captured shop
#: share one file and no file's meaning moves under a case that cites it.
GRADED_DIR = "graded"


def artefact_path(fixture_dir: Path, content_hash: str) -> Path:
    return fixture_dir / GRADED_DIR / f"{content_hash}.json"


def read_artefact(fixture_dir: Path, content_hash: str) -> EvidenceBundle:
    """One promoted case's captured boundary, from the agent's own fixtures.

    Shared by every agent and imported by none of them from each other: this
    lives in ``neura-agent-core`` precisely so CARE and SELL can both replay
    without either learning the other exists (AGENTS.md, "Add an agent").

    A missing artefact is an error naming the path. It must never degrade to an
    empty store — that is [ADR-0034] §6, and the failure it prevents is a case
    that fails while looking exactly like a regression.
    """
    path = artefact_path(fixture_dir, content_hash)
    if not path.exists():
        raise EvidenceError(
            f"no evidence artefact at {path}. A promoted case replays captured "
            "evidence; without it there is nothing to run, and running against the "
            "base fixture instead is the defect ADR-0034 exists to remove."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    bundle = load_artefact(payload)
    _verify(path, content_hash, payload, bundle)
    return bundle


def _verify(path: Path, requested: str, payload: dict[str, Any], bundle: EvidenceBundle) -> None:
    """Three hashes must agree, or the artefact is not what it claims to be.

    1. **The filename** — what the case asked for.
    2. **The embedded ``_content_hash``** — what the file says it is.
    3. **The recomputed hash** — what the file's own content actually is.

    A content address that is never checked is a filename. All three are
    compared because each catches a different accident: a case citing the wrong
    artefact, a file renamed by hand, and a file edited in place — the last
    being the one that matters, because an edited artefact changes what a
    `synthetic: false` case asserts while still looking like evidence.

    **Loudly, never leniently.** A promoted case exists to be trusted more than
    an invented one; an artefact that cannot prove it is intact must stop the
    run rather than quietly answer from whatever it now contains.
    """
    embedded = str(payload.get("_content_hash", ""))
    recomputed = content_hash_of(_replay_content(payload))

    if embedded != requested:
        raise EvidenceError(
            f"evidence artefact {path.name} declares content hash {embedded!r} but was "
            f"requested as {requested!r}. The file was renamed, or a case cites the "
            "wrong artefact."
        )
    if recomputed != embedded:
        raise EvidenceError(
            f"evidence artefact {path.name} has been modified: it declares "
            f"{embedded!r} and its content hashes to {recomputed!r}. A promoted case "
            "asserts facts a human approved against exactly this evidence; running it "
            "against altered evidence would be a `synthetic: false` claim nobody made."
        )


# ── Replay ───────────────────────────────────────────────────────────────────


class ReplayAdapter:
    """A store that answers exactly what one recorded turn was told.

    Satisfies ``CommerceAdapter`` structurally. Used **only** by promoted eval
    cases: an invented case keeps the fixture store it was written against, and
    nothing in a serving path ever builds one of these.
    """

    def __init__(self, bundle: EvidenceBundle, *, tenant_id: str = "tn_replay") -> None:
        self._bundle = bundle
        self._calls = {call.key: call for call in bundle.calls}
        self._capabilities = frozenset(
            Capability(value) for value in bundle.capabilities if _is_capability(value)
        )
        # Assigned by this side, exactly as a fixture store assigns it. The
        # artefact carries none of this and must not.
        self._provenance = {
            "tenant_id": tenant_id,
            "platform": REPLAY_PLATFORM,
            "synced_at": bundle.captured_at,
        }

    @property
    def capabilities(self) -> frozenset[Capability]:
        """What the store could do on the day. A replay of a store that could
        not search must not present as one that could."""
        return self._capabilities

    async def health(self) -> Any:
        raise ReplayMismatch("health() is not part of a replayed turn")

    async def get_product(self, external_id: str) -> Any:
        return self._answer("get_product", {"external_id": external_id})

    async def search_products(self, query: Any) -> Any:
        return self._answer("search_products", {"query": _dump(query)})

    async def list_products(self, query: Any, cursor: Any = None) -> Any:
        return self._answer("list_products", {"query": _dump(query), "cursor": _dump(cursor)})

    async def list_categories(self) -> Any:
        return self._answer("list_categories", {})

    async def get_inventory(self, variant_external_ids: list[str]) -> Any:
        return self._answer("get_inventory", {"variant_external_ids": list(variant_external_ids)})

    async def get_policies(self) -> Any:
        return self._answer("get_policies", {})

    async def get_order(self, external_id: str) -> Any:
        raise ReplayMismatch(
            "orders are never recorded into evidence (ADR-0034 §8), so a promoted "
            "case can never replay one"
        )

    async def list_orders(self, query: Any, cursor: Any = None) -> Any:
        raise ReplayMismatch("orders are never recorded into evidence (ADR-0034 §8)")

    async def find_orders_for_customer(self, ref: Any) -> Any:
        raise ReplayMismatch("orders are never recorded into evidence (ADR-0034 §8)")

    async def get_customer(self, external_id: str) -> Any:
        raise ReplayMismatch("customers are never recorded into evidence (ADR-0034 §8)")

    def _answer(self, method: str, arguments: dict[str, Any]) -> Any:
        key = call_key(method, arguments)
        if (call := self._calls.get(key)) is None:
            raise ReplayMismatch(_mismatch(method, arguments, self._bundle))
        return _rehydrate(method, call.result, self._provenance)


@dataclass(frozen=True, slots=True)
class ReplayedRetrieval:
    """A recorded retrieval, in the shape the ``retrieve`` node reads.

    **Not the stored model, and that distinction cost a bug.** ``ReplayRetriever``
    used to hand back the ``RetrievalEvidence`` row itself, which has the right
    *data* and none of the right *members* — the node calls ``as_context()``,
    reads ``sources``, ``diagnosis`` and ``top_score``, and takes the result's
    truthiness. The unit test asserted on the stored model's fields and passed;
    the first real promoted case crashed with ``'RetrievalEvidence' object has no
    attribute 'as_context'``. **The end-to-end check found what the unit test was
    shaped not to.**

    Deliberately not a real ``RetrievalResult``: that one is built from chunks,
    and chunks are not what the node reads. Recording them would record more
    than the boundary, and reconstructing them from a rendered string would be
    inventing evidence.
    """

    query: str
    context: str
    sources: list[str]
    diagnosis: str | None = None
    top_score: float = 0.0

    def __bool__(self) -> bool:
        return bool(self.context.strip() or self.sources)

    def __len__(self) -> int:
        return len(self.sources)

    def as_context(self) -> str:
        return self.context


class ReplayRetriever:
    """The retrieval half of the same boundary."""

    def __init__(self, bundle: EvidenceBundle) -> None:
        self._retrieval = bundle.retrieval

    async def search(self, query: str, **_: Any) -> ReplayedRetrieval:
        if self._retrieval is None:
            raise ReplayMismatch(
                f"retrieval was asked for {query!r} but this turn recorded none — "
                "a promoted case cannot exercise a path its turn did not take"
            )
        recorded = self._retrieval
        return ReplayedRetrieval(
            query=recorded.query,
            context=recorded.context,
            sources=list(recorded.sources),
            diagnosis=recorded.diagnosis,
            top_score=recorded.top_score,
        )


def _mismatch(method: str, arguments: dict[str, Any], bundle: EvidenceBundle) -> str:
    """Why this failed, and what *was* available. Never an empty result.

    The diagnostic names the recorded calls because the usual cause is a model
    forming a slightly different query — and a reader who cannot see the recorded
    arguments has no way to tell that from a genuine regression.
    """
    recorded = "\n".join(
        f"    {call.method}({json.dumps(call.arguments, sort_keys=True, default=str)})"
        for call in bundle.calls
    )
    return (
        f"replay has no recorded result for {method}"
        f"({json.dumps(arguments, sort_keys=True, default=str)}).\n"
        f"  This turn recorded:\n{recorded or '    (nothing)'}\n"
        "  A promoted case replays one captured turn; it cannot answer a call that "
        "turn never made. Returning an empty result here would be indistinguishable "
        "from a store that stocks nothing (ADR-0034 §6)."
    )


def _is_capability(value: str) -> bool:
    try:
        Capability(value)
    except ValueError:
        log.warning("evidence_unknown_capability", capability=value)
        return False
    return True


#: What a replayed entity's ``platform`` says. Not a commerce platform and
#: deliberately so — the same call `evals/store.py` makes with ``"fixture"``.
#: Naming a real platform here would put one in a core package and break the
#: check that keeps the market position honest (AGENTS.md rule 1).
REPLAY_PLATFORM = "replay"


def _rehydrate(method: str, payload: Any, provenance: dict[str, Any]) -> Any:
    """Recorded JSON back into the canonical objects a tool expects.

    **Provenance is supplied here, never read from the artefact.** It was
    stripped at capture and the file does not carry it, which is the same rule
    `evals/store.py` applies to a fixture: ``neura_id``, ``tenant_id``,
    ``platform`` and ``synced_at`` are ours to assign and are never accepted
    from the other side of a boundary.
    """
    from neura_commerce import Page  # local: keeps the module importable standalone
    from neura_domain import Category, InventoryLevel, Policy, Product

    if payload is None:
        return None
    if method == "get_product":
        return Product.model_validate(_with(payload, provenance))
    if method in ("search_products", "list_products"):
        items = [
            Product.model_validate(_with(item, provenance))
            for item in (payload or {}).get("items", [])
        ]
        return Page(items=items)
    if method == "list_categories":
        return [Category.model_validate(_with(item, provenance)) for item in payload]
    if method == "get_inventory":
        # Not a canonical entity — no provenance to fill in.
        return [InventoryLevel.model_validate(item) for item in payload]
    if method == "get_policies":
        return [Policy.model_validate(_with(item, provenance)) for item in payload]
    raise ReplayMismatch(f"no rehydration rule for {method!r}")  # pragma: no cover


def _with(document: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    """One entity, plus the provenance this side assigns.

    ``neura_id`` is derived from the external id so it is stable between runs —
    a value that changed per run would make two replays of one artefact produce
    different objects, which is the opposite of the point.
    """
    external_id = str(document.get("external_id", ""))
    return {**document, **provenance, "neura_id": f"ne_replay_{external_id}"}


__all__ = [
    "GRADED_DIR",
    "PII_METHODS",
    "PROVENANCE_FIELDS",
    "RECORDABLE",
    "REPLAY_KEYS",
    "SCHEMA_VERSION",
    "EvidenceBundle",
    "EvidenceError",
    "RecordedCall",
    "RecordingAdapter",
    "RecordingRetriever",
    "ReplayAdapter",
    "ReplayMismatch",
    "ReplayRetriever",
    "ReplayedRetrieval",
    "RetrievalEvidence",
    "artefact_path",
    "call_key",
    "contains_credential",
    "derive_inventory",
    "export_artefact",
    "fingerprint",
    "load_artefact",
    "read_artefact",
]
