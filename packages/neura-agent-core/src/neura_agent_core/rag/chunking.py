"""Canonical entities → retrievable text.

Two jobs, deliberately separated:

* **Rendering** — turn a ``Product``/``Category``/``Policy`` into the text that
  gets embedded. Retrieval quality is decided here more than anywhere else: an
  embedding can only find what the text says.
* **Splitting** — cut long text into overlapping pieces small enough for the
  embedder's context window.

**The rendered text is the contract.** Change a renderer and every vector
produced by the old one is subtly wrong — same product, different point in
vector space. That failure is invisible, so it is made visible instead: the
rendered text is content-hashed, and the indexer re-embeds anything whose hash
moved. Editing a renderer therefore causes a re-embed on the next run rather
than a silently mixed index.

Nothing here knows which platform an entity came from, and nothing here knows
which embedding model will be used — chunks are model-agnostic text until the
indexer embeds them.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from neura_commerce import EntityType
from neura_domain import Category, Policy, Product, ProductStatus

#: Rough character budget per chunk. Chosen against the smallest embedder we
#: ship with: ``nomic-embed-text`` takes 2048 tokens, and ~4 characters per
#: token leaves comfortable headroom. Deliberately characters, not tokens — a
#: tokeniser would tie chunking to one model family, and the whole point of the
#: role map is that the model is swappable.
DEFAULT_CHUNK_CHARS = 1200

#: Carried from the end of one chunk into the start of the next, so a sentence
#: split across a boundary is still retrievable from both sides.
DEFAULT_OVERLAP_CHARS = 150

#: Below this, a trailing fragment is folded back into the previous chunk rather
#: than stored alone. A three-word chunk matches everything and means nothing.
MIN_CHUNK_CHARS = 80

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class Chunk:
    """One retrievable unit of text, before it has been embedded."""

    tenant_id: str
    source_type: EntityType
    source_id: str
    chunk_index: int
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """Identifies the *text*, so unchanged text is never re-embedded."""
        return hashlib.sha256(self.content.encode()).hexdigest()[:32]


# ── Rendering ────────────────────────────────────────────────────────────────


def render(entity: Product | Category | Policy) -> str:
    """The text that will be embedded and later quoted back as evidence.

    Written to be read by a model *and* by a human reviewing why an answer was
    given. Labelled fields ("Price: …") beat bare values: the label is part of
    what the query matches against, and "how much is X" retrieves better when
    the word "price" is present in the document.
    """
    if isinstance(entity, Product):
        return _render_product(entity)
    if isinstance(entity, Category):
        return _render_category(entity)
    return _render_policy(entity)


#: Product statuses that are indexed. ``ACTIVE`` is obvious; ``UNKNOWN`` is the
#: interesting one, and it is included **on purpose**.
#:
#: ``UNKNOWN`` means the shop sent a status word we could not map, not that the
#: product is unavailable. Excluding it would empty the index for any shop whose
#: status vocabulary we have not seen — the agent would know nothing about their
#: entire catalogue, and the only symptom would be an agent that says "I don't
#: know" to everything. Weighed against the opposite error — occasionally
#: describing a product that turns out to be unavailable — that is far worse.
#:
#: So: tolerate, then report. The same decision the adapter layer made in
#: milestone 1.6 for unknown fields and capabilities.
INDEXED_PRODUCT_STATUSES = frozenset({ProductStatus.ACTIVE, ProductStatus.UNKNOWN})


def not_for_sale(entity: Product | Category | Policy) -> str | None:
    """Why this entity must not be indexed — or ``None`` if it may be.

    A ``DRAFT`` or ``ARCHIVED`` product is one the merchant has explicitly taken
    off sale. Indexing it means the agent can retrieve it, describe it and
    recommend it to a shopper who then cannot buy it — and the merchant is left
    explaining a product they deliberately unpublished.

    Only products carry a purchasable state. A category or a policy page is
    either present or absent; the shop deletes it rather than drafting it, and
    the sync engine already removes what has gone.
    """
    if isinstance(entity, Product) and entity.status not in INDEXED_PRODUCT_STATUSES:
        return f"status: {entity.status.value}"
    return None


def missing_content(entity: Product | Category | Policy) -> str | None:
    """Why this entity cannot usefully be embedded — or ``None`` if it can.

    Real catalogues contain half-finished records: a product row created and
    never named, a policy page with an empty body. They render to something
    structurally valid and semantically empty:

        Product:
        Availability: out of stock
        Status: active

    Embedding that is worse than skipping it. The vector carries no meaning, so
    it sits near the origin and can surface for queries it has nothing to do
    with — and if it ever *is* retrieved, the agent recommends a nameless
    product to a shopper.

    Note what is deliberately **not** checked: prose quality. A page reading
    "Return Policy Page Content" is a real string and gets indexed, because no
    rule can reliably tell placeholder prose from terse prose. Emptiness is
    unambiguous; vagueness is the merchant's call.
    """
    if isinstance(entity, Product):
        return "no title" if not entity.title.strip() else None
    if isinstance(entity, Category):
        return "no name" if not entity.name.strip() else None
    if not entity.title.strip():
        return "no title"
    # A policy *is* its body. A titled page with nothing in it gives the agent
    # nothing to ground an answer in, which is the one thing policies exist for.
    return "empty body" if not entity.body.strip() else None


def _render_product(product: Product) -> str:
    lines = [f"Product: {product.title}"]

    if product.price_range_min is not None:
        low = product.price_range_min
        high = product.price_range_max or low
        if low.amount == high.amount and low.currency == high.currency:
            lines.append(f"Price: {low}")
        else:
            lines.append(f"Price: {low} to {high}")

    # Availability is a question shoppers ask constantly, and it is cheap to put
    # in the text. It is also the field most likely to be stale, which is why
    # the sync engine's freshness matters to retrieval and not only to tools.
    in_stock = [v for v in product.variants if v.in_stock]
    if product.variants:
        lines.append(
            f"Availability: {len(in_stock)} of {len(product.variants)} variants in stock"
            if in_stock
            else "Availability: out of stock"
        )

    lines.append(f"Status: {product.status.value}")

    if product.description:
        lines.append("")
        lines.append(product.description)

    options = sorted(
        {
            f"{key}: {value}"
            for variant in product.variants
            for key, value in variant.options.items()
        }
    )
    if options:
        lines.append("")
        lines.append("Options — " + "; ".join(options))

    variant_titles = [v.title for v in product.variants if v.title and v.title != product.title]
    if variant_titles:
        lines.append("Variants — " + "; ".join(variant_titles))

    return "\n".join(lines).strip()


def _render_category(category: Category) -> str:
    lines = [f"Category: {category.name}"]
    if category.description:
        lines.append("")
        lines.append(category.description)
    return "\n".join(lines).strip()


def _render_policy(policy: Policy) -> str:
    # The kind is included on purpose. "Returns Policy" as a title is common, but
    # a merchant may call the page "Changed your mind?", and the canonical kind
    # is the only reliable word for a shopper asking about returns.
    return f"{policy.kind.value.replace('_', ' ').title()} policy: {policy.title}\n\n{policy.body}".strip()


# ── Splitting ────────────────────────────────────────────────────────────────


def split(
    text: str,
    *,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[str]:
    """Split on the strongest boundary that fits: paragraph, then sentence, then hard.

    Splitting mid-sentence loses the meaning of both halves, so a hard cut is
    the last resort rather than the mechanism.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces = _pack(_atoms(text, max_chars), max_chars)
    return _with_overlap(pieces, overlap_chars, max_chars)


def _atoms(text: str, max_chars: int) -> list[str]:
    """The smallest units we are willing to keep together."""
    atoms: list[str] = []
    for paragraph in _PARAGRAPH.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            atoms.append(paragraph)
            continue
        for sentence in _SENTENCE.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= max_chars:
                atoms.append(sentence)
            else:
                # One sentence longer than a whole chunk. Rare, but a wall of
                # unpunctuated text must still be indexed rather than dropped.
                atoms.extend(
                    sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars)
                )
    return atoms


def _pack(atoms: list[str], max_chars: int) -> list[str]:
    packed: list[str] = []
    current = ""
    for atom in atoms:
        candidate = f"{current}\n\n{atom}" if current else atom
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                packed.append(current)
            current = atom
    if current:
        packed.append(current)
    return packed


def _with_overlap(pieces: list[str], overlap_chars: int, max_chars: int) -> list[str]:
    if overlap_chars <= 0 or len(pieces) < 2:
        return pieces

    out = [pieces[0]]
    for index in range(1, len(pieces)):
        tail = pieces[index - 1][-overlap_chars:].lstrip()
        combined = f"{tail}\n\n{pieces[index]}"
        # Never let the overlap push a chunk past the embedder's budget — the
        # tail is a retrieval aid, not something worth truncating real text for.
        out.append(combined if len(combined) <= max_chars else pieces[index])
    return out


# ── The two joined ───────────────────────────────────────────────────────────


def chunk_entity(
    entity: Product | Category | Policy,
    *,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Render one entity and split it into chunks.

    Deterministic: the same entity always produces the same chunks in the same
    order, which is what lets the indexer compare hashes instead of re-embedding
    a catalogue every night.
    """
    source_type = _SOURCE_TYPES[type(entity).__name__]
    pieces = split(render(entity), max_chars=max_chars, overlap_chars=overlap_chars)
    pieces = _fold_short_tail(pieces, max_chars)

    return [
        Chunk(
            tenant_id=entity.tenant_id,
            source_type=source_type,
            source_id=entity.external_id,
            chunk_index=index,
            content=piece,
            metadata=_metadata(entity, part=index, of=len(pieces)),
        )
        for index, piece in enumerate(pieces)
    ]


def _fold_short_tail(pieces: list[str], max_chars: int) -> list[str]:
    if len(pieces) < 2 or len(pieces[-1]) >= MIN_CHUNK_CHARS:
        return pieces
    merged = f"{pieces[-2]}\n\n{pieces[-1]}"
    if len(merged) > max_chars:
        return pieces
    return [*pieces[:-2], merged]


def _metadata(entity: Product | Category | Policy, *, part: int, of: int) -> dict[str, Any]:
    """Kept small on purpose.

    This is carried into the model's context alongside the chunk, so every field
    costs tokens on every retrieval. It holds what an answer needs to cite a
    source — a title and a link — and nothing else. The full entity is a lookup
    away by ``source_id``.
    """
    meta: dict[str, Any] = {"part": part + 1, "of": of}

    if isinstance(entity, Product):
        meta["title"] = entity.title
        if entity.url:
            meta["url"] = entity.url
    elif isinstance(entity, Category):
        meta["title"] = entity.name
        if entity.url:
            meta["url"] = entity.url
    else:
        meta["title"] = entity.title
        meta["kind"] = entity.kind.value
        if entity.url:
            meta["url"] = entity.url

    return meta


_SOURCE_TYPES = {
    "Product": EntityType.PRODUCT,
    "Category": EntityType.CATEGORY,
    "Policy": EntityType.POLICY,
}

#: What the indexer will accept. Orders and customers are absent for the same
#: reason the sync engine does not store them: they are read live, and a
#: customer's data has no business sitting in a semantic index
#: (docs/architecture/commerce-integration.md §6.1).
INDEXABLE_TYPES: tuple[EntityType, ...] = (
    EntityType.PRODUCT,
    EntityType.CATEGORY,
    EntityType.POLICY,
)
