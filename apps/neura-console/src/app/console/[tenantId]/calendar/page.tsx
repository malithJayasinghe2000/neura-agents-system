/**
 * Marketing calendar (NEURA-GROW, ADR-0072; console.md §3.14, board 75, approved
 * 2026-11-01).
 *
 * The shop's kept dates in the next 12 months, soonest first, each with what its
 * plan is: ready, made 21 days before, or a moving date whose day is not set.
 * GROW writes a plan 21 days before each kept date; the owner reads it, edits
 * it, copies it and posts it themselves. **The Owner and Support** (R86).
 *
 * A suggested date counts once this year's list is saved (R91), so until then
 * the page says so and only the shop's own dates are listed.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { CalendarDays, CalendarPlus } from "lucide-react";
import { CouldNotLoad, NotThisShopsPlan, PausedNote, TITLE } from "@/components/calendar/notes";
import { MakeAgain } from "@/components/calendar/make-again";
import { NotAllowed } from "@/components/not-allowed";
import {
  comingLine,
  dateBox,
  datesHref,
  planHref,
  shortDay,
  type Calendar,
  type ComingDate,
} from "@/lib/calendar";
import { PERMISSION, refusal } from "@/lib/roles";
import { fromApi, hasSession } from "@/lib/server-api";
import { hasGrow, shopAssistants } from "@/lib/shop-assistants";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default async function CalendarPage({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  // A role that does not include this screen sees why, not an error (ADR-0058).
  const refused = await refusal(tenantId, PERMISSION.calendar);
  if (refused) return <NotAllowed refusal={refused} what={TITLE} />;
  if (!hasGrow(await shopAssistants(tenantId))) return <NotThisShopsPlan />;

  const result = await fromApi<Calendar>(`/shops/${encodeURIComponent(tenantId)}/calendar`);

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">{TITLE}</h1>
          <p className="max-w-3xl leading-relaxed text-muted-foreground">
            Your special dates for the year. 21 days before each one, your assistant writes a
            campaign plan from your shop&apos;s own data. You edit it, copy it and post it yourself.
          </p>
        </div>
        <Button
          variant="outline"
          className="h-11 self-start px-4 sm:h-10 sm:shrink-0"
          nativeButton={false}
          data-this-years-dates
          render={<Link href={datesHref(tenantId)} />}
        >
          <CalendarDays aria-hidden />
          This year&apos;s dates
        </Button>
      </div>

      {!result.ok ? (
        <CouldNotLoad status={result.status} message={result.message} />
      ) : (
        <>
          {result.data.paused_since ? <PausedNote since={result.data.paused_since} /> : null}
          {result.data.saved ? null : <ChooseDates tenantId={tenantId} year={result.data.year} />}
          <section className="space-y-3" aria-labelledby="coming-up">
            <h2 id="coming-up" className="text-[17px] font-semibold">
              Coming up
            </h2>
            {result.data.coming_up.length === 0 ? (
              <p className="rounded-xl border px-4 py-4 text-sm text-muted-foreground sm:px-5">
                {result.data.saved
                  ? "No kept date in the next 12 months. Add your own on This year's dates."
                  : "Nothing yet. Choose this year's dates, or add your own."}
              </p>
            ) : (
              <ul aria-label="Coming up" className="divide-y overflow-hidden rounded-xl border">
                {result.data.coming_up.map((date) => (
                  <ComingRow
                    key={`${date.date_key}:${date.day ?? "?"}`}
                    tenantId={tenantId}
                    date={date}
                    year={result.data.year}
                    paused={result.data.paused_since !== null}
                  />
                ))}
              </ul>
            )}
          </section>
          <p className="max-w-3xl text-[13px] leading-relaxed text-muted-foreground">
            Plans are written by AI from your products and what your shoppers asked. Read every word
            before you post it. We never post or send anything for you.
          </p>
        </>
      )}
    </>
  );
}

/** This year's list is not saved: only the shop's own dates count yet (R91). */
function ChooseDates({ tenantId, year }: { tenantId: string; year: number }) {
  return (
    <section
      data-choose-dates
      className="flex flex-col gap-3 rounded-xl border border-dashed px-4 py-4 sm:flex-row sm:items-center sm:gap-5 sm:px-5"
    >
      <CalendarPlus className="hidden size-6 shrink-0 sm:block" aria-hidden />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="font-medium">Add this year&apos;s special dates</p>
        <p className="text-sm text-muted-foreground">
          Untick the ones that don&apos;t fit your shop and add your own. Until you save the
          {` ${year} `}list, only your own dates get a plan.
        </p>
      </div>
      <Button
        variant="outline"
        className="h-10 self-start px-4 sm:shrink-0 sm:self-center"
        nativeButton={false}
        render={<Link href={datesHref(tenantId)} />}
      >
        Add dates
      </Button>
    </section>
  );
}

function ComingRow({
  tenantId,
  date,
  year,
  paused,
}: {
  tenantId: string;
  date: ComingDate;
  year: number;
  paused: boolean;
}) {
  const box = dateBox(date.day, date.usually);
  const line = comingLine(date);
  return (
    <li
      data-coming={date.date_key}
      data-status={date.status}
      className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
    >
      <div className="flex min-w-0 flex-1 items-center gap-4">
        <span
          aria-hidden
          className="flex size-14 shrink-0 flex-col items-center justify-center rounded-[10px] border"
        >
          <span className="text-[11px] font-semibold text-muted-foreground uppercase">
            {box.month}
          </span>
          <span className="text-xl leading-tight font-semibold">{box.day}</span>
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="font-semibold break-words">
            {date.name}
            {date.day ? <span className="sr-only">, {shortDay(date.day, year)}</span> : null}
          </p>
          {line ? <p className="text-[13px] text-muted-foreground">{line}</p> : null}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 sm:shrink-0 sm:justify-end">
        <Pill date={date} year={year} />
        <span className="flex sm:w-[140px] sm:justify-end">
          <Action tenantId={tenantId} date={date} paused={paused} />
        </span>
      </div>
    </li>
  );
}

const PILL = "inline-flex h-[26px] items-center rounded-full border px-2.5 text-[13px] font-medium";

function Pill({ date, year }: { date: ComingDate; year: number }) {
  switch (date.status) {
    case "ready":
      return (
        <span className={cn(PILL, "border-foreground bg-foreground text-background")}>
          Plan ready
        </span>
      );
    case "making":
      return <span className={cn(PILL, "text-foreground/80")}>Making a new plan</span>;
    case "failed":
      return (
        <span
          className={cn(
            PILL,
            "border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300",
          )}
        >
          Plan could not be made
        </span>
      );
    case "not_set":
      return (
        <span className={cn(PILL, "border-dashed bg-muted text-muted-foreground")}>
          Date not set yet
        </span>
      );
    case "tonight":
      return <span className={cn(PILL, "text-foreground/80")}>Plan tonight</span>;
    case "paused":
      return <span className={cn(PILL, "text-foreground/80")}>No plan while paused</span>;
    default:
      return (
        <span className={cn(PILL, "text-foreground/80")}>
          Plan on {date.plan_day ? shortDay(date.plan_day, year) : ""}
        </span>
      );
  }
}

function Action({
  tenantId,
  date,
  paused,
}: {
  tenantId: string;
  date: ComingDate;
  paused: boolean;
}) {
  if ((date.status === "ready" || date.status === "making") && date.plan_id) {
    return (
      <Button
        variant="outline"
        className="h-11 px-4 sm:h-10"
        nativeButton={false}
        data-see-plan
        render={<Link href={planHref(tenantId, date.plan_id)} />}
      >
        See the plan
      </Button>
    );
  }
  if (date.status === "failed" && date.plan_id && !paused) {
    return <MakeAgain tenantId={tenantId} planId={date.plan_id} />;
  }
  if (date.status === "not_set") {
    return (
      <Button
        variant="outline"
        className="h-11 px-4 sm:h-10"
        nativeButton={false}
        data-set-date
        render={<Link href={datesHref(tenantId)} />}
      >
        Set the date
      </Button>
    );
  }
  return null;
}
