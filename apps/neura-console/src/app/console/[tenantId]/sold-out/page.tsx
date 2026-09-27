/**
 * Screen 6 — Sold out. ADR-0046 stage 1.
 *
 * Products shoppers opened while they could not be bought, in the last seven
 * days, most-viewed first. It answers one question — *what should I restock?* —
 * and it is careful about three things it cannot know:
 *
 * 1. **A product here may be back in stock.** The count is of views that
 *    happened while it was sold out (ADR-0049), which is the point: a product
 *    restocked on Friday still shows Monday's demand. The screen says so.
 * 2. **A session is not a person.** Views and sessions are both shown, and
 *    neither is called "customers" or "people".
 * 3. **An empty screen has two different causes**, and they read differently:
 *    no agreement on record, or nothing viewed while sold out. The shop's own
 *    switch is the third, and it is named as something we cannot see.
 *
 * Nothing on this screen reaches a shopper, and nothing here is contactable —
 * that is stages 2 and 3, and neither is approved.
 */
import { redirect } from "next/navigation";
import { Info, PackageX } from "lucide-react";
import { ShopNav } from "@/components/shop/shop-nav";
import { fromApi, hasSession } from "@/lib/server-api";
import type { SoldOut, SoldOutProduct } from "@/lib/sold-out";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default async function SoldOutPage({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const result = await fromApi<SoldOut>(`/shops/${encodeURIComponent(tenantId)}/sold-out`);

  return (
    <>
      <ShopNav tenantId={tenantId} current="sold-out" />

      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Wanted while sold out</h1>
        <p className="text-muted-foreground">
          Products shoppers opened while they could not be bought.
        </p>
      </div>

      {!result.ok ? (
        <Alert variant="destructive">
          <AlertTitle>
            {result.status === 404 ? "No such shop, or no access to it" : "Could not load"}
          </AlertTitle>
          <AlertDescription>
            {result.status === 404
              ? "Your account does not hold a live membership for this shop."
              : result.message}
          </AlertDescription>
        </Alert>
      ) : (
        <SoldOutBody soldOut={result.data} />
      )}
    </>
  );
}

function SoldOutBody({ soldOut }: { soldOut: SoldOut }) {
  const period = `Last ${soldOut.period.days} days, ${day(soldOut.period.since)} to ${day(soldOut.period.through)}`;

  return (
    <>
      {soldOut.products.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {soldOut.agreement
                ? "No sold-out product was viewed"
                : "Nothing is collected for this shop"}
            </CardTitle>
            <CardDescription>
              {soldOut.agreement
                ? `${period}. This screen also stays empty while product views are switched off in your shop's own settings — that switch is yours, and it cannot be seen from here.`
                : "No data-processing agreement is on record for this shop, so nothing about your shoppers' visits is stored. Until one is recorded, this screen stays empty."}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{period}</CardTitle>
            <CardDescription>Most-viewed first. Counts only — never who.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="divide-y">
              {soldOut.products.map((product) => (
                <Row key={product.product_id} product={product} />
              ))}
            </ul>
            {soldOut.truncated ? (
              <p className="pt-3 text-sm text-muted-foreground">
                More products were viewed while sold out than this list shows.
              </p>
            ) : null}
          </CardContent>
        </Card>
      )}

      {soldOut.caveats.length > 0 ? (
        <Card className="border-dashed bg-muted/30">
          <CardHeader>
            <CardTitle className="text-base">What these numbers do not say</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {soldOut.caveats.map((caveat) => (
                <li key={caveat} className="flex items-start gap-2 text-sm text-muted-foreground">
                  <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  {caveat}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}

function Row({ product }: { product: SoldOutProduct }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 py-3">
      <div className="flex min-w-0 items-start gap-2">
        <PackageX className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0">
          {product.title ? (
            product.url ? (
              <a
                className="font-medium underline-offset-3 hover:underline"
                href={product.url}
                target="_blank"
                rel="noreferrer"
              >
                {product.title}
              </a>
            ) : (
              <span className="font-medium">{product.title}</span>
            )
          ) : (
            // Shown by its id rather than dropped: the demand is real even when
            // the synced catalogue has not caught up with the product.
            <span className="font-medium">Product {product.product_id}</span>
          )}
          <p className="text-xs text-muted-foreground">
            {product.title ? `#${product.product_id} · ` : "Not in the synced catalogue yet · "}
            last viewed {day(product.last_viewed_at)}
          </p>
        </div>
      </div>
      <dl className="flex gap-6 text-right">
        <div>
          <dt className="text-xs tracking-wide text-muted-foreground uppercase">views</dt>
          <dd className="text-xl font-semibold tabular-nums">{product.views}</dd>
        </div>
        <div>
          <dt className="text-xs tracking-wide text-muted-foreground uppercase">sessions</dt>
          <dd className="text-xl font-semibold tabular-nums">{product.sessions}</dd>
        </div>
      </dl>
    </li>
  );
}

/** `2026-09-27T06:26:27+00:00` → `2026-09-27`. The date is what a merchant plans with. */
function day(iso: string): string {
  return iso.slice(0, 10);
}
