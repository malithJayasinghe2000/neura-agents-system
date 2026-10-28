/**
 * *Shoppers asked for* (ADR-0068, console.md §3.12): what the console's own
 * route returns, and the few words the page builds from it.
 */

/** One thing at least 2 shoppers asked for that the shop doesn't sell. */
export type WantedThing = {
  /** The short label it is grouped by, e.g. `matcha`. Plain text, checked in code. */
  label: string;
  /** The most recent question, e.g. *Do you have matcha?* */
  question: string;
  shoppers: number;
  last_asked: string;
};

export type Wanted = {
  days: number;
  min_shoppers: number;
  /** When FiveNeurals switched the night check off (ADR-0065), or `null`. */
  paused_since: string | null;
  total: number;
  items: WantedThing[];
};

/** *Matcha* for `matcha`: the label as the page shows it (board 67). */
export function thing(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/** Conversations narrowed to the chats one row counts (*See the chats*). */
export function wantedChatsHref(tenantId: string, label: string): string {
  return `/console/${encodeURIComponent(tenantId)}/conversations?${new URLSearchParams({ wanted: label })}`;
}
