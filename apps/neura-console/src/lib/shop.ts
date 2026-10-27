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

import type { MadeBy } from "@/lib/api";

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
  /** Who made that token (ADR-0058 §6). `null`: not recorded, so nobody is named. */
  token_made_by?: MadeBy;
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
  /** Every ✘ and ⚠, in the developer's words. The owner's words: `warningWords`. */
  findings: CheckFinding[];
  /** The names of the checks that passed. The owner's words: `passedWords`. */
  passed_checks: string[];
  /** The full result as plain text, for the developer. */
  text: string;
};

export type CheckFinding = {
  check: string;
  severity: "error" | "warning";
  message: string;
  hint: string | null;
};

export type ShopView = {
  stores: ConnectedStore[];
  /** Said by the server, not inferred from an empty array. */
  connected: boolean;
  /**
   * Before the shop is connected (ADR-0052): when a token was made (never the
   * token) and the last check of the typed address. `null` once connected.
   */
  connect: {
    token_made_at: string | null;
    token_made_by?: MadeBy;
    last_check: ShopCheck | null;
  } | null;
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

/**
 * What a clean check proved, for the owner, in a few lines instead of about
 * twenty check names. **Only what this check tested and passed** (G51): the check
 * skips what a shop does not list, so a shop without orders is never told
 * *"Orders can be looked up"*. A line needs every check it names to have passed.
 */
const PASSED_LINES: { line: string; checks: string[] }[] = [
  { line: "Your shop answers, and says what it can do", checks: ["health"] },
  { line: "Only your token gets in", checks: ["auth.required", "auth.rejects_wrong_token"] },
  { line: "Products can be read", checks: ["products.get_missing"] },
  { line: "Products can be searched", checks: ["products.search_empty"] },
  { line: "Orders can be looked up", checks: ["orders.get_missing"] },
  { line: "Customers can be looked up", checks: ["customers.get_missing"] },
  { line: "Policy pages can be read", checks: ["policies"] },
  { line: "Long lists come page by page", checks: ["pagination"] },
  { line: "It can send only what changed", checks: ["sync.updated_since"] },
  { line: "Something missing answers \u201cnot found\u201d", checks: ["errors.not_found"] },
];

export function passedWords(result: CheckResult): string[] {
  const passed = new Set(result.passed_checks ?? []);
  return PASSED_LINES.filter(({ checks }) => checks.every((c) => passed.has(c))).map(
    ({ line }) => line,
  );
}

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

/**
 * What a warning means for the shop, in the owner's words (G75). A warning
 * does not stop Connect, but these change what shoppers get, so the owner reads
 * them, not only the developer. Any other warning is counted as a technical
 * detail; the full check has it.
 */
const WARNING_WORDS: Record<string, string> = {
  "products.status_vocabulary":
    "Some products don't say they are on sale, so NEURA never recommends them.",
  "orders.status_vocabulary":
    "Some orders use status words NEURA doesn't know, so the assistant can't tell a shopper how those orders are doing.",
  policies:
    "Your policy pages are missing or empty, so the assistant can't answer returns or shipping questions from them.",
  "products.search_no_match":
    "A search for words that match nothing still finds products, so the assistant is given products that don't fit the question.",
};

/** A check's warnings, one plain line each; the technical ones counted together. */
export function warningWords(result: CheckResult): string[] {
  const warnings = (result.findings ?? []).filter((f) => f.severity === "warning");
  const lines = warnings.flatMap((f) => (WARNING_WORDS[f.check] ? [WARNING_WORDS[f.check]] : []));
  const technical = warnings.length - lines.length;
  if (technical > 0) {
    lines.push(
      technical === 1
        ? "1 technical detail for your developer."
        : `${technical} technical details for your developer.`,
    );
  }
  return lines;
}

/** Where the guide for developers lives (ADR-0051). Live once the website is deployed. */
export const DEVELOPER_GUIDE_URL = "https://neura.fiveneurals.com/docs/developers/";
