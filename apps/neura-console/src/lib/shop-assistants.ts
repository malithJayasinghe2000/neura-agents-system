/**
 * Which assistants a shop has (server only: it reads `/me` with the session) — so a screen that belongs to one it does not
 * have is not shown (2026-09-30: *Sold out* and *Suggestions* were shown to a
 * shop with NEURA-CARE only, which is a gym app showing the pool to a member
 * without the pool).
 *
 * **Display only.** It hides links; it grants and refuses nothing. SELL's own
 * routes check the entitlement for Suggestions; the API passes the list through
 * `/me` without reading it, so it still names no agent (ADR-0026 §3).
 */
import { fromApi } from "@/lib/server-api";

export type Membership = {
  tenant_id: string;
  name: string | null;
  assistants?: string[];
  /** `owner`, `support` or `developer` (ADR-0058). */
  role?: string;
  /** What the role may open, worked out by the API from its own map. */
  permissions?: string[];
};
export type Me = { memberships?: Membership[] };

/** NEURA-SELL's key in `enabled_agents`. Its screens: Suggestions and Sold out. */
export const SELL = "sell";

/** The shop's assistants, or `null` when they could not be read. */
export function assistantsOf(me: Me | null, tenantId: string): string[] | null {
  return me?.memberships?.find((m) => m.tenant_id === tenantId)?.assistants ?? null;
}

export async function shopAssistants(tenantId: string): Promise<string[] | null> {
  const me = await fromApi<Me>("/me");
  return me.ok ? assistantsOf(me.data, tenantId) : null;
}

/**
 * Whether to show NEURA-SELL's screens. **Unknown shows them**: hiding a
 * screen because a read failed would make a feature silently vanish, and the
 * screen itself still says what it can.
 */
export function hasSell(assistants: string[] | null): boolean {
  return assistants === null || assistants.includes(SELL);
}

/** NEURA-CARE's key in `enabled_agents`. It answers order questions (ADR-0057). */
export const CARE = "care";

/** Whether to show NEURA-CARE's parts. Unknown shows them, as `hasSell`. */
export function hasCare(assistants: string[] | null): boolean {
  return assistants === null || assistants.includes(CARE);
}
