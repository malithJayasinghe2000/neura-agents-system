/**
 * Shoppers asked for (NEURA-GROW, ADR-0068; console.md §3.12, boards 67 to 70,
 * approved 2026-10-28).
 *
 * The things at least 2 shoppers asked for in the last 30 days that the shop
 * doesn't sell, so the owner can decide to start selling them. Most asked
 * first. **Counts only, never who asked**: *See the chats* opens Conversations.
 * **The Owner only** (R61): what to sell is the owner's decision.
 *
 * **Paused** (ADR-0065, ADR-0068 §8): the night check's switch pauses this page
 * too, said as Missing from your pages says it.
 */
import { redirect } from "next/navigation";
import { Pause } from "lucide-react";
import { NotAllowed } from "@/components/not-allowed";
import { ShoppingBagPlus } from "@/components/shopping-bag-plus";
import { When } from "@/components/when";
import { WantedRow } from "@/components/wanted/wanted-row";
import { things } from "@/lib/gaps";
import { PERMISSION, refusal } from "@/lib/roles";
import { fromApi, hasSession } from "@/lib/server-api";
import { hasGrow, shopAssistants } from "@/lib/shop-assistants";
import type { Wanted } from "@/lib/wanted";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const TITLE = "Shoppers asked for";

export default async function WantedPage({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  // A role that does not include this screen sees why, not an error (ADR-0058).
  const refused = await refusal(tenantId, PERMISSION.wanted);
  if (refused) return <NotAllowed refusal={refused} what={TITLE} />;
  // Reached by its address only: the menu does not list it for a shop without
  // NEURA-GROW, said the way Missing from your pages says it.
  if (!hasGrow(await shopAssistants(tenantId))) {
    return (
      <>
        <h1 className="text-2xl font-semibold tracking-tight">{TITLE}</h1>
        <Alert>
          <AlertTitle>{TITLE} is not part of this shop&apos;s plan</AlertTitle>
          <AlertDescription>
            It comes with NEURA-GROW, which this shop doesn&apos;t have.
          </AlertDescription>
        </Alert>
      </>
    );
  }

  const result = await fromApi<Wanted>(`/shops/${encodeURIComponent(tenantId)}/wanted`);

  return (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">{TITLE}</h1>
        <p className="max-w-3xl leading-relaxed text-muted-foreground">
          Things shoppers asked for in the last {result.ok ? result.data.days : 30} days that your
          shop doesn&apos;t sell. If many people want something, you may want to start selling it.
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
        <>
          {result.data.paused_since ? <Paused since={result.data.paused_since} /> : null}
          {result.data.total === 0 ? (
            <Empty />
          ) : (
            <>
              <p className="text-sm">
                <strong className="font-semibold">{things(result.data.total)}</strong> shoppers
                asked for. Most asked first.
              </p>
              <ul aria-label={TITLE} className="divide-y overflow-hidden rounded-xl border">
                {result.data.items.map((item) => (
                  <WantedRow key={item.label} tenantId={tenantId} item={item} />
                ))}
              </ul>
              <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
                Counts only, never who asked. Something shows when at least{" "}
                {result.data.min_shoppers} shoppers asked for it. Your assistant checks new chats
                once a night.
              </p>
            </>
          )}
        </>
      )}
    </>
  );
}

/** ADR-0068 §8: FiveNeurals has switched the night check off. */
function Paused({ since }: { since: string }) {
  return (
    <div
      role="status"
      data-paused
      className="flex max-w-3xl items-start gap-3 rounded-xl border bg-muted/40 px-4 py-4 sm:px-5"
    >
      <Pause className="mt-0.5 size-[18px] shrink-0 text-foreground/80" aria-hidden />
      <div className="space-y-1">
        <p className="text-sm font-semibold">
          Paused since <When iso={since} date />
        </p>
        <p className="text-sm leading-relaxed text-foreground/80">
          FiveNeurals has paused the check that finds these things, so nothing new appears here.
          What you see was found before it was paused. To turn it back on, ask FiveNeurals.
        </p>
      </div>
    </div>
  );
}

/** Board 69. */
function Empty() {
  return (
    <section className="space-y-2 rounded-2xl border border-dashed p-5 sm:p-7">
      <span className="flex size-11 items-center justify-center rounded-lg bg-muted">
        <ShoppingBagPlus className="size-5 text-muted-foreground" aria-hidden />
      </span>
      <h2 className="pt-1 text-lg font-semibold">Nothing asked for right now</h2>
      <p className="leading-relaxed">
        When 2 or more shoppers ask for something your shop doesn&apos;t sell, it shows here. Your
        assistant checks new chats once a night.
      </p>
    </section>
  );
}
