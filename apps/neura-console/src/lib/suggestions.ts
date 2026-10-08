/**
 * The shapes the Suggestions screen reads — ADR-0050, redesigned 2026-09-28.
 *
 * For each product, who decides what a shopper's basket shows with it:
 *
 * - `owner` — the shop owner chose. It always wins; an empty list means
 *   "show nothing for this product".
 * - `automatic` — a stored AI pairing (on screen: *Chosen by AI*), used until
 *   the owner chooses.
 * - `pending` — nothing stored (on screen: *Automatic*). The basket decides
 *   from the product's own words each time, and nothing is saved — which is why
 *   the list alone cannot say what a shopper sees, and the **preview** exists.
 *
 * Whatever the mode, a shopper sees at most two, and only ones in stock at that
 * moment.
 */

export type SuggestionMode = "owner" | "automatic" | "pending";

export type Price = { amount: string; currency: string };

export type Suggested = {
  product_id: string;
  /** `null` when the synced catalogue no longer holds it. */
  title: string | null;
};

export type ProductSuggestions = {
  product_id: string;
  title: string | null;
  mode: SuggestionMode;
  /** The owner's whole list (up to `max_chosen`), or a stored AI pairing's ids. */
  suggested: Suggested[];
  chosen_at: string | null;
  /** Category names from the synced catalogue; empty when it has none. */
  categories: string[];
  price: Price | null;
};

export type SuggestionsPage = {
  products: ProductSuggestions[];
  /** How many products the owner may choose for one product. */
  max_chosen: number;
};

export type CategoryMenu = {
  /** Each named category the products carry, with how many are in it. */
  named: { id: string; name: string; count: number }[];
  /** How many products have no category — they can never get an automatic suggestion. */
  none: number;
};

export type SuggestionsMeta = {
  has_more?: boolean;
  next_cursor?: string | null;
  /** How many products match the filters — for "Showing 26–38 of 38". */
  total?: number;
  /** How many matching products come before this page. Counted, never used to fetch. */
  offset?: number;
  has_previous?: boolean;
  /** `null` with `has_previous` true means the page before is the first. */
  previous_cursor?: string | null;
  /** Given the search, never given the category — the menu always offers every way out. */
  categories?: CategoryMenu;
  /** Given the search, never given the mode filter — each chip says what it would show. */
  counts?: Record<"all" | SuggestionMode, number>;
  /** False when the catalogue is larger than the server counts. Said, not hidden. */
  counted_all?: boolean;
};

/** One card, exactly as a shopper's basket receives it. */
export type PreviewCard = {
  id: string;
  title: string;
  in_stock: "true" | "false";
  price?: string;
  currency?: string;
  url?: string;
  image?: string;
};

/**
 * What a shopper's basket shows with one product **now** — asked of the shop
 * when the owner opens the product, by the basket's own code, and never a model
 * run (`console.py`'s `preview`).
 */
export type Preview = {
  product_id: string;
  /** The list's row for this product; `null` when the synced catalogue lacks it. */
  product: ProductSuggestions | null;
  /** False when the shop did not answer. Said — never shown as "nothing". */
  reachable: boolean;
  asked_at: string;
  origin: "owner" | "model" | "words" | null;
  reason:
    "cannot_search" | "not_found" | "owner_nothing" | "no_category" | "nothing_matched" | null;
  heading: string | null;
  suggestions: PreviewCard[];
  /** What the AI looked for, when it has run for the product's current text. */
  ai: { kinds: string[]; found: number } | null;
};

export const MODE_LABEL: Record<SuggestionMode, string> = {
  owner: "Your choice",
  automatic: "Chosen by AI",
  pending: "Automatic",
};

/** The filter chips, in the owner-approved order. `""` is first: nothing hidden by default. */
export const MODE_FILTERS: { key: "" | SuggestionMode; label: string }[] = [
  { key: "", label: "All" },
  { key: "owner", label: MODE_LABEL.owner },
  { key: "automatic", label: MODE_LABEL.automatic },
  { key: "pending", label: MODE_LABEL.pending },
];

/** "$62.00" — or the amount and code as they are, for a code `Intl` refuses. */
export function money(price: Price | { amount?: string; currency?: string } | null): string {
  if (!price?.amount) return "";
  try {
    return new Intl.NumberFormat("en", {
      style: "currency",
      currency: price.currency || "USD",
    }).format(Number(price.amount));
  } catch {
    return `${price.amount} ${price.currency ?? ""}`.trim();
  }
}

/** "socks and shoe polish" · "rain pants, a waterproof bag and a towel". */
export function listed(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** Where the products shown came from, in one sentence under them. */
export function sourceLine(preview: Preview): string {
  if (preview.origin === "owner") return "Your choice — nothing automatic replaces it.";
  if (preview.origin === "model") {
    return preview.ai?.kinds.length
      ? `Picked by the AI — it looked for ${listed(preview.ai.kinds)}. Only what your shop sells, and only what is in stock.`
      : "Picked by the AI. Only what your shop sells, and only what is in stock.";
  }
  return "Picked automatically from this product’s own words.";
}

/**
 * When the AI has run but word matching is what shows, say what it tried —
 * otherwise an owner cannot tell "the AI found nothing" from "the AI never ran".
 */
export function aiNote(preview: Preview): string | null {
  if (preview.origin !== "words" || !preview.ai?.kinds.length) return null;
  const tried = listed(preview.ai.kinds);
  return preview.ai.found === 0
    ? `The AI also tried: it looked for ${tried}, matched nothing in your shop, so word matching is used.`
    : `The AI looked for ${tried}, but what it found cannot be shown right now — sold out or gone from your shop — so word matching is used.`;
}

/** Why nothing is shown with this product — something the owner can act on. */
export function whyNothing(preview: Preview): string {
  switch (preview.reason) {
    case "no_category":
      return "It has no category in your shop, so nothing can be picked for it automatically. Give it a category in your shop, or choose suggestions yourself.";
    case "owner_nothing":
      return preview.product?.suggested.length
        ? "None of the products you chose can be shown right now — they are sold out or no longer in your shop. Nothing automatic replaces your choice."
        : "You chose to show nothing with this product.";
    case "not_found":
      return "Your shop did not find this product just now. It may have been removed since your catalogue last synced.";
    case "cannot_search":
      return "Your shop’s connection does not allow searching, so nothing can be suggested automatically. You can still choose suggestions yourself.";
    default:
      return "Nothing in your shop matched this product’s own words well enough. You can choose suggestions yourself.";
  }
}
