# ADR-0041 — A Suggestion Is Delivered In The Panel We Own, And It May Open Itself Once

**Status:** **Accepted** — owner decision, 2026-09-24; **built 2026-09-24** · **Date:** 2026-09-24 · **Amends:** [ADR-0040](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md) (delivery and the pop-up exclusion) · **Supersedes:** nothing · **Related:** [ADR-0019](0019-widget-no-build-step.md), [ADR-0030](0030-a-product-card-is-fields-not-markup.md), [ADR-0031](0031-the-shopper-never-chooses-the-agent.md)

## Context

[ADR-0040](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md) decided *what* a paired suggestion is and left *where it renders* as a block on the merchant's own cart page. That shipped on 2026-09-21 and worked against the real shop.

**Then the owner asked the question that ADR could not answer: what does this cost the next platform?**

Measured against the Bagisto bridge, honestly:

| | what a shop must build |
|:--|:--|
| The assistant | paste a `<script>` tag |
| **A cart-page block** (ADR-0040) | **a template, an element placement, and styling that matches their theme** |

The block is not portable work. It is *per platform and per theme*, repeated for Shopify, for WooCommerce, and for every theme a merchant switches to. **That is the exact cost [Rule 1](../../../AGENTS.md) exists to keep out of this product** — not as a rule violation (no platform name entered our code; the check stays green) but as an erosion of the claim the rule protects: *connect any shop, easily.*

**And a second problem, which is the one that actually decides this.** A block on a page is passive — it is seen. A panel is opened. The owner's objection was blunt and correct: *"if user not open model when shopping that user not see that."* A suggestion nobody sees is not a cheaper feature; it is not a feature.

## Decision

> **The paired suggestion is delivered inside the assistant panel, which we own and which is already on every page. The shop passes product ids on the `<script>` tag that is already there. The panel may open itself — once per tab, only when there is something to show, and only when the merchant switched it on.**

### 1. The delivery moves; the surface does not

ADR-0040 §1 said the paired suggestion is a fourth surface with no model in it. **That is unchanged and is not reopened.** The endpoint, the selection, the category exclusion, the heading, the "show nothing rather than something poor" rule — all of it stands exactly as decided.

What changes is one line of that ADR's consequences: *"It puts a NEURA-rendered block on a page the merchant owns."* It no longer has to. It renders in the panel.

**The panel is ours.** It looks the same on every shop, it is styled once, it already renders product cards ([ADR-0030](0030-a-product-card-is-fields-not-markup.md)), and it already carries the Art. 50 disclosure. A suggestion delivered there inherits all of that and costs a storefront nothing to display.

### 2. The shop's whole integration is one attribute

```html
<script src="…/widget.js"
        data-neura-key="fn_pk_…"
        data-neura-products="1315,1320">   ← the entire change
</script>
```

The tag already exists. **No new template, no new element, no theme styling, nothing to place.**

`data-neura-products`, never `data-neura-cart`. ADR-0040 §2's reasoning is unchanged and is the reason the name matters: the interface has no cart endpoint and must not grow one, because every platform exposes a cart differently. The page says what it is displaying. It never says what that means.

### 3. The panel may open itself, and every condition on it is a restriction

ADR-0040's "what this ADR does NOT decide" excluded **the pop-up**: *"an agent speaking first, unprompted, when a shopper adds to a cart. That needs [A21] resolved, behavioural events the bridge does not send, and a judgement about timing."*

**This amends that exclusion, and the distinction is not a technicality:**

| ADR-0040's excluded pop-up | this |
|:--|:--|
| triggered by a **behavioural event** (added to cart) | triggered by **a page loading** |
| needs a session to know *whose* event | needs no identity at all |
| the **agent** speaks, unprompted | **no agent speaks** — a fixed heading and product cards, no model call |
| needs [A21](../../open-questions.md) | needs nothing that does not exist |

What remains true is the part ADR-0040 was right to be careful about: **a panel opening over a page is an interruption, and the cart page is the one place an interruption can cost the merchant money** rather than merely annoy somebody. So:

- **Off by default.** `NEURA_PAIRS_AUTO_OPEN=false`. A behaviour this intrusive is opted into, never inherited.
- **Only when there is a suggestion.** No products, no interruption. The empty case — which is [common on real catalogues](../../PROJECT_STATE.md) — costs the shopper nothing.
- **Once per tab.** Returning to the page does not reopen it. *Once is a suggestion; every visit is nagging.*
- **A switch, not a deploy.** One line of the shop's `.env` turns it off, because **nobody has measured whether this helps or hurts** and the honest response to that is a control, not a conviction.

### 4. Nothing generated, and the panel must not pretend otherwise

The heading is the server's fixed string and the cards are fields. **No model runs on either side**, which is what lets this render with no `verify` step in front of it.

So it renders with the `note` style and **not as an assistant bubble**. An assistant bubble would be the widget putting words in the agent's mouth — harmless while the words are fixed, and exactly the habit that would make a later generated line indistinguishable from a fixed one.

### 5. The cart-page block stays published, and no bridge ships a template for it

`pairs.js` is still served at `/v1/widget/pairs.js` and still gated by `make pairs-check`. Any shop that wants the block on the page itself, and will own the placement, can use it.

**The Bagisto bridge no longer carries a template for it** — removed 2026-09-24, once the panel version worked. Leaving a dormant template in a merchant's repository is dead code in somebody else's codebase, which is a worse thing to own than a published asset nobody mounts.

The asset is kept rather than deleted because it is built, tested and costs nothing unmounted — and because the measurement ADR-0040 asks for (*of N shown, M added*) will eventually want a passive variant to compare against.

## Consequences

**Good.** The per-platform cost of this feature drops from "a template and theme styling" to "one attribute on a tag that already exists." The suggestion renders in a surface we style once. It is seen, because the panel opens. The Art. 50 disclosure is inherited rather than re-solved.

**Bad.** The suggestion is now behind a panel, so a shopper who closes it loses it for that tab. Auto-open is an interruption on a page where interruptions are expensive, and **we have no evidence either way** — which is why it ships off, with a switch, and why this ADR must not be read as a claim that it works.

**What would falsify this.** If merchants turn auto-open off, or if cart conversion drops on shops that turn it on, the panel is the wrong place for an unrequested suggestion and the passive block was right. ADR-0040's own falsification test also still stands, one level up: if the suggestion is taken so rarely that it is noise, **delete the surface rather than add a model to it.**

## What this ADR does NOT decide

- **Any suggestion that needs identity.** Behavioural triggers, per-shopper targeting and the add-to-cart pop-up remain out, and [A21](../../open-questions.md) is still unresolved.
- **Email, outreach or cart recovery.** Excluded by [CLAUDE.md](../../../CLAUDE.md) and unaffected by this.
- **Anything the panel says in prose about a suggestion.** The moment a sentence is generated about why two products pair, a model is required and [Finding 37](../../TESTING_LOG.md)'s failure mode returns.
- **Whether auto-open is a good idea.** It is a switch, defaulted off, precisely because nobody knows.
