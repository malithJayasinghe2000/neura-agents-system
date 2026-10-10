/**
 * One shop's frame — the side menu and the space every screen sits in.
 *
 * The tenant id in the URL is **not** authorisation and nothing here treats it
 * as such. Every page below calls `acting_for` on the API, which resolves the
 * signed-in person's membership fresh on that request (ADR-0026 §3). A layout
 * renders once and does not re-run when a nested page navigates, so putting the
 * check here would be a check that stops running.
 *
 * **The reads here are for display only**: the shop's name and the person's
 * role there, from their own memberships on `/me` (a shop they do not hold has
 * no name to show, so the id stands in and the page underneath says *no
 * access*), what the role may open, for the menu (ADR-0058), and how many
 * replies wait in Review, for the menu's badge. Grading calls
 * `router.refresh()`, which re-reads both, so the badge does not go stale on the
 * screen where it changes. Nothing is granted or refused by what this finds.
 */
import { fromApi } from "@/lib/server-api";
import type { Scorecard } from "@/lib/review";
import { PERMISSION, may, roleName } from "@/lib/roles";
import { ShopSidebar } from "@/components/shop/shop-sidebar";
import { assistantsOf, hasSell, type Me } from "@/lib/shop-assistants";

export default async function ShopLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  const me = await fromApi<Me>("/me");
  const membership = me.ok
    ? me.data.memberships?.find((held) => held.tenant_id === tenantId)
    : undefined;
  const name = membership?.name;
  // The menu shows each role only what it may open (ADR-0058). The Review count
  // is read only for a role that may open Review: for any other it is a 403.
  const reviews = may(membership, PERMISSION.review);
  const card = reviews
    ? await fromApi<Scorecard>(`/shops/${encodeURIComponent(tenantId)}/review/scorecard`)
    : null;
  const opens = Object.fromEntries(
    Object.entries(PERMISSION).map(([screen, permission]) => [screen, may(membership, permission)]),
  ) as Record<keyof typeof PERMISSION, boolean>;

  return (
    <div className="md:flex md:min-h-dvh">
      <ShopSidebar
        tenantId={tenantId}
        shopName={name ?? tenantId}
        sell={hasSell(me.ok ? assistantsOf(me.data, tenantId) : null)}
        waiting={card?.ok ? card.data.ungraded : null}
        role={roleName(membership?.role)}
        opens={opens}
      />
      <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 md:px-10 md:py-10">
        <div className="mx-auto max-w-5xl space-y-6">{children}</div>
      </main>
    </div>
  );
}
