# ADR-0047 — A Kind Is Resolved By Meaning, Not By A Shared Word

**Status:** **Accepted** — owner decision, 2026-09-26 · **not built** · **Amends:** [ADR-0045](0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md) §3 · **Related:** [ADR-0005](0005-pgvector-not-qdrant.md), [ADR-0028](0028-only-the-catalogue-may-say-what-a-store-sells.md), [ADR-0029](0029-the-index-may-name-a-candidate-never-describe-one.md), [ADR-0040](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)

> **This changes one step and nothing else.** ADR-0045 §3 sends the model's *kinds*
> to `search_products`, a keyword engine over the merchant's own text. This lets
> them go to the **embedding index instead, or as well**. Everything else in
> ADR-0045 stands unchanged: no model between a shopper and an answer, kinds and
> never products, `heading_for` writes every visible word, and only ids the
> merchant's own catalogue holds may be shown.
>
> **Nothing here is built.** No vector search has ever been run on this surface.

## Context

**ADR-0045 was built on 2026-09-26 and its own §9 falsification test was run the
same day, twice. The second run is the reason this ADR exists.**

Run 1, against the 29-product Bagisto test shop: **words 19 of 29, model 19 of
29.** A flat tie. But the measurement named its own cause — **24 of 29 products
got correct kinds the shop does not stock.** That shop had ten categories, all
clothing and footwear, and sold no belt, no socks, no shoe polish and no wool
wash. Nine ordinary complements were added to its seeder.

Run 2, 38 products: **words 28, model 29.** Stocking the complements is what
moved the number, and it **moved the word path most** — 19 to 28 with no model
anywhere, because a belt described as *"full-grain leather"* is found by a loafer
described as *"polished calf leather"*.

**So after both runs there are two distinct reasons a kind produces nothing, and
only one of them is the catalogue's fault:**

| the model asked for | the shop | what happened |
|:--|:--|:--|
| `shoe horns`, `garment bags`, `pocket squares` | does not stock them | **Correct.** Empty is a result (ADR-0040 §4). No fix exists in software |
| `ankle socks` | sells **Merino Walking Socks** | **A miss we caused.** No shared word, so a keyword search returns nothing |
| `waterproof spray` | sells **Waterproofing Spray** | Matched, by luck of a shared stem |

**The second row is the whole of this ADR.** The model knew the answer, the
merchant stocks the answer, and the lookup in between threw it away because two
strings did not share a substring. `1327` Canvas Court Sneaker is the measured
instance: it asked for `ankle socks, shoe cleaner, waterproof spray`, the shop
stocks socks and a spray, and the block rendered **nothing**.

**This is an ordinary solved problem and the tool is already installed.**
[ADR-0005](0005-pgvector-not-qdrant.md) put pgvector in PostgreSQL; the indexer,
the embedder, `Namespace` and `Retriever.search` have been serving CARE's and
SELL's retrieval since milestone 1.9. Semantic lookup is also the industry's
answer to exactly this failure, rather than anything novel.

### Why ADR-0045 rejected embeddings, and why that rejection does not cover this

ADR-0045's Context table reads:

> **Embeddings** — nearest neighbour in meaning · Available (pgvector, an
> embedder). **Wrong relation**: a rain shell's nearest neighbour is another rain
> shell, which §4 then excludes. Similarity is the thing we already have too much
> of.

**That is correct and is not being reversed.** It rejects embeddings for
**product → product**: asking *"what is nearest to this rain shell"* returns
another rain shell, because similarity is not complementarity.

**This ADR proposes embeddings for a different pair of operands entirely:
phrase → product.** The question is not *"what is near this boot"* but *"which
product in this shop is this phrase"* — and `ankle socks` → Merino Walking Socks
is the same operation `Retriever.search` already performs on a shopper's
sentence. **The relation that decides complementarity is still the model's, and
is still the thing ADR-0045 bought.** Embeddings only carry its answer to the
shelf.

Both sentences are true at once and the distinction is the ADR:

* *A rain shell's nearest neighbour is another rain shell.* — still rejected.
* *"Waterproofing spray"'s nearest neighbour is the Waterproofing Spray.* — this.

## Decision

> **A kind may be resolved to the merchant's products by semantic search over
> their own indexed catalogue, in addition to the keyword search ADR-0045 §3
> names. Both are searches of the merchant's own data, and neither may return an
> id the merchant's catalogue does not hold.**

### 1. What ADR-0045 §3 becomes

**Was:** *the kinds are then searched in the merchant's own catalogue by the
existing `search_products` path.*

**Now:** the kinds are resolved against the merchant's own catalogue by
`search_products` **and** by `Retriever.search` over `EntityType.PRODUCT`, and
the union is the candidate set. Everything §3 says after that is unchanged:
**only ids that came back from one of those lookups may be stored**, and a model
that hallucinates *"Dry Bag Pro 2000"* produces a lookup that finds nothing.

### 2. The invariant survives, and it survives structurally rather than by care

A chunk's `source_id` **is the merchant's own `external_id`**
(`rag/chunking.py`), and the index contains nothing but entities our own sync
pulled from that tenant's shop, inside a `Namespace(tenant_id,
embedding_model)` with no un-namespaced read. So a vector hit is a product the
merchant sells, named in the merchant's own numbering.

**This is [ADR-0029](0029-the-index-may-name-a-candidate-never-describe-one.md)
unchanged, not stretched.** That ADR already permits the index to *name a
candidate* and forbids it from *describing one*. Here the index names a
candidate and every displayed field is then read live from the shop.

### 3. Both lookups, not one — and the reason is a measured one

Keyword search is not being replaced. On run 2 it produced 28 of 38 on its own,
and it has two properties semantic search does not: it is **exact** where a
merchant's own vocabulary is exact, and it **needs no index**, so it works for a
tenant who has never been indexed.

**So the union, with the keyword hits first.** `compute.py` already keeps
candidates in the model's own order and applies `select.is_complementary` to all
of them; a second source of candidates changes the input to that loop and
nothing else.

### 4. A tenant with no index loses nothing

Semantic resolution needs an indexed catalogue, and indexing is a separate
operation a merchant may not have run. An unpopulated or absent namespace
returns no chunks, the keyword hits stand alone, and the word path is still
underneath that. **Three tiers, each degrading to the next in silence** — which
is the same shape `structured.py` uses for provider capability and for the same
reason.

### 5. Everything about what a shopper sees is still untouched

Stated again because this is the third ADR in a row to touch this surface and
each one has had to say it:

* **`select.heading_for` writes every visible word.** The model writes none.
* **The anchor's own category is still excluded**, applied to a vector hit
  exactly as to a keyword hit.
* **Stock and status are still read live** on every request against stored ids.
  A vector index may be hours stale; the block never is.
* **Empty is still a result.** An absent index, an unreachable embedder and a
  kind nothing matches all render nothing.
* **No behavioural ranking.** A vector score orders candidates by *meaning*,
  never by what anyone bought or viewed — ADR-0040 §3 stands, and `ORDER` sync
  is still off.

### 6. Rule 4, and what it costs here

[Rule 4](../../../AGENTS.md) already reaches this surface since ADR-0045 §6.
`pairing.yaml` exists, and **injection resistance stays at 1.00** — measured as
*"every id shown came back from a lookup of the merchant's own catalogue"*, which
this ADR widens by one lookup and does not weaken.

**One new eval case is required and is the point of the change:** a kind the shop
stocks under a different word. `ankle socks` against a catalogue holding *Merino
Walking Socks* fails today and must pass after.

### 7. The parameters, and they are guesses

| parameter | value | why it is a guess |
|:--|:--|:--|
| `min_score` for a kind | **the retriever's default** | tuned for a shopper's sentence, not for a two-word phrase; not measured on either |
| products per kind | **`select.CANDIDATES_PER_TERM`** | matches the keyword path for symmetry, for no measured reason |
| order within the union | **keyword hits first** | the exact match is likelier to be what the merchant means; untested |

**None is tuned.** Same standing rule as ADR-0040 §6 and ADR-0045 §8: do not
repeat these as measured.

### 8. The falsification test, and it is NOT §9's

**ADR-0045 §9 chose coverage — how many products produce a suggestion — and run
2 showed that metric cannot answer the question.** Both arms rendered about the
same number of blocks (28 and 29) while differing in *which product was in them*:
the model paired the rain shell with waterproofing spray where words paired it
with a cotton frock, and paired the jersey frock with tights where words paired
it with chinos. **Coverage scores those identically.**

So this ADR is falsified differently, on the row it exists to fix:

> **Count the kinds that found nothing while the shop stocked the thing.** It is
> **2 of 38** on the measured run at minimum — `1327`'s `ankle socks` and
> `shoe cleaner`. If semantic resolution does not convert those, it has not done
> the one job it was added for, and it should be removed whatever coverage says.

**And a second measurement is required before either ADR is judged again:** a
hand-graded pass over the 38 blocks, words against model, by someone willing to
say which suggestion is better. Coverage cannot see quality, and quality is the
whole of what is being argued about.

## Consequences

**The paired suggestion gains a dependency on the RAG layer**, which it has never
had — so a surface that began with no model and no index now has both. Each is
optional and degrades silently, which is what keeps that acceptable, and each is
another thing that can be down.

**A merchant's catalogue must be indexed for the best behaviour**, which makes
indexing worth more than it was and makes *"is this shop indexed?"* a question
the console does not currently answer.

**It does not make the feature cheaper to justify.** ADR-0045's one-product
coverage gain is the number this is trying to improve, and if it converts the two
measured misses the gain is **three products, not one**. Whether that justifies a
prompt, a table, a job kind and an eval suite is the same open question, better
informed.

**Reversible, and more cheaply than ADR-0045 is.** Delete one lookup. The keyword
path, the word path and the whole cache are untouched.

## Alternatives considered

| approach | verdict |
|:--|:--|
| **Ask the model for the product, not the kind** | Rejected, and it is the thing ADR-0045 §3 exists to forbid. It would let a persuaded product description name a product, and *"only the store may say what it sells"* ([ADR-0028](0028-only-the-catalogue-may-say-what-a-store-sells.md)) is not negotiable for a search-engine convenience |
| **Give the model the catalogue to choose from** | Rejected. 10,000 products do not fit a prompt, the cost scales with the catalogue, and it reintroduces exactly the naming power above |
| **Broaden the keyword search** — stem, split, drop words | Considered seriously, because it needs no index. `tools/catalogue.py` already broadens a failed search this way. Rejected as the primary fix: it converts `ankle socks` → `socks` and would equally convert `shoe cleaner` → `shoe`, which matches every shoe in the shop. **Widening a keyword search trades a miss for a wrong answer**, and a wrong pairing is the expensive error here |
| **Let the merchant map kinds to categories by hand** | Rejected for ADR-0045's own reason: it moves work onto the person the product is supposed to save |
| **Do nothing and delete ADR-0045** | **Still live, and it is the owner's open decision.** This ADR is written so that the choice is between *the model path at its best* and the words, rather than between a half-wired model path and the words |

## What this ADR does NOT decide

* **It does not allow a model call on the request path.** ADR-0045's first
  non-negotiable is untouched; both lookups happen in the background job.
* **It does not reverse ADR-0045's rejection of embeddings for finding a
  pairing.** Product → product stays rejected. Only phrase → product is added.
* **It does not let the model name a product**, describe one, or write a word a
  shopper reads.
* **It does not authorise behavioural ranking.** ADR-0040 §3 stands.
* **It does not decide whether ADR-0045's surface is kept.** That decision is
  the owner's and is recorded in [PROJECT_STATE](../../PROJECT_STATE.md).
* **It does not require a reindex.** It reads the namespace the tenant already
  has; a shop with none simply keeps the keyword path.
