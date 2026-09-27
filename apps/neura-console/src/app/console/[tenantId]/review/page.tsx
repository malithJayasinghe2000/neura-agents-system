/**
 * Screen 3 — Review. Grading what the assistant would have said. ADR-0026.
 *
 * **This is the screen the console was built for**: it is the only one that
 * produces something this project does not have — *real graded turns* — which
 * is the sole route out of open question **E1**, where every golden case is
 * synthetic.
 *
 * **Redesigned 2026-09-27 from the owner's approved mockup.** Two tabs, because
 * grading and looking back are different jobs:
 *
 * - **To review** — an inbox. The waiting replies on the left, grouped by day
 *   and by chat; one reply open on the right, with what it looked at and three
 *   big buttons. Grading one opens the next. On a phone: the list, then one
 *   reply at a time.
 * - **Already graded** — a table to scan, filterable by grade.
 *
 * Both can be narrowed by outcome or grade, by the day it was asked, and by
 * assistant. The rules that were decisions before are still decisions:
 *
 * 1. **The evidence is in front of the grader** — in the open reply, beside the
 *    buttons (§3.2, E7). You cannot grade a reply you have not opened.
 * 2. **Declined and escalated turns are in the queue and look it.** The screen
 *    opens on every waiting turn; a narrowed view says so and how to clear it.
 * 3. **No sampling.** Every recorded turn is reachable: the list pages, and
 *    every filter can be cleared (A4).
 * 4. **No number that was not measured.** Counts, never a percentage; cost is
 *    *not priced* rather than `$0` (§5, CLAUDE.md §4).
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { FilterBar, type Chip } from "@/components/review/filter-bar";
import { GradeBar } from "@/components/review/grade-bar";
import { GradedTable } from "@/components/review/graded-table";
import { ReplyDetail } from "@/components/review/reply-detail";
import { WaitingList, flatten, groupWaiting } from "@/components/review/waiting-list";
import type { Transcript, TranscriptMessage } from "@/lib/conversations";
import { askedWindow, askedWords, dayIn } from "@/lib/days";
import {
  OUTCOME_FILTERS,
  VERDICT_FILTERS,
  type ReviewCounts,
  type ReviewTurn,
  type Scorecard,
} from "@/lib/review";
import { fromApi, hasSession, type PageMeta } from "@/lib/server-api";
import { readerTimeZone } from "@/lib/time-zone";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

type Me = { signed_in: boolean; user_id?: string };

type Params = {
  show?: string;
  state?: string;
  verdict?: string;
  agent?: string;
  asked?: string;
  from?: string;
  to?: string;
  turn?: string;
  cursor?: string;
};

/** How many earlier messages of a chat are worth showing above a reply. */
const EARLIER_SHOWN = 6;

export default async function ReviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<Params>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const query = await searchParams;
  const graded = query.show === "graded";
  const shop = encodeURIComponent(tenantId);
  const base = `/console/${shop}/review`;

  // The filters, as the URL holds them. Changing one drops the cursor and the
  // open reply — a new filter starts again at the top.
  const view = {
    show: graded ? "graded" : "",
    state: graded ? "" : (query.state ?? ""),
    verdict: graded ? (query.verdict ?? "") : "",
    agent: query.agent ?? "",
    asked: query.asked ?? "",
    from: query.from ?? "",
    to: query.to ?? "",
  };
  const link = (changes: Partial<typeof view> & { turn?: string; cursor?: string }) => {
    const next = new URLSearchParams(
      Object.entries({ ...view, ...changes }).filter(([, value]) => value) as [string, string][],
    );
    if (next.get("asked") !== "custom") {
      next.delete("from");
      next.delete("to");
    }
    return next.size ? `${base}?${next}` : base;
  };

  const timeZone = await readerTimeZone();
  const today = dayIn(new Date(), timeZone);
  const window = askedWindow(view.asked, view.from, view.to, today);

  const narrowing = new URLSearchParams({ tz: timeZone });
  if (view.agent) narrowing.set("agent", view.agent);
  if (window?.since) narrowing.set("since", window.since);
  if (window?.until) narrowing.set("until", window.until);

  const listQuery = new URLSearchParams(narrowing);
  listQuery.set("graded", String(graded));
  if (view.state) listQuery.set("state", view.state);
  if (view.verdict) listQuery.set("verdict", view.verdict);
  if (query.cursor) listQuery.set("cursor", query.cursor);
  const countQuery = new URLSearchParams(narrowing);
  countQuery.set("graded", String(graded));

  const [card, counts, list, me] = await Promise.all([
    fromApi<Scorecard>(`/shops/${shop}/review/scorecard`),
    fromApi<ReviewCounts>(`/shops/${shop}/review/counts?${countQuery}`),
    fromApi<ReviewTurn[]>(`/shops/${shop}/review?${listQuery}`),
    fromApi<Me>("/me"),
  ]);

  const failure = [card, counts, list].find((result) => !result.ok);

  return (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Review</h1>
        <p className="text-muted-foreground">
          No shopper saw any of these replies. Your grades show whether your assistant is ready to
          go live.
        </p>
      </div>

      {failure && !failure.ok ? (
        <Alert variant="destructive">
          <AlertTitle>
            {failure.status === 404
              ? "No such shop, or no access to it"
              : "Could not load the queue"}
          </AlertTitle>
          <AlertDescription>
            {failure.status === 404
              ? "Your account does not hold a live membership for this shop. If it should, ask whoever set it up."
              : failure.message}
          </AlertDescription>
        </Alert>
      ) : card.ok && counts.ok && list.ok ? (
        <Body
          graded={graded}
          view={view}
          link={link}
          base={base}
          card={card.data}
          counts={counts.data}
          turns={list.data}
          meta={list.meta}
          query={query}
          shop={shop}
          tenantId={tenantId}
          viewerId={me.ok ? me.data.user_id : undefined}
          timeZone={timeZone}
          today={today}
          period={askedWords(window, today)}
        />
      ) : null}
    </>
  );
}

async function Body({
  graded,
  view,
  link,
  base,
  card,
  counts,
  turns,
  meta,
  query,
  shop,
  tenantId,
  viewerId,
  timeZone,
  today,
  period,
}: {
  graded: boolean;
  view: Record<string, string>;
  link: (changes: Record<string, string>) => string;
  base: string;
  card: Scorecard;
  counts: ReviewCounts;
  turns: ReviewTurn[];
  meta: PageMeta;
  query: Params;
  shop: string;
  tenantId: string;
  viewerId: string | undefined;
  timeZone: string;
  today: string;
  period: string;
}) {
  const tabTotal = graded ? card.graded : card.ungraded;
  const filtered = Boolean(view.state || view.verdict || view.agent || view.asked);
  const shown = graded
    ? view.verdict
      ? (counts.by_verdict[view.verdict as keyof ReviewCounts["by_verdict"]] ?? 0)
      : counts.total
    : view.state
      ? (counts.by_state[view.state] ?? 0)
      : counts.total;

  const chips: Chip[] = (graded ? VERDICT_FILTERS : OUTCOME_FILTERS).map((option) => ({
    key: option.key,
    label: option.label,
    count: option.key
      ? graded
        ? (counts.by_verdict[option.key as keyof ReviewCounts["by_verdict"]] ?? 0)
        : (counts.by_state[option.key] ?? 0)
      : counts.total,
    href: link(graded ? { verdict: option.key } : { state: option.key }),
    current: (graded ? view.verdict : view.state) === option.key,
  }));

  // The open reply: the one in the address, or — on the inbox — the first one.
  const groups = graded ? [] : groupWaiting(turns, timeZone, today);
  const order = graded ? turns : flatten(groups);
  const selectedId = query.turn ?? (graded ? undefined : order[0]?.id);
  let selected = order.find((turn) => turn.id === selectedId) ?? null;
  if (!selected && query.turn) {
    const one = await fromApi<ReviewTurn>(
      `/shops/${shop}/review/${encodeURIComponent(query.turn)}`,
    );
    selected = one.ok ? one.data : null;
  }
  const earlier = selected ? await earlierIn(shop, selected) : [];

  const index = selected ? order.findIndex((turn) => turn.id === selected.id) : -1;
  const next = index >= 0 ? (order[index + 1] ?? order[index - 1]) : order[0];
  const nextHref = graded
    ? null
    : next && next.id !== selected?.id
      ? link({ turn: next.id })
      : link({});
  const position =
    !graded && !query.cursor && index >= 0 && !filtered ? `${index + 1} of ${tabTotal}` : undefined;

  return (
    <>
      <nav aria-label="Replies" className="flex gap-1 border-b">
        {[
          { key: "", label: "To review", count: card.ungraded },
          { key: "graded", label: "Already graded", count: card.graded },
        ].map((tab) => {
          const on = view.show === tab.key;
          return (
            <Link
              key={tab.key || "waiting"}
              href={tab.key ? `${base}?show=${tab.key}` : base}
              aria-current={on ? "page" : undefined}
              className={cn(
                "-mb-px flex h-11 items-center gap-2 border-b-2 px-3 text-sm",
                on
                  ? "border-foreground font-semibold text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
              <span
                className={cn(
                  "grid h-5 min-w-5 place-items-center rounded-full px-1.5 text-xs tabular-nums",
                  tab.key ? "bg-muted text-foreground" : "bg-foreground text-background",
                )}
              >
                {tab.count}
              </span>
            </Link>
          );
        })}
      </nav>

      {graded ? (
        <p className="text-sm">
          In all, {card.graded} graded: <strong>{card.verdicts.agree} good</strong>,{" "}
          <strong>{card.verdicts.disagree} not good</strong>,{" "}
          <strong>{card.verdicts.would_have_harmed} harmful</strong>.{" "}
          {card.verdicts.would_have_harmed > 0 ? (
            <span className="font-medium text-red-700 dark:text-red-400">
              A harmful reply is a reason not to go live yet.{" "}
            </span>
          ) : null}
          <span className="text-muted-foreground">
            Every reply your assistant held back is here or waiting — none is skipped.
          </span>
        </p>
      ) : null}

      {/* On a phone, an open reply gets the whole screen; "All waiting
          replies" brings the filters back. */}
      <div className={cn("space-y-3", query.turn && !graded ? "hidden lg:block" : "")}>
        <FilterBar
          key={`${view.show}|${view.agent}|${view.asked}|${view.from}|${view.to}`}
          action={base}
          keep={{ show: view.show, state: view.state, verdict: view.verdict }}
          chips={chips}
          chipsLabel={graded ? "Show grades" : "Show replies that"}
          asked={view.asked}
          from={view.from}
          to={view.to}
          agent={view.agent}
        />

        {filtered ? (
          <p className="-mt-2 flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
            Showing {shown} of {tabTotal} {graded ? "graded" : "waiting"}
            {period}
            <Link
              href={graded ? `${base}?show=graded` : base}
              className="font-medium text-foreground underline underline-offset-3"
            >
              Show all
            </Link>
          </p>
        ) : null}
      </div>

      {graded ? (
        selected ? (
          <div className="space-y-3">
            <Link href={link({})} className="text-sm text-muted-foreground hover:text-foreground">
              ← All graded replies
            </Link>
            <ReplyDetail turn={selected} earlier={earlier} viewerId={viewerId}>
              <GradeBar
                key={selected.id}
                tenantId={tenantId}
                turnId={selected.id}
                verdict={selected.verdict}
                note={selected.note}
                nextHref={null}
              />
            </ReplyDetail>
          </div>
        ) : turns.length === 0 ? (
          <Empty
            title={
              tabTotal === 0
                ? "Nothing graded yet"
                : view.verdict === "would_have_harmed"
                  ? "No reply was graded harmful"
                  : "No graded reply matches these filters"
            }
            text={
              tabTotal === 0
                ? "Replies you grade in To review show up here, to look back at or change."
                : view.verdict === "would_have_harmed"
                  ? "If you ever grade one harmful, it shows here — it is the grade that stops a go-live."
                  : "Try other filters, or show every graded reply."
            }
          />
        ) : (
          <>
            <GradedTable turns={turns} viewerId={viewerId} hrefFor={(id) => link({ turn: id })} />
            <Pager
              older={meta.next_cursor ? link({ cursor: meta.next_cursor }) : null}
              newest={query.cursor ? link({}) : null}
            />
          </>
        )
      ) : order.length === 0 && !selected ? (
        tabTotal === 0 ? (
          card.graded > 0 ? (
            <Empty
              title="All caught up"
              text="Nothing is waiting for your review. New practice replies will appear here."
              action={{ href: `${base}?show=graded`, label: "See what you graded" }}
            />
          ) : (
            <Empty
              title="Nothing to review yet"
              text="This fills up while your assistant runs in practice mode: it answers real questions in full, nobody is shown the answer, and the reply lands here for you to judge. If it stays empty, practice mode is probably off for this shop — an assistant that is already live has nothing to hold back."
            />
          )
        ) : (
          <Empty
            title="No waiting reply matches these filters"
            text={`${tabTotal} ${tabTotal === 1 ? "reply is" : "replies are"} waiting, but none with these filters.`}
            action={{ href: base, label: "Show all waiting replies" }}
          />
        )
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(15rem,20rem)_1fr]">
          <div className={cn(query.turn ? "hidden lg:block" : "block")}>
            <WaitingList
              groups={groups}
              selectedId={selected?.id}
              hrefFor={(id) => link({ turn: id })}
              olderHref={meta.next_cursor ? link({ cursor: meta.next_cursor }) : null}
            />
            {query.cursor ? (
              <Link
                href={link({})}
                className="mt-3 block text-center text-sm text-muted-foreground hover:text-foreground"
              >
                Back to the newest
              </Link>
            ) : null}
          </div>
          <div className={cn("space-y-3", query.turn ? "block" : "hidden lg:block")}>
            <Link
              href={link({})}
              className="text-sm text-muted-foreground hover:text-foreground lg:hidden"
            >
              ← All waiting replies
            </Link>
            {selected ? (
              <ReplyDetail
                turn={selected}
                earlier={earlier}
                viewerId={viewerId}
                position={position}
              >
                <GradeBar
                  key={selected.id}
                  tenantId={tenantId}
                  turnId={selected.id}
                  verdict={selected.verdict}
                  note={selected.note}
                  nextHref={nextHref}
                />
              </ReplyDetail>
            ) : (
              <Empty
                title="That reply could not be found"
                text="It may belong to another shop, or it was removed."
              />
            )}
          </div>
        </div>
      )}
    </>
  );
}

/**
 * What was said in the same chat before this question — so a follow-up like
 * "what about the red one?" can be judged. Read from the transcript the
 * Conversations screen already uses; gone with it after retention, in which
 * case nothing is shown rather than a guess.
 */
async function earlierIn(shop: string, turn: ReviewTurn): Promise<TranscriptMessage[]> {
  if (!turn.question.recorded || !turn.question.asked_at) return [];
  const thread = await fromApi<Transcript>(
    `/shops/${shop}/conversations/${encodeURIComponent(turn.conversation_id)}`,
  );
  if (!thread.ok) return [];
  const asked = Date.parse(turn.question.asked_at);
  return thread.data.messages
    .filter((message) => message.created_at && Date.parse(message.created_at) < asked)
    .slice(-EARLIER_SHOWN);
}

function Empty({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: { href: string; label: string };
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-12 text-center">
      <p className="text-lg font-semibold">{title}</p>
      <p className="max-w-prose text-sm text-muted-foreground">{text}</p>
      {action ? (
        <Link href={action.href} className="mt-2 text-sm font-medium underline underline-offset-3">
          {action.label}
        </Link>
      ) : null}
    </div>
  );
}

function Pager({ older, newest }: { older: string | null; newest: string | null }) {
  if (!older && !newest) return null;
  return (
    <div className="flex justify-between text-sm">
      {newest ? (
        <Link href={newest} className="font-medium underline underline-offset-3">
          ← Newest
        </Link>
      ) : (
        <span />
      )}
      {older ? (
        <Link href={older} className="font-medium underline underline-offset-3">
          Older →
        </Link>
      ) : null}
    </div>
  );
}
