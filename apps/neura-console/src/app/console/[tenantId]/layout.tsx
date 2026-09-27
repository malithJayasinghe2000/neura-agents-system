/**
 * One shop's frame — the side menu and the space every screen sits in.
 *
 * The tenant id in the URL is **not** authorisation and nothing here treats it
 * as such. Every page below calls `acting_for` on the API, which resolves the
 * signed-in person's membership fresh on that request (ADR-0026 §3). A layout
 * renders once and does not re-run when a nested page navigates, so putting the
 * check here would be a check that stops running.
 *
 * **The two reads here are for display only**: the shop's name, from the
 * person's own memberships on `/me` (a shop they do not hold has no name to
 * show, so the id stands in and the page underneath says *no access*), and how
 * many replies wait in Review, for the menu's badge. Grading calls
 * `router.refresh()`, which re-reads both, so the badge does not go stale on the
 * screen where it changes. Nothing is granted or refused by what this finds.
 */
import { fromApi } from "@/lib/server-api";
import type { Scorecard } from "@/lib/review";
import { ShopSidebar } from "@/components/shop/shop-sidebar";

type Me = { memberships?: { tenant_id: string; name: string | null }[] };

export default async function ShopLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  const [me, card] = await Promise.all([
    fromApi<Me>("/me"),
    fromApi<Scorecard>(`/shops/${encodeURIComponent(tenantId)}/review/scorecard`),
  ]);
  const name = me.ok
    ? me.data.memberships?.find((membership) => membership.tenant_id === tenantId)?.name
    : null;

  return (
    <div className="md:flex md:min-h-dvh">
      <ShopSidebar
        tenantId={tenantId}
        shopName={name ?? tenantId}
        waiting={card.ok ? card.data.ungraded : null}
      />
      <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 md:px-10 md:py-10">
        <div className="mx-auto max-w-5xl space-y-6">{children}</div>
      </main>
    </div>
  );
}
