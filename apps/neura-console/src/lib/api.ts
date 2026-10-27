/**
 * Talking to the NEURA API. ADR-0026.
 *
 * Every console request goes through here, and the two rules below are the
 * reason it is one file rather than a fetch call in each component.
 *
 * **1. `credentials: "include"`, always.** The session lives in an `HttpOnly`
 * cookie, which JavaScript cannot read by design — so nothing in the console
 * can attach a token by hand, and a request that forgets this flag is simply
 * anonymous. It fails as "signed out" rather than as an error, which is the
 * confusing direction, so the flag is set once here and never per call.
 *
 * **2. There is no API key in this file, and there must never be one.** The
 * browser is handed no tenant credential at all; the cookie names a person and
 * the server re-derives what they may do on every request. A key here would
 * carry the merchant's full machine authority into every browser extension and
 * screenshot — see ADR-0026 §3.
 */

/**
 * **Always same-origin.** `/api/*` is rewritten to the real API by
 * `next.config.ts`, and that indirection is the security boundary rather than a
 * convenience — see the comment there. Pointing this at the API's own host would
 * make every console request cross-origin, which the API cannot serve with
 * cookies without enabling CORS credentials on every endpoint it has.
 */
const BASE = "/api";

import type { AdminSwitch } from "@/lib/admin";
import type { ReviewTurn, Scorecard, Verdict } from "@/lib/review";
import type { ShopCheck, ShopView, SyncAsked } from "@/lib/shop";

/** The API's envelope: `{ data, meta }`, on success and on error alike. */
type Envelope<T> = { data: T; error?: { message?: string } };

export type Membership = { tenant_id: string; role: string };

export type Me = {
  signed_in: boolean;
  user_id?: string;
  memberships: Membership[];
};

async function call<T>(path: string, init?: RequestInit, prefix = "/v1/console"): Promise<T> {
  const response = await fetch(`${BASE}${prefix}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });

  const body = (await response.json().catch(() => null)) as Envelope<T> | null;

  if (!response.ok) {
    // The API's error envelope, when there is one. A raw status number tells a
    // merchant nothing, and inventing a friendly message here would hide the
    // real one from whoever has to debug it.
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  if (!body) throw new Error("The server sent a response we could not read.");

  return body.data;
}

/**
 * Ask for a sign-in link.
 *
 * Resolves identically whether or not the address has an account — the API
 * refuses to say, because "no account with that email" lets anyone walk a list
 * of shop owners' addresses and learn which merchants use us. The screen must
 * not try to be more helpful than this.
 */
export function requestSignInLink(email: string): Promise<{ message: string }> {
  return call("/auth/request-link", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

/** Redeem a one-time link. The session cookie is set by the response itself. */
export function verifySignInToken(
  token: string,
): Promise<{ signed_in: boolean; message?: string }> {
  return call("/auth/verify", { method: "POST", body: JSON.stringify({ token }) });
}

/**
 * Ask for a sign-up link (ADR-0058 §7). Resolves the same for every email, and
 * every email gets a link (R15), so the screen says the same words to everyone.
 */
export function requestSignUp(
  email: string,
  shopName: string,
  website: string,
): Promise<{ message: string }> {
  return call("/auth/sign-up", {
    method: "POST",
    body: JSON.stringify({ email, shop_name: shopName, website }),
  });
}

/** Use a sign-up link. The response's cookie signs them in; the shop waits. */
export function confirmSignUp(
  token: string,
): Promise<{ signed_in: boolean; tenant_id?: string; message?: string }> {
  return call("/auth/confirm-sign-up", { method: "POST", body: JSON.stringify({ token }) });
}

/** Approve a waiting shop with these assistants (ADR-0061 §7). */
export function approveShop(
  tenantId: string,
  agents: string[],
): Promise<{
  approved: boolean;
  name: string;
  assistants: string[];
  owners: string[];
  emailed: boolean;
}> {
  return call(
    `/shops/${encodeURIComponent(tenantId)}/approve`,
    { method: "POST", body: JSON.stringify({ agents }) },
    "/v1/admin",
  );
}

/** Switch one feature of a shop on or off (ADR-0065). `changed` is false for a no-op. */
export function setSwitch(
  tenantId: string,
  key: string,
  on: boolean,
): Promise<{ changed: boolean; switch: AdminSwitch }> {
  return call(
    `/shops/${encodeURIComponent(tenantId)}/switches/${encodeURIComponent(key)}`,
    { method: "PUT", body: JSON.stringify({ on }) },
    "/v1/admin",
  );
}

/** Refuse a waiting shop: it is removed, and its Owners are emailed (ADR-0061 §7). */
export function refuseShop(
  tenantId: string,
): Promise<{ refused: boolean; name: string; owners: string[]; emailed: boolean }> {
  return call(`/shops/${encodeURIComponent(tenantId)}/refuse`, { method: "POST" }, "/v1/admin");
}

/** Who is signed in, and which merchants they may act for — asked fresh. */
export function fetchMe(): Promise<Me> {
  return call("/me");
}

export function signOut(): Promise<{ signed_out: boolean }> {
  return call("/auth/sign-out", { method: "POST" });
}

/**
 * Record this person's verdict on one withheld turn.
 *
 * **No `reviewed_by`.** The machine endpoint takes a free string because it
 * cannot know who is calling; here the person *is* the thing that was
 * authenticated, and letting the browser name a reviewer would let one person
 * sign another's opinion. The API reads it from the session.
 */
export function gradeTurn(
  tenantId: string,
  turnId: string,
  verdict: Verdict,
  note: string,
): Promise<ReviewTurn> {
  return call(`/shops/${encodeURIComponent(tenantId)}/review/${encodeURIComponent(turnId)}/grade`, {
    method: "POST",
    body: JSON.stringify({ verdict, note }),
  });
}

// ── Shop connection (console.md §3.4) ────────────────────────────────────────

/**
 * *Sync now* — queues a fresh read of the shop into **our copy**. Nothing is
 * written to the shop. Pressing it again while one is queued or running
 * returns that one: it is one sync, not two.
 */
export function syncShop(
  tenantId: string,
  storeId: string,
): Promise<{ id: string; sync_asked: SyncAsked | null }> {
  return call(`/shops/${encodeURIComponent(tenantId)}/store/${encodeURIComponent(storeId)}/sync`, {
    method: "POST",
  });
}

/**
 * *Go live* (`live`) or *Back to practice mode* (`shadow`) on Home (ADR-0054).
 * Only the mode changes; the API records who switched it.
 */
export function setMode(
  tenantId: string,
  mode: "live" | "shadow",
): Promise<{ mode: "live" | "shadow"; withheld: boolean; changed: boolean }> {
  return call(`/shops/${encodeURIComponent(tenantId)}/mode`, {
    method: "PUT",
    body: JSON.stringify({ mode }),
  });
}

/** The shop's contact details, and the sentence a handed-over shopper reads (ADR-0055). */
export type ShopContactView = { email: string | null; phone: string | null; handover: string };

/**
 * Save the shop's contact details. A refused field comes back as one plain
 * sentence naming it (*"Email: this doesn't look like an email address…"*),
 * read from the API's 400, rather than *"Request validation failed."*
 */
export async function saveContact(
  tenantId: string,
  contact: { email: string; phone: string },
): Promise<ShopContactView> {
  const response = await fetch(`${BASE}/v1/console/shops/${encodeURIComponent(tenantId)}/contact`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(contact),
  });
  const body = (await response.json().catch(() => null)) as {
    data?: ShopContactView;
    error?: { message?: string; details?: { errors?: { loc?: unknown[]; msg?: string }[] } };
  } | null;
  if (!response.ok) {
    const first = body?.error?.details?.errors?.[0];
    const field = first?.loc?.at(-1);
    if (first?.msg && (field === "email" || field === "phone")) {
      const said = first.msg.replace(/^Value error, /, "");
      throw new Error(`${field === "email" ? "Email" : "Phone"}: ${said}.`);
    }
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  if (!body?.data) throw new Error("The server sent a response we could not read.");
  return body.data;
}

/**
 * The Review scorecard, read from the browser — for the side menu's badge. The
 * layout reads it once; this keeps it current as the owner moves around (G40).
 */
// ── Connecting a shop (ADR-0052) ──────────────────────────────────────────────
// The browser never sends a token: NEURA makes it and returns it once. The only
// thing these send is an address.

const shopPath = (tenantId: string) => `/shops/${encodeURIComponent(tenantId)}`;

/** Make the shop token. Returned **once**; nothing reads it back. */
export function makeShopToken(
  tenantId: string,
): Promise<{ token: string; made_at: string; made_by?: MadeBy }> {
  return call(`${shopPath(tenantId)}/token`, { method: "POST" });
}

/** A new token for a connected shop. Returned **once**. */
export function replaceShopToken(
  tenantId: string,
  storeId: string,
): Promise<{ token: string; made_at: string; made_by?: MadeBy }> {
  return call(`${shopPath(tenantId)}/store/${encodeURIComponent(storeId)}/token`, {
    method: "POST",
  });
}

/** Who made a secret: a name (or an email when they never gave one) and their
 * role now, `null` when they are no longer in the shop (ADR-0058 §6). */
export type MadeBy = { name: string; role: string | null } | null;

/** When the customer sign-in secret was made, and by whom (ADR-0057 §3). Never the secret. */
export type CustomerSecretView = { made_at: string | null; made_by?: MadeBy };

/** Make the customer sign-in secret, or a new one. Returned **once**. */
export function makeCustomerSecret(
  tenantId: string,
): Promise<{ secret: string; made_at: string; made_by?: MadeBy }> {
  return call(`${shopPath(tenantId)}/customer-secret`, { method: "POST" });
}

// People (ADR-0058 §4): the Owner's alone. The invite link is never in an
// answer; it goes by email only.

export type Invite = {
  id: string;
  email: string;
  role: string;
  sent_at: string;
  expires_at: string;
  expired: boolean;
};

/** Invite an email with a role. `emailed`: whether the email could be sent. */
export function sendInvite(
  tenantId: string,
  email: string,
  role: string,
): Promise<{ invite: Invite; emailed: boolean }> {
  return call(`${shopPath(tenantId)}/invites`, {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}

/** A new link for a waiting invite; the old one stops. */
export function sendInviteAgain(
  tenantId: string,
  inviteId: string,
): Promise<{ invite: Invite; emailed: boolean }> {
  return call(`${shopPath(tenantId)}/invites/${encodeURIComponent(inviteId)}/send-again`, {
    method: "POST",
  });
}

export function cancelInvite(tenantId: string, inviteId: string): Promise<{ cancelled: boolean }> {
  return call(`${shopPath(tenantId)}/invites/${encodeURIComponent(inviteId)}`, {
    method: "DELETE",
  });
}

export function changeRole(
  tenantId: string,
  userId: string,
  role: string,
): Promise<{ user_id: string; role: string }> {
  return call(`${shopPath(tenantId)}/people/${encodeURIComponent(userId)}`, {
    method: "PUT",
    body: JSON.stringify({ role }),
  });
}

export function removePerson(tenantId: string, userId: string): Promise<{ removed: boolean }> {
  return call(`${shopPath(tenantId)}/people/${encodeURIComponent(userId)}`, {
    method: "DELETE",
  });
}

/**
 * Use an invite link. A new account is signed in by the response's cookie; an
 * account that already exists is added and signs in as usual (R13).
 */
export function acceptInvite(
  shop: string,
  token: string,
): Promise<{ signed_in: boolean; joined?: boolean; tenant_id?: string; message?: string }> {
  return call("/auth/accept-invite", { method: "POST", body: JSON.stringify({ shop, token }) });
}

/** Start the full check: of a typed address, or of a connection. Returns at once. */
export function startShopCheck(
  tenantId: string,
  what: { address: string } | { store_id: string },
): Promise<{ check: ShopCheck }> {
  return call(`${shopPath(tenantId)}/checks`, { method: "POST", body: JSON.stringify(what) });
}

export function readShopCheck(tenantId: string, checkId: string): Promise<{ check: ShopCheck }> {
  return call(`${shopPath(tenantId)}/checks/${encodeURIComponent(checkId)}`);
}

/** Connect, after a clean check of this address. Queues the full copy. */
export function connectShop(
  tenantId: string,
  address: string,
): Promise<{ id: string; base_url: string }> {
  return call(`${shopPath(tenantId)}/connect`, {
    method: "POST",
    body: JSON.stringify({ address }),
  });
}

/** Home's own facts; here for the menu's count of shoppers waiting (ADR-0062). */
export function readHome(tenantId: string): Promise<{ waiting: number | null }> {
  return call(`/shops/${encodeURIComponent(tenantId)}/home`);
}

/**
 * Said on `window` after *Mark as answered*, so the menu reads its count again
 * at once. `router.refresh()` alone left the menu's number as it was until the
 * next page (found by `make console-check`, 2026-10-12).
 */
export const WAITING_CHANGED = "neura:waiting-changed";

/** *Mark as answered*: the shopper's email is deleted at once (ADR-0062 §7). */
export function markAnswered(
  tenantId: string,
  conversationId: string,
): Promise<{
  answered_at: string | null;
  answered_by: { name: string; role: string | null } | null;
}> {
  return call(
    `/shops/${encodeURIComponent(tenantId)}/conversations/${encodeURIComponent(conversationId)}/answered`,
    { method: "POST" },
  );
}

export function readScorecard(tenantId: string): Promise<Scorecard> {
  return call(`/shops/${encodeURIComponent(tenantId)}/review/scorecard`);
}

/** The screen's own read, again — used to notice when an asked-for sync finishes. */
export function readShop(tenantId: string): Promise<ShopView> {
  return call(`/shops/${encodeURIComponent(tenantId)}/store`);
}

// ── Suggestions (ADR-0050) ───────────────────────────────────────────────────
// Served by SELL's own routes, under its prefix, so the API that mounts them
// never learns an agent's name. Same cookie, same membership check.

const SELL = "/v1/sell/console";

export type PickedProduct = {
  product_id: string;
  title: string | null;
  /** From the synced catalogue; absent on a product the editor already held. */
  price?: { amount: string; currency: string } | null;
};

export function chooseSuggestions(
  tenantId: string,
  productId: string,
  productIds: string[],
): Promise<unknown> {
  return call(
    `/shops/${encodeURIComponent(tenantId)}/suggestions/${encodeURIComponent(productId)}`,
    { method: "PUT", body: JSON.stringify({ product_ids: productIds }) },
    SELL,
  );
}

export function resetSuggestions(tenantId: string, productId: string): Promise<unknown> {
  return call(
    `/shops/${encodeURIComponent(tenantId)}/suggestions/${encodeURIComponent(productId)}`,
    { method: "DELETE" },
    SELL,
  );
}

export function findProducts(tenantId: string, query: string): Promise<PickedProduct[]> {
  return call(
    `/shops/${encodeURIComponent(tenantId)}/suggestions/catalogue?q=${encodeURIComponent(query)}`,
    undefined,
    SELL,
  );
}
