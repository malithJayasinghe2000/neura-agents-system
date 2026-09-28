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

import type { ReviewTurn, Verdict } from "@/lib/review";
import type { Health, ShopView, SyncAsked } from "@/lib/shop";

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
 * *Check now* — asks the shop, right now, whether it answers and what it
 * allows. Made only when the owner presses the button, never on a page load:
 * it is a request to the merchant's own server. A shop that did not answer is
 * a 200 describing the failure, so this resolves either way.
 */
export function checkShop(tenantId: string, storeId: string): Promise<Health> {
  return call(`/shops/${encodeURIComponent(tenantId)}/store/${encodeURIComponent(storeId)}/health`);
}

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
