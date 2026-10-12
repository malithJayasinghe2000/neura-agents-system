/**
 * What a person's role in one shop lets them open (ADR-0058).
 *
 * **Display only.** It hides menu items and Home's parts, and shows *You can't
 * open this page*; the API's 403 is the lock. The permissions come from `/me`,
 * which the API works out from its own map, so this file keeps no copy of who
 * may do what: it only names the doors.
 */
import { fromApi } from "@/lib/server-api";
import type { Me, Membership } from "@/lib/shop-assistants";

/** The doors, by the names the API gives them (console.md §3.8). */
export const PERMISSION = {
  home: "shop:home:read",
  conversations: "shop:conversations:read",
  review: "shop:review:write",
  suggestions: "sell:suggestions:write",
  soldOut: "shop:sold_out:read",
  connection: "shop:connection:write",
  connect: "shop:connect:write",
  contact: "shop:contact:write",
  mode: "shop:mode:write",
  usage: "usage:cost:read",
  people: "people:members:write",
  /** Answer a handed-over shopper: their email, Mark as answered (ADR-0062 §8). */
  handovers: "shop:handovers:write",
} as const;

export type Permission = (typeof PERMISSION)[keyof typeof PERMISSION];

export { roleName } from "@/lib/role-names";
import { roleName } from "@/lib/role-names";

/**
 * May this membership open `permission`? **Unknown opens it** (the list could
 * not be read): hiding a screen because a read failed would make it silently
 * vanish, and the API still refuses what the role does not include.
 */
export function may(membership: Membership | null | undefined, permission: Permission): boolean {
  const held = membership?.permissions;
  return held === undefined ? true : held.includes(permission);
}

/** The person's membership of this shop, from `/me`, or `null`. */
export async function membershipOf(tenantId: string): Promise<Membership | null> {
  const me = await fromApi<Me>("/me");
  return me.ok ? (me.data.memberships?.find((m) => m.tenant_id === tenantId) ?? null) : null;
}

/** What *You can't open this page* says, or `null` when the page may open. */
export type Refusal = { shop: string; role: string; next: { href: string; label: string } };

/**
 * Asked at the top of a screen. `null` lets the screen render: it may open,
 * or the membership is unknown, and then the screen's own read says why.
 */
export async function refusal(tenantId: string, permission: Permission): Promise<Refusal | null> {
  const membership = await membershipOf(tenantId);
  if (!membership || may(membership, permission)) return null;
  return {
    shop: membership.name ?? tenantId,
    role: roleName(membership.role),
    next: firstOpen(tenantId, membership),
  };
}

/** The first screen in the menu, after Home, that the role may open; else Home. */
export function firstOpen(
  tenantId: string,
  membership: Membership,
): { href: string; label: string } {
  const base = `/console/${encodeURIComponent(tenantId)}`;
  const screens: [Permission, string, string][] = [
    [PERMISSION.review, `${base}/review`, "Review"],
    [PERMISSION.conversations, `${base}/conversations`, "Conversations"],
    [PERMISSION.connection, `${base}/shops`, "Shop connection"],
  ];
  const found = screens.find(([permission]) => may(membership, permission));
  return found ? { href: found[1], label: found[2] } : { href: base, label: "Home" };
}
