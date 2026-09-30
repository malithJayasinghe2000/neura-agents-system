/**
 * The shapes the Shop connection screen reads — redesigned 2026-09-28 from the
 * owner's approved mockup (console.md §3.4), and still read-only towards the
 * shop: the one thing this screen writes is **our copy** of the catalogue.
 *
 * Three fields carry more than they look like:
 *
 * - `completed_at` is nullable and is **not** defaulted anywhere. A sync that
 *   has never finished and a sync that finished long ago are different facts,
 *   and only one of them should make a merchant worry. A screen that printed
 *   "never" as a date would merge them.
 * - `catalogue` counts what was actually synced. Orders and customers are
 *   deliberately absent: they are looked up live through the shop and never
 *   synced (commerce-integration.md), so a zero next to them would read as a
 *   broken sync rather than as a design decision.
 * - `setup.chat_box` is **when** the chat box's key was last used and **which
 *   addresses** it works from — never the key, its prefix, its hash or its
 *   scopes. The API selects two columns, so it cannot send more.
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

/** A sentence from the server, placed by its key beside the figure it explains. */
export type Note = { key: string; text: string };

/** A sync somebody asked for that has not finished yet. */
export type SyncAsked = { status: string; queued_at: string | null };

export type ConnectedStore = {
  id: string;
  /** The platform string stored on the row. A value, never a branch. */
  platform: string;
  base_url: string;
  status: string;
  catalogue: Record<string, number>;
  syncs: SyncStatus[];
  /** Synced products, and how many of them search by meaning can find. */
  index: { products: number; searchable: number };
  sync_asked: SyncAsked | null;
  notes: Note[];
};

export type ShopView = {
  stores: ConnectedStore[];
  /** Said by the server, not inferred from an empty array. */
  connected: boolean;
  /** Facts about the shop rather than one connection — all read from our own tables. */
  setup?: {
    /** `null` when the shop has no live chat box key at all. */
    chat_box: { last_used_at: string | null; origins: string[] } | null;
    agreement_since: string | null;
    /** Did any product view arrive in the window. A yes or no, never a count. */
    receiving: boolean;
    window_days: number;
  };
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
  category: "Categories",
  policy: "Policy pages",
};

/** In the order the owner reads them. Variants are not counted (sizes live inside a product). */
export const SHOWN_KINDS = ["product", "category", "policy"] as const;

/** `https://shop.example/neura/v1` → `shop.example`. The whole address stays in the details. */
export function host(address: string): string {
  try {
    return new URL(address).host || address;
  } catch {
    return address;
  }
}

/** `38 products`, `1 policy page` — a count with its noun. */
export function counted(count: number, kind: string): string {
  const [one, many] =
    kind === "product"
      ? ["product", "products"]
      : kind === "category"
        ? ["category", "categories"]
        : kind === "policy"
          ? ["policy page", "policy pages"]
          : [kind, kind];
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * One kind's last sync, in words. `last_run_count` is how many records that
 * sync **wrote** — new or changed — not how many it read: a full read of 38
 * unchanged products records 0. So a count is said as *"1 new or changed"*,
 * and 0 as *"no changes since the time before"* (beside *"11 policy pages"*,
 * a bare *"0 read"* looked like a contradiction).
 */
export function readLine(sync: SyncStatus, held: number): string {
  if (!sync.completed_at) return "has never finished";
  if (sync.last_run_count === 0)
    return held > 0 ? "no changes since the time before" : "none in your shop";
  return `${sync.last_run_count} new or changed`;
}

/**
 * The connection's kind, in words. `generic` is the one every shop that
 * implements our published specification uses — the standard bridge.
 */
export function connectionKind(platform: string): string {
  return platform === "generic" ? "Standard NEURA bridge" : platform;
}

export type Allowed = { what: string; note?: string };

/**
 * What the shop declared at `/health`, in the owner's words (console.md §3.4).
 * The codes are the shop's own declaration, not what we assume it can do; an
 * unknown code is shown as itself rather than dropped.
 */
export function allowedWords(codes: string[]): Allowed[] {
  const has = new Set(codes);
  const words: Allowed[] = [];
  const seen = new Set<string>();
  const take = (...names: string[]) => names.forEach((name) => seen.add(name));

  if (has.has("product.read") || has.has("product.search")) {
    words.push({
      what:
        has.has("product.read") && has.has("product.search")
          ? "Read and search your products"
          : has.has("product.read")
            ? "Read your products"
            : "Search your products",
    });
    take("product.read", "product.search");
  }
  const simple: [string, Allowed][] = [
    ["category.read", { what: "Read your categories" }],
    ["inventory.read", { what: "Check stock" }],
  ];
  for (const [code, allowed] of simple) {
    if (has.has(code)) words.push(allowed);
    take(code);
  }
  if (has.has("order.read") || has.has("order.search")) {
    words.push({ what: "Look up orders", note: "checked against the shopper first" });
    take("order.read", "order.search");
  }
  const rest: [string, Allowed][] = [
    ["customer.read", { what: "Read a customer's details" }],
    ["policy.read", { what: "Read your policy pages" }],
    ["cart.read", { what: "Read shopping baskets" }],
    [
      "sync.incremental",
      {
        what: "Copy only what changed",
        note: "Sync now still reads everything, so stock changes aren't missed",
      },
    ],
    [
      "events.realtime",
      { what: "Send change messages", note: "NEURA does not listen to these yet" },
    ],
    ["order.write", { what: "Change orders", note: "never used — your assistant is read only" }],
    [
      "cart.write",
      { what: "Change shopping baskets", note: "never used — your assistant is read only" },
    ],
  ];
  for (const [code, allowed] of rest) {
    if (has.has(code)) words.push(allowed);
    take(code);
  }
  for (const code of codes) if (!seen.has(code)) words.push({ what: code });
  return words;
}
