# ADR-0040 — A Paired Suggestion Is A Fourth Surface, And Has No Model In It

**Status:** **Accepted** — owner decision, 2026-09-20; **built 2026-09-21** · **Date:** 2026-09-20 · **Extends:** [ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md) · **Supersedes:** nothing · **Related:** [ADR-0010](0010-read-only-mvp-tools.md), [ADR-0027](0027-a-constraint-miss-is-not-an-empty-store.md), [ADR-0029](0029-the-index-may-name-a-candidate-never-describe-one.md)

> **Accepted by owner decision on 2026-09-20 and built on 2026-09-21.** It records a decision the
> owner and one session reached in conversation on 2026-09-20, argued with before code existed
> rather than after.
>
> **What "built" means here, precisely:** `POST /v1/sell/suggestions`, the `neura_agent_sell.pairing`
> package and `pairs.js`, green on `make check`, `make test-widget` and `make pairs-check` — the last
> of which drives the block in **real headless Chrome**, in stub mode and live cross-origin. **Run
> against the real shop on 2026-09-21**, where §4's measured example reproduced: a cart holding the
> Lightweight Rain Shell is offered the Waterproof Hiking Shoe. **No shopper has seen it**, so nothing
> below is a measurement of whether it helps anyone, and the two parameters in §6 are still guesses.
>
> **Acceptance decides the design, not the schedule.** The same decision sequenced the build *after*
> the tester handover rather than before it, so that the tester's install report — the highest-value
> input available and the one that cannot be produced on the author's machine — is not delayed by a
> fourth surface. See [PROJECT_STATE](../../PROJECT_STATE.md), 2026-09-20.

## Context

SELL as built is a chat box. A shopper types, it answers. The owner's assessment on 2026-09-20 was
blunt and correct: **as a thing to sell, that is thin** — every competitor has a chat box.

The [v1 blueprint](../../archive/FiveNeurals_AI_Agents_Blueprint_v1.md) listed six SELL capabilities.
Measured against what exists: one is built (Sales Conversation AI), one is partial (upsell/cross-sell —
it suggests a second product, but only ever inside a reply to a question), and four are absent. Three of
those four — dynamic pricing, cart recovery, lead scoring — are **excluded by
[ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md) or blocked by
[ADR-0010](0010-read-only-mvp-tools.md)**, and two of them need write access that requires an approval
queue nobody has built.

**What is left is the reachable half of cross-sell**, and the thing that makes it reachable is that it
does not need to know who the shopper is:

| | needs identity? | needs timing? | needs the agent to speak first? |
|:--|:--:|:--:|:--:|
| Suggest a second product **when asked** *(built)* | no | no | no |
| **Suggest a paired product on the cart page** *(this ADR)* | **no** | **no** | **no** |
| Pop up when a shopper adds to cart | **yes** ([A21](../../open-questions.md)) | yes | yes |

The third row is a real project and is **not** what this decides. The second row reuses what exists.

## Decision

> **A paired suggestion is a fourth SELL surface: a page asks "what goes with product X", and gets
> back products chosen from the catalogue's own text by ordinary code. No model of ours runs in it,
> and it never claims to know what anyone bought.**

### 1. It is a fourth surface, and saying so is the point

[ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md) §2 fixed three surfaces:
the recommendation widget (has a graph), the MCP server (does not), the product feed (does not). This
is a fourth, and it belongs with the second and third: **no nodes, no prompts, no LLM call of ours
anywhere in it.**

Calling it "part of the widget" would be the tidy fiction ADR-0023 refused. It has a different
consumer, a different gate and a different failure mode.

### 2. The shop hands over product ids. We never ask about a cart.

**There is no cart in the Generic Commerce Interface** — nine read-only endpoints, and none of them is
a cart ([INTEGRATION_GUIDE §3](../../INTEGRATION_GUIDE.md)). **This does not add a tenth.**

The cart page already knows what it is displaying. It sends the ids:

```
  cart page  →  "1315, 1332 — what goes with these?"
  NEURA      →  "1332 Waterproof Hiking Shoe, 1304 Halden Cargo Trousers"
```

**NEURA is never told these came from a cart**, and must not be. They could be a wishlist, a page, or
a list typed by hand. This is what keeps the feature platform-independent: every shop has a cart and
**every shop exposes it differently**, so asking the shop about carts would mean per-platform code and
would break [Rule 1](../../../AGENTS.md) — the entire market position.

**The alternative was considered and rejected.** A `GET /cart/{id}` endpoint would need every shop to
build one more thing, would need a cart id, and a cart id means a session, which is
[A21](../../open-questions.md) — an open problem, imported into a feature that does not otherwise have
it.

### 3. Selection is by the product's own words, never by behaviour, and the label must say so

`sell.md` §300 is explicit: *"the ramp binds the moment anything is ranked by behaviour. **"Customers
also bought"**, propensity scoring, personalised ordering — none is in scope."*

**This selects on attributes the merchant wrote**, which is the same evidence `search_products` already
uses. The Rain Shell's description says *waterproof*; so does the Hiking Shoe's; they pair.

**The words on the screen are part of the decision, not styling.**

| on screen | allowed | why |
|:--|:--:|:--|
| "Goes well with your Lightweight Rain Shell" | ✅ | states the pairing and its reason |
| "Often bought together" | ❌ | a claim about behaviour |
| "Customers also bought" | ❌ | named out of scope by `sell.md` |
| "Trending" / "Popular" | ❌ | behaviour |

**There is no purchase history in this system.** A label implying one is a false claim to a shopper,
which is the single failure class this repository exists to prevent — the same class as
[Finding 37](../../TESTING_LOG.md), arriving through a heading instead of a sentence.

**The suggestion names the cart item it is paired with.** Not decoration: with three items in a cart,
an unlabelled "goes well with" is unattributable, and an attributed claim is one a shopper can judge
and reject. This is [ADR-0029](0029-the-index-may-name-a-candidate-never-describe-one.md)'s instinct
applied to a heading.

### 4. Never suggest from the same category, and show nothing rather than something poor

**Measured on the real shop, 2026-09-19:**

| search | returns |
|:--|:--|
| `waterproof` | Rain Shell, **Hiking Shoe** — a genuine pair |
| `jacket` | Merino Knit, Field Jacket, Quilted Vest, Flannel Overshirt — **four tops** |

**Word matching finds similar products; a pairing needs complementary ones.** A shopper with a jacket
in the cart does not want four more jackets. The `waterproof` result worked by luck — the matching word
happened to belong to a shoe.

So: **the category of the cart item is excluded from its own suggestions.** The shop's categories come
from `GET /categories`, which already exists.

**And an empty result is an acceptable result.** [ADR-0027](0027-a-constraint-miss-is-not-an-empty-store.md)
already established that a miss is not an empty store; the same applies here, with the block simply not
rendering. **Showing nothing costs a shopper nothing. Showing something silly costs the merchant's
trust in the whole product.**

### 5. No model runs in it

Every step is ordinary code: read the words, search, drop the same category, return at most two.

**This is a cost and safety decision, not an aesthetic one.** The cart page loads for every visitor; a
model call per page view is slow and is billed per view. A surface with no model **cannot fabricate a
product** and **cannot be prompt-injected**, which is the same argument ADR-0023 §2 makes for the MCP
server and the feed.

**And it constrains the output shape:** no sentence is generated. The block renders a product card —
name, price, image — and the fixed heading from §3. **The moment it writes prose about why two products
pair, a model is required and [Finding 37](../../TESTING_LOG.md)'s failure mode returns.**

### 6. The two parameters, and they are guesses

- **Which cart item?** The **most expensive**. It is usually the main purchase — the jacket, not the
  socks — and with §3's label the choice is visible to the shopper.
- **How many suggestions?** **Two.** One is easy to ignore; beyond two the weakest match is always
  visible, and a poor suggestion discredits the good one beside it.

**Both are informed guesses and neither is measured.** They are recorded here so they can be changed
against evidence rather than re-argued from taste. [CLAUDE.md §4](../../../CLAUDE.md) applies: these are
not measurements.

## Consequences

**Good.** A sellable capability that needs no identity, no consent, no behavioural data and no design
partner's history — the same property ADR-0023 says makes SELL shippable where MIND is not. It reuses
`search_products`, the category endpoint and the script-tag pattern the widget already proves. It is
measurable in a way the chat box is not: *of N carts shown a suggestion, M added it.*

**Bad.** It is a fourth surface to maintain, gate and document. It puts a NEURA-rendered block on a
page the merchant owns, which is a support burden the widget already has and this doubles. The
suggestion quality is bounded by how well merchants write product descriptions — a shop with thin
copy gets thin pairings, and nothing in this design can fix that.

**Accepted risk, stated plainly.** Attribute matching **will** produce some poor pairs. §4 reduces them
and does not eliminate them. The mitigation is that a poor pair is *visible and ignorable*, unlike a
false claim, which is *invisible and believed* — and that the block stays silent when it has nothing
good. **The failure mode chosen here is "unhelpful", never "wrong".**

**What would falsify this.** If, once measured, the suggestion is taken so rarely that it is noise, the
right response is to delete the surface rather than to add a model to it.

## What this ADR does NOT decide

- **The pop-up** — an agent speaking first, unprompted, when a shopper adds to a cart. That needs
  [A21](../../open-questions.md) resolved, behavioural events the bridge does not send, and a judgement
  about timing. Explicitly out.
- **The product page.** The same mechanism would work there. Cart first, because it is measurable:
  the shopper has already decided to buy, so *added it or did not* is a clean number.
- **Merchant-curated pairings.** Letting a merchant name pairs by hand is a reasonable later addition
  and a different decision — it needs a write path and a UI, and this has neither.
- **Whether it stays.** Acceptance decides the design and authorises the build; it does not decide
  that the surface survives contact with a shopper. **Nothing here has been built or measured**, and
  there is still no merchant on live traffic ([B2](../../open-questions.md)), which is the risk that
  outranks this one. *What would falsify this* stands unchanged: if the suggestion is taken so rarely
  that it is noise, delete the surface rather than add a model to it.
