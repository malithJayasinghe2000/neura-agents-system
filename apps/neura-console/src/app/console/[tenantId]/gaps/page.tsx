/**
 * Missing from your pages (NEURA-GROW, ADR-0064; console.md §3.11, boards 57
 * to 62, approved 2026-10-20 and 2026-10-27).
 *
 * The questions at least 2 shoppers asked in the last 30 days that the shop's
 * pages don't say, so the owner adds each answer **once**, in their own shop,
 * instead of answering it many times. Grouped by product (most asked first),
 * then *About your shop*. **Counts only, never who asked**: *See the chats*
 * opens Conversations, which has its own permission.
 *
 * **Paused** (ADR-0065): when FiveNeurals has switched the night check off, a
 * note says so above the list. The rows found before stay, and *I added it*
 * still works.
 */
import { redirect } from "next/navigation";
import { ExternalLink, FileQuestionMark, Pause, Store } from "lucide-react";
import { GapRow } from "@/components/gaps/gap-row";
import { NotAllowed } from "@/components/not-allowed";
import { When } from "@/components/when";
import { groups, things, type GapTopic, type Gaps } from "@/lib/gaps";
import { PERMISSION, refusal } from "@/lib/roles";
import { fromApi, hasSession } from "@/lib/server-api";
import { hasGrow, shopAssistants } from "@/lib/shop-assistants";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const TITLE = "Missing from your pages";

export default async function GapsPage({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  // A role that does not include this screen sees why, not an error (ADR-0058).
  const refused = await refusal(tenantId, PERMISSION.gaps);
  if (refused) return <NotAllowed refusal={refused} what={TITLE} />;
  // Reached by its address only: the menu does not list it for a shop without
  // NEURA-GROW, said the way Sold out says it.
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

  const result = await fromApi<Gaps>(`/shops/${encodeURIComponent(tenantId)}/gaps`);

  return (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">{TITLE}</h1>
        <p className="max-w-3xl leading-relaxed text-muted-foreground">
          What shoppers asked in the last {result.ok ? result.data.days : 30} days that your
          shop&apos;s pages don&apos;t say. Add each one to your shop once, and your assistant can
          answer the next shopper.
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
                asked, {groups(result.data.groups)}. Most asked first.
              </p>
              {result.data.products.map((product) => (
                <Group
                  key={product.product_id}
                  tenantId={tenantId}
                  productId={product.product_id}
                  title={product.title ?? `Product ${product.product_id}`}
                  url={product.url}
                  topics={product.topics}
                />
              ))}
              {result.data.shop.length > 0 ? (
                <Group tenantId={tenantId} productId={null} topics={result.data.shop} />
              ) : null}
              <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
                Counts only, never who asked. A question shows when at least{" "}
                {result.data.min_shoppers} shoppers asked it. Your assistant checks new chats once a
                night. Only you know the answers, so NEURA never writes them for you.
              </p>
            </>
          )}
        </>
      )}
    </>
  );
}

/** One product's questions, or *About your shop* when `productId` is `null`. */
function Group({
  tenantId,
  productId,
  title,
  url,
  topics,
}: {
  tenantId: string;
  productId: string | null;
  title?: string;
  url?: string | null;
  topics: GapTopic[];
}) {
  const heading = productId ? title : "About your shop";
  return (
    <section
      aria-label={heading}
      data-gap-group={productId ?? "shop"}
      className="overflow-hidden rounded-xl border"
    >
      <div className="flex flex-col gap-1.5 border-b bg-muted/40 px-4 py-3 sm:flex-row sm:items-center sm:gap-3 sm:px-5">
        <h2 className="flex min-w-0 flex-1 items-center gap-2 font-semibold break-words">
          {productId ? null : (
            <Store className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          )}
          {heading}
        </h2>
        {productId && url ? (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            aria-label={`Open the page for ${title} in a new tab`}
            className="inline-flex items-center gap-1.5 self-start text-sm font-medium whitespace-nowrap underline underline-offset-3 sm:self-auto"
          >
            Open the page
            <ExternalLink className="size-3.5" aria-hidden />
          </a>
        ) : null}
      </div>
      <ul className="divide-y">
        {topics.map((topic) => (
          <GapRow key={topic.fact} tenantId={tenantId} productId={productId} topic={topic} />
        ))}
      </ul>
    </section>
  );
}

/** ADR-0065, board 62: FiveNeurals has switched the night check off. */
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
          FiveNeurals has paused the check that finds these questions, so nothing new appears here.
          What you see was found before it was paused. To turn it back on, ask FiveNeurals.
        </p>
      </div>
    </div>
  );
}

/** Board 59. */
function Empty() {
  return (
    <section className="space-y-2 rounded-2xl border border-dashed p-5 sm:p-7">
      <span className="flex size-11 items-center justify-center rounded-lg bg-muted">
        <FileQuestionMark className="size-5 text-muted-foreground" aria-hidden />
      </span>
      <h2 className="pt-1 text-lg font-semibold">Nothing missing right now</h2>
      <p className="leading-relaxed">
        When 2 or more shoppers ask something your pages don&apos;t say, it shows here. Your
        assistant checks new chats once a night.
      </p>
    </section>
  );
}
