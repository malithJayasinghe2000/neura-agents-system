/**
 * Where a signed-in merchant lands: their shops. ADR-0026.
 *
 * One card per shop, the whole card one click, with the shop's own name and one
 * line of status — the owner's approved mockup, 2026-09-27. The status is read
 * from the same membership-checked endpoints the shop's own screens use, and it
 * holds **no figure that was not counted**: the mode the shop is in, how many
 * replies wait in Review right now, or that no online shop is connected. Nothing
 * measured is claimed here, because `docs/console.md §5` is explicit that a
 * dashboard is where this project's honesty about unmeasured numbers usually
 * dies.
 *
 * This page draws its own header; a shop's screens carry the wordmark and
 * *Sign out* in their side menu instead.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ChevronRight, Store } from "lucide-react";
import { Brand } from "@/components/brand";
import { SignOutButton } from "@/components/sign-out-button";
import { fromApi, hasSession } from "@/lib/server-api";
import type { Scorecard } from "@/lib/review";
import type { ShopView } from "@/lib/shop";
import type { Usage } from "@/lib/usage";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** `name` is `null` when the shop has none on record; the id stands in for it. */
type Membership = { tenant_id: string; role: string; name: string | null };
type Me = { signed_in: boolean; memberships?: Membership[] };

export default async function ConsolePage() {
  if (!(await hasSession())) redirect("/");

  // Asked fresh on every load rather than trusted from the cookie. That is the
  // whole reason the cookie carries no tenant: revoking access has to bite on
  // the next request, and a cookie cannot be recalled (ADR-0026 §3).
  const me = await fromApi<Me>("/me");
  if (!me.ok || !me.data.signed_in) redirect("/");

  const memberships: Membership[] = me.data.memberships ?? [];
  const statuses = await Promise.all(memberships.map((m) => statusOf(m.tenant_id)));

  return (
    <>
      <header className="border-b">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4 sm:px-6">
          <Brand />
          <SignOutButton />
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-7 px-4 py-10 sm:px-6 sm:py-14">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">Your shops</h1>
          <p className="text-muted-foreground">
            Choose a shop to see what its assistant has been doing.
          </p>
        </div>

        {memberships.length === 0 ? (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">No shop yet</CardTitle>
              <CardDescription>
                Your account is active, but it isn&apos;t connected to a shop — so there&apos;s
                nothing to show. Ask whoever set this up to grant you access, and this page will
                fill in.
              </CardDescription>
            </CardHeader>
          </Card>
        ) : (
          <ul className="space-y-3">
            {memberships.map((membership, index) => (
              <li key={membership.tenant_id}>
                <Link
                  href={`/console/${encodeURIComponent(membership.tenant_id)}`}
                  className="flex items-center gap-4 rounded-xl border bg-card px-4 py-4 transition-colors outline-none hover:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50 sm:px-5"
                >
                  <span className="grid size-11 shrink-0 place-items-center rounded-lg bg-muted">
                    <Store className="size-5" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1 space-y-1">
                    <span className="block truncate font-semibold">
                      {membership.name ?? <code>{membership.tenant_id}</code>}
                    </span>
                    <StatusLine status={statuses[index]} />
                  </span>
                  <ChevronRight className="size-5 shrink-0 text-muted-foreground" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}

type Status = {
  /** `null` when it could not be read — then nothing is said about it. */
  connected: boolean | null;
  practice: boolean | null;
  waiting: number | null;
};

/** Three reads per shop, in parallel, each one already membership-checked. */
async function statusOf(tenantId: string): Promise<Status> {
  const shop = encodeURIComponent(tenantId);
  const [store, usage, card] = await Promise.all([
    fromApi<ShopView>(`/shops/${shop}/store`),
    fromApi<Usage>(`/shops/${shop}/usage?period=today`),
    fromApi<Scorecard>(`/shops/${shop}/review/scorecard`),
  ]);
  return {
    connected: store.ok ? store.data.connected : null,
    practice: usage.ok ? usage.data.withheld : null,
    waiting: card.ok ? card.data.ungraded : null,
  };
}

function StatusLine({ status }: { status: Status }) {
  if (status.connected === false) {
    return (
      <span className="block text-sm text-muted-foreground">
        Not connected to your online shop yet
      </span>
    );
  }
  if (status.practice === null) return null;

  return (
    <span className="block text-sm text-muted-foreground">
      {status.practice ? "Practice mode" : "Live"}
      {status.waiting ? (
        <>
          {" · "}
          <span className="font-medium text-foreground">
            {status.waiting === 1
              ? "1 reply waiting for your review"
              : `${status.waiting} replies waiting for your review`}
          </span>
        </>
      ) : null}
    </span>
  );
}
