# ADR-0077 · The Marketing Calendar's Open Points, Settled (G120, G126)

**Status:** **Accepted** · the owner, 2026-11-02: *"fix those with your recommended way"* (G120, G122, G125, G126,
D17) · built 2026-11-02, no mockup · **Date:** 2026-11-02 · **Changes, in part:**
[ADR-0072 §6](0072-grow-plans-a-campaign-for-each-date-the-shop-keeps.md) (the claim list's *treats*) and the approved
board 76's words (console.md §3.14) · **Related:** [ADR-0076](0076-the-owner-may-choose-a-plans-products.md) (G125,
settled with D20), the log's G120 to G126, D17

> **In one sentence:** *treats* is a food word again and still a claim when said of what a product does; a plan's
> products are *Products to promote*, a missing photo says so, and each post says which of the shop's own photos goes
> with it.

## Decision

### 1. *Treats* (G120)

ADR-0072 §6 put *treats* on the fixed claim list. It is also the ordinary word for sweets, and a honey shop's
Valentine's plan could not be made because of it (the first Gemini eval, 2026-11-01). **Now:** *treats* as a noun
passes (*sweet treats*, *festive treats*, *treats for the family*); **said of what a product does** (*treats colds*,
*treats your skin*, *treats the symptoms*) it is refused as a claim, by a rule in code next to the list. The rule is
conservative: *treats your family to* is refused too, and the model writes it another way. The retry names it:
*"write it only as a noun, as in 'sweet treats'"*. The prompt's list loses *treats* and gains that one sentence.

### 2. Photos and words on a plan (G126)

The owner, at the first real plan: the grey boxes and text-only posts were confusing (*"is this for promoting?"*).

- **Products to show** is now **Products to promote**.
- A product without a photo in the catalogue says **No photo in your shop** under the image placeholder.
- **Under each post, which photo goes with it**: the photo of the product its link opens (ADR-0074, R110), small, with
  *"Post it with this photo. Open the photo to save it."*, or *"No photo of [product] in your shop yet."* It is the
  shop's own photo from the synced catalogue; **no picture is made by AI** (D17: later, its own decision).

### 3. The others

- **G122** (Support sees *Shoppers asked for* rows inside a plan, without the link): kept as built (R99).
- **G125**: settled with D20, ADR-0076 §6.
- **D17** (AI-made pictures): later, after the shop's own photos (this ADR, §2).
- **G128** (a rate limit on `/go/`): deferred by the owner. **G121** (the plans' instructions): the owner's to read.

## What was tested

`tests/unit/test_grow_campaign.py` (*treats* as a noun passes in three sentences; as what a product does it is
refused in three; the retry explains it); `make console-check` (*Products to promote*, *No photo in your shop*, the
post's photo line). **The Gemini eval (cloud-prod), `calendar.yaml`, now 13 cases** (new: a sweets shop's Avurudu,
G120): **13 of 13, injection resistance 1.00, 13 calls, none refused**, 2026-11-02. In that run the sweets plan did not
use the word *treats*, so the eval shows the plan is made, not that the word now passes; the unit tests show that.

## Consequences

- One claim word is now judged by its use, not its spelling. Any other word moved that way needs the same: a rule
  in code, tests both ways, and an eval run.
