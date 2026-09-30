/**
 * Every value on the public website that is **not decided yet** (ADR-0051 §4).
 *
 * Each is `null` until the owner decides it, and the page then shows a bracketed
 * placeholder instead of an invented value. `make web-check` lists every
 * placeholder still in the built pages, so none reaches a real deployment by
 * being forgotten.
 */

/**
 * Where "Talk to us" goes. **Temporary** — the owner's own address, for now
 * (owner, 2026-09-30); the real contact address is decided later.
 */
export const CONTACT_EMAIL: string | null = "malith2jayasinghe@gmail.com";

/** The dashboard's public address, behind "Sign in". Not decided. */
export const DASHBOARD_URL: string | null = null;

/** The API's public address, in the chat box line and the product-views example. Not decided. */
export const NEURA_ADDRESS: string | null = null;

export const CONTACT_LABEL = CONTACT_EMAIL ?? "[CONTACT ADDRESS]";
export const NEURA_HOST = NEURA_ADDRESS ?? "[NEURA ADDRESS]";

/** Until an address exists, both buttons lead to the contact line in the footer. */
export const CONTACT_HREF = CONTACT_EMAIL ? `mailto:${CONTACT_EMAIL}` : "#contact";
export const SIGN_IN_HREF = DASHBOARD_URL ?? "#contact";

/** Served beside the pages, copied from docs/spec at build time (scripts/copy-spec.mjs). */
export const OPENAPI_HREF = "/spec/openapi.json";
