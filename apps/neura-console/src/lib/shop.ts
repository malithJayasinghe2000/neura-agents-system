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
  /** The newest full check of this connection (ADR-0052 §4), or `null`. */
  last_check: ShopCheck | null;
  /** When its token was last set. Never the token. */
  token_set_at: string | null;
};

/**
 * One run of the full check (ADR-0052 §4). `result` holds findings and counts,
 * never a token; it is `null` while the check is still running.
 */
export type ShopCheck = {
  id: string;
  store_id: string | null;
  address: string;
  status: "pending" | "done" | "failed";
  result: CheckResult | null;
  requested_at: string;
  finished_at: string | null;
};

export type CheckResult = {
  /** The one reason everything else failed, when there is one (G48). */
  cause:
    | null
    | "unreachable"
    | "no_bridge"
    | "not_ok"
    | "token_refused"
    | "address_refused"
    | "no_token";
  /** The server's own sentence, for `address_refused`. */
  message: string | null;
  passed: number;
  failed: number;
  warnings: number;
  /** Clean enough to connect: the whole check ran, and nothing failed. */
  conformant: boolean;
  capabilities: string[];
  /** The full result as plain text, for the developer. */
  text: string;
};

export type ShopView = {
  stores: ConnectedStore[];
  /** Said by the server, not inferred from an empty array. */
  connected: boolean;
  /**
   * Before the shop is connected (ADR-0052): when a token was made (never the
   * token) and the last check of the typed address. `null` once connected.
   */
  connect: { token_made_at: string | null; last_check: ShopCheck | null } | null;
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

// ── The full check, in plain words (ADR-0052 §4) ─────────────────────────────

/** What a clean check proved, for the owner: seven lines instead of nineteen check names. */
export const PASSED_WORDS = [
  "Your shop answers, and says what it can do",
  "Only your token gets in",
  "Products can be read and searched",
  "Orders can be looked up",
  "Long lists come page by page",
  "It can send only what changed",
  "Something missing answers \u201cnot found\u201d",
] as const;

/**
 * The one sentence for a check that found a single cause (G48), or for a check
 * that found problems of its own. The developer gets the full list separately.
 */
export function checkWords(result: CheckResult): { title: string; body: string } {
  switch (result.cause) {
    case "token_refused":
      return {
        title: "Your shop refused the token",
        body: "Your bridge answers, but not with the token you made. Ask your developer to put it in the bridge's settings, then press Check again.",
      };
    case "unreachable":
      return {
        title: "We couldn't reach this address",
        body: "Nothing answered. Check the address for typing mistakes, and ask your developer whether the bridge is online.",
      };
    case "no_bridge":
      return {
        title: "There is no bridge at this address",
        body: "Something answered, but not a NEURA bridge. Check the address with your developer: it usually ends in /neura/v1.",
      };
    case "not_ok":
      return {
        title: "Your bridge says it is not ready",
        body: "It answered, but not with \u201cok\u201d, so NEURA would treat your shop as down. Your developer can see why in the full check.",
      };
    case "address_refused":
      return {
        title: "NEURA won't call this address",
        body: result.message ?? "This address is not allowed.",
      };
    case "no_token":
      return {
        title: "There is no token to check with",
        body: "Make the shop token first.",
      };
    default:
      return {
        title:
          result.failed === 1
            ? "Your shop has 1 problem to fix"
            : `Your shop has ${result.failed} problems to fix`,
        body: "Send the full check to your developer. It says what is wrong and how to fix it.",
      };
  }
}

/** Where the guide for developers lives (ADR-0051). Live once the website is deployed. */
export const DEVELOPER_GUIDE_URL = "https://neura.fiveneurals.com/docs/developers/";
