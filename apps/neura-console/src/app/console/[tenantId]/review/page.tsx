/**
 * Screen 3 — Review. Grading what the agent would have said. ADR-0026.
 *
 * **This is the screen the console was built for**, and the build order in
 * `docs/console.md §2` says so: it is second of five because it is the only one
 * that produces something this project does not have — *real graded turns* —
 * which is the sole route out of open question **E1**, where every golden case
 * is synthetic. A console that shipped analytics first would look finished and
 * change nothing.
 *
 * Four things here are decisions rather than layout:
 *
 * 1. **The evidence is on the card, not behind a click.** A grader who has to
 *    ask for it grades fluency (§3.2, open question E7).
 * 2. **Declined and escalated turns are in the queue and look it.** The filter
 *    is on whether a *human* has graded, never on what the agent did — hiding
 *    the turns the agent refused is the merchant-facing version of the empty
 *    bubble ADR-0020 was written about, and those are the interesting rows.
 * 3. **No sampling.** Every recorded turn is reachable through the cursor.
 *    Open question **A4** is unanswered, and a rate chosen before anybody has
 *    graded for an hour is a rate invented to fit an imaginary constraint.
 * 4. **No number that was not measured.** §5, and `CLAUDE.md §4`.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ShopNav } from "@/components/shop/shop-nav";
import { ScorecardStrip } from "@/components/review/scorecard-strip";
import { TurnCard } from "@/components/review/turn-card";
import { fromApi, hasSession } from "@/lib/server-api";
import type { ReviewTurn, Scorecard } from "@/lib/review";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Me = { signed_in: boolean; user_id?: string };
type Failure = { ok: false; status: number; message: string };

/** The three views of one queue. `all` is the default so nothing is hidden by default. */
const FILTERS = [
  { key: "", label: "Everything", graded: undefined },
  { key: "ungraded", label: "To review", graded: false },
  { key: "graded", label: "Already graded", graded: true },
] as const;

export default async function ReviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ show?: string; cursor?: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const { show = "", cursor } = await searchParams;
  const filter = FILTERS.find((option) => option.key === show) ?? FILTERS[0];

  // Asked fresh, like every other console read: the membership check happens on
  // the API side, on this request. A person whose access was revoked a second
  // ago gets a 404 here and not a cached page (ADR-0026 §3).
  const me = await fromApi<Me>("/me");
  if (!me.ok || !me.data.signed_in) redirect("/");

  const query = new URLSearchParams();
  if (filter.graded !== undefined) query.set("graded", String(filter.graded));
  if (cursor) query.set("cursor", cursor);
  const suffix = query.size ? `?${query}` : "";

  const [card, queue] = await Promise.all([
    fromApi<Scorecard>(`/shops/${encodeURIComponent(tenantId)}/review/scorecard`),
    fromApi<ReviewTurn[]>(`/shops/${encodeURIComponent(tenantId)}/review${suffix}`),
  ]);

  // Narrowed here rather than inline, so the failure branch below is one
  // object with a status on it instead of two half-known results.
  const failure = !card.ok ? card : !queue.ok ? queue : null;

  return (
    <>
      <ShopNav tenantId={tenantId} current="review" />

      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Review</h1>
        <p className="text-muted-foreground">
          Replies your assistant drafted while in shadow mode. Nobody was shown any of them. Your
          verdicts are what decide whether it is safe to go live.
        </p>
      </div>

      {failure || !card.ok || !queue.ok ? (
        <Unreachable failure={failure} />
      ) : (
        <>
          <ScorecardStrip card={card.data} />

          <nav className="flex flex-wrap gap-2" aria-label="Filter the queue">
            {FILTERS.map((option) => (
              <Button
                key={option.key || "all"}
                size="sm"
                variant={option.key === filter.key ? "secondary" : "ghost"}
                // These render an <a>, and Base UI assumes a native <button>
                // unless told otherwise — the mismatch strips the element's
                // semantics from a screen reader. shadcn was chosen partly so
                // accessibility ships in the defaults (ADR-0026 §1), so this is
                // the fix rather than a silenced warning.
                nativeButton={false}
                render={
                  <Link
                    href={`/console/${encodeURIComponent(tenantId)}/review${
                      option.key ? `?show=${option.key}` : ""
                    }`}
                  />
                }
              >
                {option.label}
              </Button>
            ))}
          </nav>

          {queue.data.length === 0 ? (
            <EmptyQueue recorded={card.data.recorded} filtered={filter.key !== ""} />
          ) : (
            <>
              <ul className="space-y-4">
                {queue.data.map((turn) => (
                  <li key={turn.id}>
                    <TurnCard turn={turn} tenantId={tenantId} viewerId={me.data.user_id ?? ""} />
                  </li>
                ))}
              </ul>

              {/* Every recorded turn has to be reachable, or the queue is
                    sampling by omission — which is the one thing this screen's
                    design forbids (A4). The cursor is the whole of the answer:
                    it walks backwards through `(created_at, id)`, so a turn
                    recorded while somebody is reading cannot push another one
                    past them unseen. */}
              {queue.meta.next_cursor ? (
                <div className="flex justify-center pt-2">
                  <Button
                    variant="outline"
                    size="sm"
                    nativeButton={false}
                    render={
                      <Link
                        href={`/console/${encodeURIComponent(tenantId)}/review?${new URLSearchParams(
                          {
                            ...(filter.key ? { show: filter.key } : {}),
                            cursor: queue.meta.next_cursor,
                          },
                        )}`}
                      />
                    }
                  >
                    Older turns
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

/**
 * The empty state, which `console.md §5` calls the most valuable documentation
 * in the product and the piece most often left until last.
 *
 * Two genuinely different emptinesses, and telling a merchant the wrong one
 * wastes their afternoon: a filter that matched nothing, and a shop that has
 * never shadowed a turn. The second one names the cause — shadow mode must be
 * on, or this screen stays empty forever (§7).
 */
function EmptyQueue({ recorded, filtered }: { recorded: number; filtered: boolean }) {
  if (recorded > 0 && filtered) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Nothing in this view</CardTitle>
          <CardDescription>
            There are {recorded} recorded turns for this shop — they are under one of the other
            filters.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Nothing to review yet</CardTitle>
        <CardDescription>
          This queue fills up while your assistant runs in <strong>shadow mode</strong>: it answers
          real questions in full, nobody is shown the answer, and the draft lands here for you to
          judge.
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        If it stays empty, shadow mode is probably off for this shop — an assistant that is already
        live has nothing to withhold, so there is nothing to grade.
      </CardContent>
    </Card>
  );
}

function Unreachable({ failure }: { failure: Failure | null }) {
  if (!failure) return null;
  return (
    <Alert variant="destructive">
      <AlertTitle>
        {failure.status === 404 ? "No such shop, or no access to it" : "Could not load the queue"}
      </AlertTitle>
      <AlertDescription>
        {failure.status === 404
          ? "Your account does not hold a live membership for this shop. If it should, ask whoever set it up."
          : failure.message}
      </AlertDescription>
    </Alert>
  );
}
