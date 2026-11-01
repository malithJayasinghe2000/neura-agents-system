/**
 * This year's dates (ADR-0072 §2 and §3; console.md §3.14, board 77).
 *
 * Every suggested date, ticked until the owner unticks it and saves (R89), the
 * shop's own dates (R82), and where the shop is (G119): a shop in another
 * country gets the shopping days and its own. No AI chooses the dates.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { CouldNotLoad, NotThisShopsPlan, TITLE } from "@/components/calendar/notes";
import { YearDatesForm } from "@/components/calendar/year-dates";
import { NotAllowed } from "@/components/not-allowed";
import type { YearDates } from "@/lib/calendar";
import { PERMISSION, refusal } from "@/lib/roles";
import { fromApi, hasSession } from "@/lib/server-api";
import { hasGrow, shopAssistants } from "@/lib/shop-assistants";

export default async function ThisYearsDates({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const refused = await refusal(tenantId, PERMISSION.calendar);
  if (refused) return <NotAllowed refusal={refused} what={TITLE} />;
  if (!hasGrow(await shopAssistants(tenantId))) return <NotThisShopsPlan />;

  const result = await fromApi<YearDates>(`/shops/${encodeURIComponent(tenantId)}/calendar/dates`);

  return (
    <>
      <Link
        href={`/console/${encodeURIComponent(tenantId)}/calendar`}
        className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {TITLE}
      </Link>
      {!result.ok ? (
        <CouldNotLoad status={result.status} message={result.message} />
      ) : (
        <>
          <div className="space-y-1.5">
            <h1 className="text-2xl font-semibold tracking-tight">
              This year&apos;s dates · {result.data.year}
            </h1>
            <p className="max-w-3xl leading-relaxed text-muted-foreground">
              Untick the dates that don&apos;t fit your shop, and add your own. Your assistant
              writes a plan 21 days before each ticked date.
            </p>
          </div>
          <YearDatesForm tenantId={tenantId} initial={result.data} />
        </>
      )}
    </>
  );
}
