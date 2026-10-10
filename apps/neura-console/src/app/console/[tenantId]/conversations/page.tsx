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
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { StateBadge } from "@/components/shop/state-badge";
import { TokenNote, hasToken } from "@/components/shop/token-note";
import { When } from "@/components/when";
import { ASSISTANT_CHOICES, assistantName } from "@/lib/assistants";
import { STATE_FILTERS, questions, type ConversationRow } from "@/lib/conversations";
import { fromApi, hasSession, type PageMeta } from "@/lib/server-api";
import { PERMISSION, refusal } from "@/lib/roles";
import { NotAllowed } from "@/components/not-allowed";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Filters = { state: string; agent: string; q: string };

export default async function ConversationsPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ state?: string; agent?: string; q?: string; cursor?: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  // A role that does not include this screen sees why, not an error (ADR-0058).
  const refused = await refusal(tenantId, PERMISSION.conversations);
  if (refused) return <NotAllowed refusal={refused} what="shoppers' chats" />;
  const { state = "", agent = "", q = "", cursor } = await searchParams;
  const filters: Filters = { state, agent, q: q.trim() };

  const query = new URLSearchParams(present(filters));
  if (cursor) query.set("cursor", cursor);
  const suffix = query.size ? `?${query}` : "";

  const list = await fromApi<ConversationRow[]>(
    `/shops/${encodeURIComponent(tenantId)}/conversations${suffix}`,
  );
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
            {STATE_FILTERS.map((option) => (
              <Link
                key={option.key || "all"}
                href={hrefFor(base, { ...filters, state: option.key })}
                aria-current={option.key === filters.state ? "page" : undefined}
                className={
                  option.key === filters.state
                    ? "inline-flex h-9 items-center rounded-full border border-foreground bg-foreground px-4 text-sm font-medium text-background"
                    : "inline-flex h-9 items-center rounded-full border px-4 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                }
              >
                {option.label}
              </Link>
            ))}
          </nav>

          {list.data.length === 0 ? (
            <EmptyList
              filtered={Boolean(filters.state || filters.agent || filters.q)}
              clearHref={base}
            />
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
        </>
      )}
    </>
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
          <StateBadge state={row.state} />
          <span>{assistantName(row.agent)}</span>
          <span aria-hidden>·</span>
          <span>{questions(row.turns)}</span>
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
