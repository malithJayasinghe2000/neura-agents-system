/**
 * The shapes the Shop screen reads. Read-only — see the route module for why.
 *
 * Two fields carry more than they look like:
 *
 * - `completed_at` is nullable and is **not** defaulted anywhere. A sync that
 *   has never finished and a sync that finished long ago are different facts,
 *   and only one of them should make a merchant worry. A screen that printed
 *   "never" as a date would merge them.
 * - `catalogue` counts what was actually synced. Orders and customers are
 *   deliberately absent: they are looked up live through the shop and never
 *   synced (commerce-integration.md), so a zero next to them would read as a
 *   broken sync rather than as a design decision.
 */

export type SyncStatus = {
  entity_type: string;
  /** `null` when a sync of this kind has never finished. Not a date. */
  completed_at: string | null;
  updated_through: string | null;
  last_run_count: number;
  /** A crawl is mid-flight. The cursor itself is never sent — it is opaque. */
  in_progress: boolean;
};

export type ConnectedStore = {
  id: string;
  /** The platform string stored on the row. A value, never a branch. */
  platform: string;
  base_url: string;
  status: string;
  catalogue: Record<string, number>;
  syncs: SyncStatus[];
};

export type ShopView = {
  stores: ConnectedStore[];
  /** Said by the server, not inferred from an empty array. */
  connected: boolean;
};

export type Health = {
  id: string;
  reachable: boolean;
  /** The adapter's own words when it is not. Never softened. */
  detail: string;
  capabilities: string[];
};

/** What each synced kind is called on screen. */
export const ENTITY_LABELS: Record<string, string> = {
  product: "Products",
  variant: "Variants",
  category: "Categories",
  policy: "Policy pages",
};
