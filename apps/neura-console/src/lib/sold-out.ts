/**
 * The shapes the Sold out screen reads — ADR-0046 stage 1.
 *
 * **Counts, never who.** There is no session token anywhere in this file, and
 * the API is tested to never send one: a merchant learns that a sold-out jumper
 * was viewed 12 times from 9 sessions, not which sessions.
 *
 * The sentences under the list come from the server (`caveats`), because a
 * merchant-facing sentence hard-coded in a JavaScript bundle is one nobody
 * reviews and nobody can change (ADR-0020 §3).
 */

export type SoldOutProduct = {
  product_id: string;
  /** `null` when the synced catalogue does not hold this product. */
  title: string | null;
  url: string | null;
  /** Page views while the product could not be bought (ADR-0049). */
  views: number;
  /** Browsing sessions — one visit, not one person. */
  sessions: number;
  last_viewed_at: string;
};

export type SoldOut = {
  period: { since: string; through: string; days: number };
  /** Whether a data-processing agreement is on record. Without one, nothing is kept. */
  agreement: boolean;
  products: SoldOutProduct[];
  /** True when there were more products than one page lists. */
  truncated: boolean;
  /** Only the ones that are true right now. Never boilerplate. */
  caveats: string[];
};
