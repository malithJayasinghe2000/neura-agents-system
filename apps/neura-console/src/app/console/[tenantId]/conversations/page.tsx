/**
 * Screen 2 — Conversations. What the assistant actually said. ADR-0026.
 *
 * Read-only, and the twin of Review: that screen holds what the agent *would*
 * have said and nobody saw; this one holds what it *did* say and a shopper read.
 * The two live in separate tables for the reason `shadow.py` gives — a withheld
 * draft written into the transcript would become history, and the next turn
 * would answer as though the shopper had read it.
 *
 * **The filter never hides a state by default.** `All` is the first choice and
 * the default, because the interesting rows here are the refusals and a list
 * that opened on "Answered" would quietly report a healthier product than the
 * one the merchant has.
 *
 * **Finding a thread (2026-09-27, the owner's approved mockup).** Each row leads
 * with the shopper's first question, the list can be searched by what shoppers
 * wrote and narrowed by assistant, and it says *"Showing 26–50 of 55"*. All of it
 * is in the URL, so a search is a link a merchant can keep — and the search box
 * is a plain GET form, which works before any JavaScript has loaded.
 */
import Form from "next/form";
import Link from "next/link";
import { redirect } from "next/navigation";
import { ChevronLeft, ChevronRight, Clock, Search } from "lucide-react";
import { StateBadge } from "@/components/shop/state-badge";
import { WaitingBadge } from "@/components/conversations/waiting-badge";
import { TokenNote, hasToken } from "@/components/shop/token-note";
import { When } from "@/components/when";
import { ASSISTANT_CHOICES, assistantName } from "@/lib/assistants";
import {
  STATE_FILTERS,
  WAITING_FILTER,
  questions,
  type ConversationRow,
} from "@/lib/conversations";
import { fromApi, hasSession, type PageMeta } from "@/lib/server-api";
import { PERMISSION, refusal } from "@/lib/roles";
import { thing } from "@/lib/wanted";
import { NotAllowed } from "@/components/not-allowed";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Filters = {
  state: string;
  agent: string;
  q: string;
  /** *See the chats* on Missing from your pages (ADR-0064): one row's label, its
   * product (none for the shop), and its question, to say what is shown. */
  gap?: string;
  gap_product?: string;
  asked?: string;
  /** *See the chats* on Shoppers asked for (ADR-0068): one row's label. */
  wanted?: string;
};

export default async function ConversationsPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{
    state?: string;
    agent?: string;
    q?: string;
    cursor?: string;
    gap?: string;
    gap_product?: string;
    asked?: string;
    wanted?: string;
  }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  // A role that does not include this screen sees why, not an error (ADR-0058).
  const refused = await refusal(tenantId, PERMISSION.conversations);
  if (refused) return <NotAllowed refusal={refused} what="shoppers' chats" />;
  const {
    state = "",
    agent = "",
    q = "",
    cursor,
    gap = "",
    gap_product = "",
    asked = "",
    wanted = "",
  } = await searchParams;
  const filters: Filters = { state, agent, q: q.trim(), gap, gap_product, asked, wanted };

  // *Waiting for an answer* is not a conversation state: the API is asked for
  // `?waiting=1` (ADR-0062 §6). Every other choice is the state itself.
  const waitingOnly = filters.state === WAITING_FILTER;
  const query = new URLSearchParams(
    present({ ...filters, state: waitingOnly ? "" : filters.state }),
  );
  if (waitingOnly) query.set("waiting", "1");
  // `asked` is only this page's words for the line above the list.
  query.delete("asked");
  if (cursor) query.set("cursor", cursor);
  const suffix = query.size ? `?${query}` : "";

  const [list, home] = await Promise.all([
    fromApi<ConversationRow[]>(`/shops/${encodeURIComponent(tenantId)}/conversations${suffix}`),
    // How many wait, for the choice's count: `null` for a role that may not answer.
    fromApi<{ waiting: number | null }>(`/shops/${encodeURIComponent(tenantId)}/home`),
  ]);
  const waitingCount = home.ok ? home.data.waiting : null;
  const base = `/console/${encodeURIComponent(tenantId)}/conversations`;

  return (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Conversations</h1>
        <p className="text-muted-foreground">
          Every chat your assistant has had, newest first. Reading here changes nothing.
        </p>
      </div>

      {!list.ok ? (
        <Alert variant="destructive">
          <AlertTitle>
            {list.status === 404 ? "No such shop, or no access to it" : "Could not load"}
          </AlertTitle>
          <AlertDescription>
            {list.status === 404
              ? "Your account does not hold a live membership for this shop."
              : list.message}
          </AlertDescription>
        </Alert>
      ) : (
        <>
          {/* Keyed by the filters, so following "Clear" or a state link resets
              what the box shows instead of keeping the last words typed. */}
          <Form
            key={`${filters.q}|${filters.agent}|${filters.state}`}
            action={base}
            role="search"
            className="flex flex-col gap-3 sm:flex-row sm:items-center"
          >
            {filters.state ? <input type="hidden" name="state" value={filters.state} /> : null}
            <label className="relative flex-1">
              <span className="sr-only">Search what shoppers asked</span>
              <Search
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                type="search"
                name="q"
                defaultValue={filters.q}
                maxLength={100}
                placeholder="Search what shoppers asked — try “order” or “jacket”"
                className="h-11 pl-9 text-base md:text-sm"
              />
            </label>
            <div className="flex gap-3">
              <label className="flex flex-1 items-center gap-2 text-sm text-muted-foreground">
                <span className="shrink-0">Assistant</span>
                <select
                  name="agent"
                  defaultValue={filters.agent}
                  className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 sm:w-auto"
                >
                  <option value="">All assistants</option>
                  {ASSISTANT_CHOICES.map((choice) => (
                    <option key={choice.key} value={choice.key}>
                      {choice.label}
                    </option>
                  ))}
                </select>
              </label>
              <Button type="submit" className="h-11 px-4">
                Search
              </Button>
            </div>
          </Form>

          <nav className="flex flex-wrap gap-2" aria-label="Show conversations that ended as">
            {STATE_FILTERS.filter(
              // Only for a role that may answer them; `null` means it may not.
              (option) => option.key !== WAITING_FILTER || waitingCount !== null,
            ).map((option) => (
              <Link
                key={option.key || "all"}
                href={hrefFor(base, { ...filters, state: option.key })}
                aria-current={option.key === filters.state ? "page" : undefined}
                data-waiting-chip={option.key === WAITING_FILTER ? "" : undefined}
                className={
                  option.key === filters.state
                    ? "inline-flex h-9 items-center gap-2 rounded-full border border-foreground bg-foreground px-4 text-sm font-medium text-background"
                    : "inline-flex h-9 items-center gap-2 rounded-full border px-4 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                }
              >
                {option.label}
                {option.key === WAITING_FILTER && waitingCount ? (
                  <span className="grid h-5 min-w-5 place-items-center rounded-full bg-amber-400 px-1.5 text-xs font-semibold text-amber-950 tabular-nums">
                    {waitingCount}
                  </span>
                ) : null}
              </Link>
            ))}
          </nav>

          {filters.gap ? (
            <GapLine
              asked={filters.asked || filters.gap}
              gapsHref={`/console/${encodeURIComponent(tenantId)}/gaps`}
              allHref={base}
            />
          ) : null}

          {filters.wanted ? (
            <WantedLine
              label={filters.wanted}
              wantedHref={`/console/${encodeURIComponent(tenantId)}/wanted`}
              allHref={base}
            />
          ) : null}

          {waitingOnly && list.data.length > 0 ? (
            <WaitingLine count={list.meta.total ?? list.data.length} />
          ) : null}

          {list.data.length === 0 ? (
            waitingOnly ? (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Nobody is waiting for an answer</CardTitle>
                  <CardDescription>
                    When your assistant hands a chat over and the shopper leaves a way to reach
                    them, it shows up here.
                  </CardDescription>
                </CardHeader>
              </Card>
            ) : (
              <EmptyList
                filtered={Boolean(
                  filters.state || filters.agent || filters.q || filters.gap || filters.wanted,
                )}
                clearHref={base}
              />
            )
          ) : (
            <>
              <ul className="divide-y overflow-hidden rounded-xl border">
                {list.data.map((row) => (
                  <li key={row.id}>
                    <ConversationRowLink tenantId={tenantId} row={row} />
                  </li>
                ))}
              </ul>

              {hasToken(...list.data.map((row) => row.first_question ?? "")) ? <TokenNote /> : null}

              {/* Same rule as Review: a list that cannot reach its next page is
                  sampling by omission. */}
              <Pager base={base} filters={filters} shown={list.data.length} meta={list.meta} />
            </>
          )}

          {waitingOnly ? (
            <p className="text-sm text-muted-foreground">
              A chat where the shopper pressed <em>No thanks</em> is not here: nobody can answer it.
              It stays under <em>Handed to a person</em>.
            </p>
          ) : null}
        </>
      )}
    </>
  );
}

/** Above the chats behind one row of Missing from your pages (ADR-0064). */
function GapLine({
  asked,
  gapsHref,
  allHref,
}: {
  asked: string;
  gapsHref: string;
  allHref: string;
}) {
  return (
    <p data-gap-line className="text-sm leading-relaxed">
      The chats where shoppers asked{" "}
      <strong className="font-semibold">&ldquo;{asked}&rdquo;</strong>.{" "}
      <Link className="underline underline-offset-3" href={gapsHref}>
        Back to Missing from your pages
      </Link>{" "}
      ·{" "}
      <Link className="underline underline-offset-3" href={allHref}>
        Show every conversation
      </Link>
    </p>
  );
}

/** Above the chats behind one row of Shoppers asked for (ADR-0068). */
function WantedLine({
  label,
  wantedHref,
  allHref,
}: {
  label: string;
  wantedHref: string;
  allHref: string;
}) {
  return (
    <p data-wanted-line className="text-sm leading-relaxed">
      The chats where shoppers asked for{" "}
      <strong className="font-semibold">&ldquo;{thing(label)}&rdquo;</strong>.{" "}
      <Link className="underline underline-offset-3" href={wantedHref}>
        Back to Shoppers asked for
      </Link>{" "}
      ·{" "}
      <Link className="underline underline-offset-3" href={allHref}>
        Show every conversation
      </Link>
    </p>
  );
}

/** *2 shoppers are waiting for an answer.* Above the waiting list (ADR-0062 §6). */
function WaitingLine({ count }: { count: number }) {
  return (
    <div
      data-waiting-line
      className="flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3.5 text-amber-950 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100"
    >
      <Clock className="mt-0.5 size-4 shrink-0" aria-hidden />
      <p className="text-sm">
        <span className="font-semibold">
          {count === 1
            ? "1 shopper is waiting for an answer."
            : `${count} shoppers are waiting for an answer.`}
        </span>{" "}
        {count === 1
          ? "Your assistant handed them over, and they left a way to reach them. Open the chat to answer by email."
          : "Your assistant handed them over, and each left a way to reach them. Open one to answer by email."}
      </p>
    </div>
  );
}

function ConversationRowLink({ tenantId, row }: { tenantId: string; row: ConversationRow }) {
  return (
    <Link
      href={`/console/${encodeURIComponent(tenantId)}/conversations/${encodeURIComponent(row.id)}`}
      className="flex items-center gap-4 px-4 py-3.5 transition-colors outline-none hover:bg-muted/40 focus-visible:bg-muted/60 sm:px-5"
    >
      <div className="min-w-0 flex-1 space-y-2">
        {row.first_question ? (
          <p className="truncate font-medium">“{row.first_question}”</p>
        ) : (
          // Said, not left blank: a conversation can start and hold nothing.
          <p className="text-muted-foreground italic">No message from the shopper</p>
        )}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          {row.waiting ? <WaitingBadge /> : <StateBadge state={row.state} />}
          <span>{assistantName(row.agent)}</span>
          <span aria-hidden>·</span>
          <span>{questions(row.turns)}</span>
          {row.waiting ? (
            <>
              <span aria-hidden>·</span>
              <span>
                {row.waiting.reach === "email" ? "left an email" : "signed in to your shop"}
              </span>
            </>
          ) : null}
          {row.escalations > 0 && row.state !== "escalated" ? (
            <>
              <span aria-hidden>·</span>
              <span>
                handed to a person {row.escalations === 1 ? "once" : `${row.escalations} times`}
              </span>
            </>
          ) : null}
          {row.external_ref ? (
            <code className="truncate text-xs text-muted-foreground">{row.external_ref}</code>
          ) : null}
        </div>
      </div>
      <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">
        <When iso={row.updated_at} />
      </span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
    </Link>
  );
}

/**
 * *"Showing 26–50 of 55"*, and the two ways out of this page.
 *
 * The position comes from the server's count, not from this page counting its
 * own clicks — a number the browser kept would be wrong the moment somebody
 * opened a shared link.
 */
function Pager({
  base,
  filters,
  shown,
  meta,
}: {
  base: string;
  filters: Filters;
  shown: number;
  meta: PageMeta;
}) {
  const from = (meta.offset ?? 0) + 1;
  const through = (meta.offset ?? 0) + shown;
  const filtered = Boolean(filters.state || filters.agent || filters.q);
  const newer = meta.has_previous
    ? hrefFor(base, filters, meta.previous_cursor ?? undefined)
    : null;
  const older = meta.next_cursor ? hrefFor(base, filters, meta.next_cursor) : null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-muted-foreground">
        {meta.total === undefined
          ? null
          : `Showing ${from}–${through} of ${meta.total}${filtered ? " that match" : ""}`}
      </p>
      <div className="flex gap-2">
        {newer ? (
          <Button
            variant="outline"
            className="h-10 px-3"
            nativeButton={false}
            render={<Link href={newer} />}
          >
            <ChevronLeft aria-hidden />
            Newer
          </Button>
        ) : (
          <Button variant="outline" className="h-10 px-3" disabled>
            <ChevronLeft aria-hidden />
            Newer
          </Button>
        )}
        {older ? (
          <Button
            variant="outline"
            className="h-10 px-3"
            nativeButton={false}
            render={<Link href={older} />}
          >
            Older
            <ChevronRight aria-hidden />
          </Button>
        ) : (
          <Button variant="outline" className="h-10 px-3" disabled>
            Older
            <ChevronRight aria-hidden />
          </Button>
        )}
      </div>
    </div>
  );
}

/**
 * `docs/console.md §5` — the empty state is the most valuable documentation in
 * the product and the piece most often left until last. Two different
 * emptinesses, and telling a merchant the wrong one wastes their afternoon.
 */
function EmptyList({ filtered, clearHref }: { filtered: boolean; clearHref: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {filtered ? "No conversation matches" : "No conversations yet"}
        </CardTitle>
        <CardDescription>
          {filtered ? (
            <>
              Try other words, or{" "}
              <Link className="text-foreground underline underline-offset-3" href={clearHref}>
                show every conversation
              </Link>
              .
            </>
          ) : (
            "Nothing has talked to your assistant yet. Conversations appear here as soon as the widget on your shop is used — there is nothing to switch on."
          )}
        </CardDescription>
      </CardHeader>
    </Card>
  );
}

/** Only the filters that are set — an empty `?q=` is noise in a link somebody keeps. */
function present(filters: Filters): Record<string, string> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== ""));
}

/** A link to this list with these filters. Changing a filter starts again at page one. */
function hrefFor(base: string, filters: Filters, cursor?: string): string {
  const query = new URLSearchParams(present(filters));
  if (cursor) query.set("cursor", cursor);
  return query.size ? `${base}?${query}` : base;
}
