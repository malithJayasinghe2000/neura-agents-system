/**
 * The shapes the Sold out screen reads — ADR-0046 stage 1, redesigned
 * 2026-09-28 (console.md §3.7).
 *
 * **Counts, never who.** There is no session token anywhere in this file, and
 * the API is tested to never send one: a merchant learns that a sold-out jumper
 * was opened 12 times in 9 visits, not which visits.
 *
 * The sentences under the list come from the server (`caveats`), because a
 * merchant-facing sentence hard-coded in a JavaScript bundle is one nobody
 * reviews and nobody can change (ADR-0020 §3).
 */
import type { Price } from "@/lib/suggestions";

export type SoldOutProduct = {
  product_id: string;
  /** `null` when the synced catalogue does not hold this product. */
  title: string | null;
  url: string | null;
  /** Category names from the synced catalogue; empty when it has none. */
  categories: string[];
  price: Price | null;
  /** Page views while the product could not be bought (ADR-0049). */
  views: number;
  /** Browsing sessions — on screen, *visits*: one visit, not one person. */
  sessions: number;
  last_viewed_at: string;
  /**
   * Whether it can be bought **now**, from the shop — `null` when the shop was
   * not asked, did not answer, or said nothing about this product.
   */
  in_stock_now: boolean | null;
};

export type SoldOut = {
  period: { since: string; through: string; days: number };
  /** Whether a data-processing agreement is on record. Without one, nothing is kept. */
  agreement: boolean;
  agreement_since: string | null;
  /** Did any product view arrive in the period, sold out or not. A yes or no. */
  receiving: boolean;
  /** How long a view is kept — the setting the retention sweep enforces. */
  kept_days: number;
  products: SoldOutProduct[];
  /** True when there were more products than one page lists. */
  truncated: boolean;
  /**
   * The one question asked of the shop for every product listed — `null` when
   * it was not asked (the screen asks with `?stock=now`; Home never does).
   */
  stock: {
    asked_at: string;
    answered: boolean;
    reason: "unreachable" | "not_supported" | null;
  } | null;
  /** Only the ones that are true right now. Never boilerplate. */
  caveats: string[];
};

/** The two halves of *"Opened **3 times**, in 1 visit"*. */
export function opened(product: SoldOutProduct): { times: string; visits: string } {
  return {
    times: product.views === 1 ? "once" : `${product.views} times`,
    visits: product.sessions === 1 ? "1 visit" : `${product.sessions} visits`,
  };
}

/** Why the shop could not say what is in stock — under the list, in a sentence. */
export function notCheckedLine(stock: NonNullable<SoldOut["stock"]>): string {
  return stock.reason === "not_supported"
    ? "Your shop's connection doesn't share stock levels, so we can't say what is in stock today. The counts are still right."
    : "Your shop did not answer just now, so we can't say what is in stock today. The counts are still right.";
}
