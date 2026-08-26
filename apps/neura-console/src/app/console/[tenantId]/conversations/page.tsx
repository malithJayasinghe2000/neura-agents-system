/**
 * Screen 2 — Conversations. What the assistant actually said. ADR-0026.
 *
 * Read-only, and the twin of Review: that screen holds what the agent *would*
 * have said and nobody saw; this one holds what it *did* say and a shopper read.
 * The two live in separate tables for the reason `shadow.py` gives — a withheld
 * draft written into the transcript would become history, and the next turn
 * would answer as though the shopper had read it.
 *
 * **The filter never hides a state by default.** `Everything` is the first tab
 * and the default, because the interesting rows here are the refusals and a list
 * that opened on "Answered" would quietly report a healthier product than the
 * one the merchant has.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { ShopNav } from "@/components/shop/shop-nav";
import { StateBadge } from "@/components/shop/state-badge";
import { fromApi, hasSession } from "@/lib/server-api";
import { STATE_FILTERS, type ConversationRow } from "@/lib/conversations";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default async function ConversationsPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ state?: string; cursor?: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const { state = "", cursor } = await searchParams;

  const query = new URLSearchParams();
  if (state) query.set("state", state);
  if (cursor) query.set("cursor", cursor);
  const suffix = query.size ? `?${query}` : "";

  const list = await fromApi<ConversationRow[]>(
    `/shops/${encodeURIComponent(tenantId)}/conversations${suffix}`,
  );

  return (
    <>
      <ShopNav tenantId={tenantId} current="conversations" />

      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Conversations</h1>
        <p className="text-muted-foreground">
          Every thread your assistant has held, and how each one ended. Read-only — nothing here
          changes anything.
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
          <nav className="flex flex-wrap gap-2" aria-label="Filter by how the conversation ended">
            {STATE_FILTERS.map((option) => (
              <Button
                key={option.key || "all"}
                size="sm"
                variant={option.key === state ? "secondary" : "ghost"}
                // Renders an <a>; Base UI needs telling, or the element loses
                // its button semantics for a screen reader (ADR-0026 §1).
                nativeButton={false}
                render={
                  <Link
                    href={`/console/${encodeURIComponent(tenantId)}/conversations${
                      option.key ? `?state=${option.key}` : ""
                    }`}
                  />
                }
              >
                {option.label}
              </Button>
            ))}
          </nav>

          {list.data.length === 0 ? (
            <EmptyList filtered={state !== ""} />
          ) : (
            <>
              <ul className="space-y-2">
                {list.data.map((row) => (
                  <li key={row.id}>
                    <ConversationRowCard tenantId={tenantId} row={row} />
                  </li>
                ))}
              </ul>

              {/* Same rule as Review: a list that cannot reach its next cursor
                  is sampling by omission. */}
              {list.meta.next_cursor ? (
                <div className="flex justify-center pt-2">
                  <Button
                    variant="outline"
                    size="sm"
                    nativeButton={false}
                    render={
                      <Link
                        href={`/console/${encodeURIComponent(tenantId)}/conversations?${new URLSearchParams(
                          {
                            ...(state ? { state } : {}),
                            cursor: list.meta.next_cursor,
                          },
                        )}`}
                      />
                    }
                  >
                    Older conversations
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </>
      )}
    </>
  );
}

function ConversationRowCard({ tenantId, row }: { tenantId: string; row: ConversationRow }) {
  return (
    <Link
      href={`/console/${encodeURIComponent(tenantId)}/conversations/${encodeURIComponent(row.id)}`}
      className="block rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <Card className="transition-colors hover:bg-muted/40">
        <CardContent className="flex items-center gap-4">
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <StateBadge state={row.state} />
              <span className="text-xs text-muted-foreground">{row.agent}</span>
              {row.external_ref ? (
                <code className="truncate text-xs text-muted-foreground">{row.external_ref}</code>
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground">
              {row.turns} {row.turns === 1 ? "turn" : "turns"}
              {row.escalations > 0 ? ` · ${row.escalations} escalated` : ""} · {row.channel} ·{" "}
              {formatWhen(row.updated_at)}
            </p>
          </div>
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        </CardContent>
      </Card>
    </Link>
  );
}

/**
 * `docs/console.md §5` — the empty state is the most valuable documentation in
 * the product and the piece most often left until last. Two different
 * emptinesses, and telling a merchant the wrong one wastes their afternoon.
 */
function EmptyList({ filtered }: { filtered: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {filtered ? "Nothing ended that way" : "No conversations yet"}
        </CardTitle>
        <CardDescription>
          {filtered
            ? "No conversation for this shop finished in the state you picked. Try Everything."
            : "Nothing has talked to your assistant yet. Conversations appear here as soon as the widget on your shop is used — there is nothing to switch on."}
        </CardDescription>
      </CardHeader>
    </Card>
  );
}

function formatWhen(value: string | null): string {
  if (!value) return "";
  const when = new Date(value);
  return Number.isNaN(when.getTime()) ? "" : when.toLocaleString();
}
