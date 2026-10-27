/**
 * *Missing from your pages* (ADR-0064, console.md §3.11): what the console's
 * own route returns, and the few words the page builds from it.
 */

/** One question at least 2 shoppers asked that the shop's pages don't say. */
export type GapTopic = {
  /** The short label the question is grouped by, e.g. `organic`. */
  fact: string;
  /** The question as the owner reads it, e.g. *Is it organic?* */
  question: string;
  shoppers: number;
  last_asked: string;
};

export type GapProduct = {
  product_id: string;
  /** `null` when the synced catalogue has no title for it. */
  title: string | null;
  /** The shop's own page, only when it is an http or https address. */
  url: string | null;
  topics: GapTopic[];
};

export type Gaps = {
  days: number;
  min_shoppers: number;
  /** When FiveNeurals switched the check off (ADR-0065), or `null`. */
  paused_since: string | null;
  /** How many questions the page shows. */
  total: number;
  groups: number;
  products: GapProduct[];
  /** *About your shop*: questions about the shop, not one product. */
  shop: GapTopic[];
};

/** *5 things*, *1 thing*. */
export function things(count: number): string {
  return count === 1 ? "1 thing" : `${count} things`;
}

/** *in 3 groups*, *in 1 group*. */
export function groups(count: number): string {
  return count === 1 ? "in 1 group" : `in ${count} groups`;
}

/** *Asked by 3 shoppers*. Never fewer than 2 on the page (R40). */
export function askedBy(shoppers: number): string {
  return shoppers === 1 ? "Asked by 1 shopper" : `Asked by ${shoppers} shoppers`;
}

/** Conversations narrowed to the chats one row counts (*See the chats*). */
export function chatsHref(
  tenantId: string,
  productId: string | null,
  topic: Pick<GapTopic, "fact" | "question">,
): string {
  const query = new URLSearchParams({ gap: topic.fact, asked: topic.question });
  if (productId) query.set("gap_product", productId);
  return `/console/${encodeURIComponent(tenantId)}/conversations?${query}`;
}
