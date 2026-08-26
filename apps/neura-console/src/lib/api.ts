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

/** The API's envelope: `{ data, meta }`, on success and on error alike. */
type Envelope<T> = { data: T; error?: { message?: string } };

export type Membership = { tenant_id: string; role: string };

export type Me = {
  signed_in: boolean;
  user_id?: string;
  memberships: Membership[];
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}/v1/console${path}`, {
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
export function verifySignInToken(token: string): Promise<{ signed_in: boolean; message?: string }> {
  return call("/auth/verify", { method: "POST", body: JSON.stringify({ token }) });
}

/** Who is signed in, and which merchants they may act for — asked fresh. */
export function fetchMe(): Promise<Me> {
  return call("/me");
}

export function signOut(): Promise<{ signed_out: boolean }> {
  return call("/auth/sign-out", { method: "POST" });
}
