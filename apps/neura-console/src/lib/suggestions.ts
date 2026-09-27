/**
 * The shapes the Suggestions screen reads — ADR-0050.
 *
 * For each product, what a shopper's basket shows with it now, and who decided:
 *
 * - `owner` — the shop owner chose. It always wins; an empty list means
 *   "show nothing for this product".
 * - `automatic` — worked out by the system (a stored AI pairing), used until the
 *   owner chooses.
 * - `pending` — nothing stored yet. The system decides from the product's own
 *   words the first time a shopper's basket shows it.
 *
 * Whatever the mode, a shopper sees at most two, and only ones in stock at that
 * moment.
 */

export type SuggestionMode = "owner" | "automatic" | "pending";

export type Suggested = {
  product_id: string;
  /** `null` when the synced catalogue no longer holds it. */
  title: string | null;
};

export type ProductSuggestions = {
  product_id: string;
  title: string | null;
  mode: SuggestionMode;
  suggested: Suggested[];
  chosen_at: string | null;
};

export type SuggestionsPage = {
  products: ProductSuggestions[];
  /** How many products the owner may choose for one product. */
  max_chosen: number;
};
