/**
 * Screen 4 — Shop. What we are connected to, and what we last read from it.
 *
 * **Read-only, deliberately.** `docs/console.md §3.4` designs a connect form
 * that submits a store credential; it is not built, because the console's whole
 * write surface today is one grading verdict and a credential form would be the
 * highest-value target in the application, added before anyone has connected a
 * shop through anything but the CLI. The reasoning is in
 * `routes/console_shop.py` and in PROJECT_STATE, so whoever adds it later adds
 * it on purpose. Connecting stays on `POST /v1/stores` / `make tenant-new`.
 *
 * **No credential is displayed, not even masked.** §3.4: a field that can be
 * revealed is a field that gets revealed in a screen-share. The guarantee is in
 * the query, which never selects those columns — not in this file.
 *
 * **Nothing here is live unless asked.** The counts and sync times are what the
 * database recorded; "is it reachable right now?" is a button, because a page
 * that probes the merchant's own server on every glance is a monitoring agent
 * nobody asked for.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { CheckCircle2, PlugZap, XCircle } from "lucide-react";
import { ShopNav } from "@/components/shop/shop-nav";
import { fromApi, hasSession } from "@/lib/server-api";
import { ENTITY_LABELS, type ConnectedStore, type Health, type ShopView } from "@/lib/shop";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default async function ShopPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ check?: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const { check } = await searchParams;

  const view = await fromApi<ShopView>(`/shops/${encodeURIComponent(tenantId)}/store`);

  // Only when the merchant asked. `check` carries the store id, so the request
  // to their own server happens on a click and never on a page view.
  const health = check
    ? await fromApi<Health>(
        `/shops/${encodeURIComponent(tenantId)}/store/${encodeURIComponent(check)}/health`,
      )
    : null;

  return (
    <>
      <ShopNav tenantId={tenantId} current="shops" />

      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Shop</h1>
        <p className="text-muted-foreground">
          What your assistant is connected to, and what it last read from it.
        </p>
      </div>

      {!view.ok ? (
        <Alert variant="destructive">
          <AlertTitle>
            {view.status === 404 ? "No such shop, or no access to it" : "Could not load"}
          </AlertTitle>
          <AlertDescription>
            {view.status === 404
              ? "Your account does not hold a live membership for this shop."
              : view.message}
          </AlertDescription>
        </Alert>
      ) : !view.data.connected ? (
        <NotConnected />
      ) : (
        <div className="space-y-4">
          {view.data.stores.map((store) => (
            <StoreCard
              key={store.id}
              tenantId={tenantId}
              store={store}
              health={health && check === store.id ? health : null}
            />
          ))}
        </div>
      )}
    </>
  );
}

function StoreCard({
  tenantId,
  store,
  health,
}: {
  tenantId: string;
  store: ConnectedStore;
  health: Awaited<ReturnType<typeof fromApi<Health>>> | null;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          <code>{store.base_url}</code>
        </CardTitle>
        <CardDescription>
          {store.platform} · {store.status}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        <section className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            In the catalogue
          </h3>
          {Object.keys(store.catalogue).length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing has been synced yet.</p>
          ) : (
            <dl className="flex flex-wrap gap-x-8 gap-y-2">
              {Object.entries(store.catalogue).map(([kind, count]) => (
                <div key={kind}>
                  <dt className="text-xs tracking-wide text-muted-foreground uppercase">
                    {ENTITY_LABELS[kind] ?? kind}
                  </dt>
                  <dd className="text-xl font-semibold tabular-nums">{count}</dd>
                </div>
              ))}
            </dl>
          )}
          <p className="text-xs text-muted-foreground">
            Orders and customers aren&apos;t listed because they aren&apos;t copied here — your
            assistant looks those up in your shop at the moment it needs them.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Last sync
          </h3>
          {store.syncs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No sync has run for this shop yet, so the catalogue above is empty and your assistant
              has nothing to answer product questions from.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {store.syncs.map((sync) => (
                <li key={sync.entity_type} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="min-w-28">
                    {ENTITY_LABELS[sync.entity_type] ?? sync.entity_type}
                  </span>
                  {/* `null` is not a date. "Never finished" and "finished long
                      ago" are different facts and only one should worry anyone. */}
                  <span className="text-muted-foreground">
                    {sync.completed_at
                      ? `finished ${formatWhen(sync.completed_at)} · ${sync.last_run_count} read`
                      : "has never finished"}
                  </span>
                  {sync.in_progress ? <Badge variant="secondary">part-way through</Badge> : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="space-y-2 border-t pt-4">
          <div className="flex flex-wrap items-center gap-3">
            <Button
              size="sm"
              variant="outline"
              nativeButton={false}
              render={
                <Link
                  href={`/console/${encodeURIComponent(tenantId)}/shops?check=${encodeURIComponent(store.id)}`}
                />
              }
            >
              <PlugZap className="size-3.5" aria-hidden />
              Check it&apos;s reachable
            </Button>
            <p className="text-xs text-muted-foreground">
              Everything above is what we last recorded. This asks your shop right now.
            </p>
          </div>

          {health ? <HealthResult health={health} /> : null}
        </section>
      </CardContent>
    </Card>
  );
}

function HealthResult({ health }: { health: Awaited<ReturnType<typeof fromApi<Health>>> }) {
  if (!health.ok) {
    return (
      <Alert variant="destructive">
        <AlertTitle>The check could not run</AlertTitle>
        <AlertDescription>{health.message}</AlertDescription>
      </Alert>
    );
  }

  if (!health.data.reachable) {
    return (
      <Alert variant="destructive">
        <XCircle aria-hidden />
        <AlertTitle>Your shop did not answer</AlertTitle>
        <AlertDescription>
          {/* The adapter's own words. A friendlier sentence invented here would
              hide the one detail whoever fixes this needs. */}
          {health.data.detail || "No detail was returned."}
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <Alert>
      <CheckCircle2 aria-hidden />
      <AlertTitle>Your shop answered</AlertTitle>
      <AlertDescription>
        <p>It says it can do the following. This is what your shop declares, not what we assume.</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {health.data.capabilities.length === 0 ? (
            <span className="text-sm">It declared no capabilities at all.</span>
          ) : (
            health.data.capabilities.map((capability) => (
              <Badge key={capability} variant="outline">
                {capability}
              </Badge>
            ))
          )}
        </div>
      </AlertDescription>
    </Alert>
  );
}

/**
 * The empty state that matters most on this screen: nothing is connected, so
 * nothing anywhere else in the console will ever have data in it.
 */
function NotConnected() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">No shop connected yet</CardTitle>
        <CardDescription>
          Until a shop is connected, your assistant has no catalogue to answer from and no orders to
          look up — every other screen here stays empty.
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        Connecting is not done from this screen yet: it needs your shop&apos;s address and an access
        token, and those go in through the API rather than through a form in a browser. Whoever set
        this up can do it, and this page fills in as soon as they have.
      </CardContent>
    </Card>
  );
}

function formatWhen(value: string | null): string {
  if (!value) return "";
  const when = new Date(value);
  return Number.isNaN(when.getTime()) ? "" : when.toLocaleString();
}
