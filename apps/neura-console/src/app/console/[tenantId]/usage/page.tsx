/**
 * Screen 5 — Usage. The one that is easiest to make dishonest.
 *
 * `docs/console.md §5`: *"Every number carries its own honesty… `docs/` has been
 * disciplined about this from the beginning and a dashboard is exactly where
 * that discipline usually dies."* Four rules follow from that, and every one of
 * them is subtractive:
 *
 * 1. **No rate.** Not a deflection rate, not a resolution rate, not a trend.
 *    Every ratio this data supports is a business claim in disguise; the screen
 *    shows "2 of 41", which a merchant can check.
 * 2. **No cost figure that means nothing.** Zero is what a local model records
 *    *and* what an unpriced hosted model records. Words, not `$0.00`.
 * 3. **The period is on the screen, always.** "142 turns" says nothing without
 *    "since when", and a screen that silently changed window between two visits
 *    would look like traffic changing.
 * 4. **Shadow mode is stated first.** True numbers describing work no shopper
 *    ever saw is the most misleading page this console could produce.
 *
 * The caveats come from the server, not from here: a merchant-facing sentence
 * living in a JavaScript bundle is one nobody reviews and nobody can change
 * (ADR-0020 §3).
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { EyeOff, Info } from "lucide-react";
import { ShopNav } from "@/components/shop/shop-nav";
import { fromApi, hasSession } from "@/lib/server-api";
import { PERIODS, type Totals, type Usage } from "@/lib/usage";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default async function UsagePage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ period?: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const { period = "30d" } = await searchParams;
  const chosen = PERIODS.some((p) => p.key === period) ? period : "30d";

  const result = await fromApi<Usage>(
    `/shops/${encodeURIComponent(tenantId)}/usage?period=${encodeURIComponent(chosen)}`,
  );

  return (
    <>
      <ShopNav tenantId={tenantId} current="usage" />

      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Usage</h1>
        <p className="text-muted-foreground">
          What your assistant did, and what these numbers do not say.
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
        <UsageBody tenantId={tenantId} chosen={chosen} usage={result.data} />
      )}
    </>
  );
}

function UsageBody({
  tenantId,
  chosen,
  usage,
}: {
  tenantId: string;
  chosen: string;
  usage: Usage;
}) {
  const empty = usage.totals.turns === 0;

  return (
    <>
      <nav className="flex flex-wrap gap-2" aria-label="Period">
        {PERIODS.map((option) => (
          <Button
            key={option.key}
            size="sm"
            variant={option.key === chosen ? "secondary" : "ghost"}
            nativeButton={false}
            render={
              <Link href={`/console/${encodeURIComponent(tenantId)}/usage?period=${option.key}`} />
            }
          >
            {option.label}
          </Button>
        ))}
      </nav>

      {/* Stated before any figure. A merchant reading "41 conversations" while
          in shadow mode is reading about an assistant no shopper has met. */}
      {usage.withheld ? (
        <Alert>
          <EyeOff aria-hidden />
          <AlertTitle>Nobody was shown any of this</AlertTitle>
          <AlertDescription>
            This shop is in shadow mode. Everything below is work your assistant did with the
            replies withheld — they are waiting for your verdict in{" "}
            <Link
              className="underline underline-offset-3"
              href={`/console/${encodeURIComponent(tenantId)}/review`}
            >
              Review
            </Link>
            .
          </AlertDescription>
        </Alert>
      ) : null}

      {empty ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Nothing recorded in this period</CardTitle>
            <CardDescription>
              {usage.period.days === null
                ? "Nothing has ever been recorded for this shop. Usage appears here from the first time a shopper talks to your assistant."
                : "No turns were recorded in this window. Try a longer one — there may be older activity."}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{describePeriod(usage)}</CardTitle>
            </CardHeader>
            <CardContent>
              <Counters totals={usage.totals} />
            </CardContent>
          </Card>

          {Object.keys(usage.today_by_agent).length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">By assistant, today</CardTitle>
                <CardDescription>
                  {/* Labelled as today rather than silently summed over a period
                      the meter does not break down. */}
                  The per-assistant split is recorded daily, so this covers today only — not the
                  period selected above.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {Object.entries(usage.today_by_agent).map(([agent, totals]) => (
                  <div key={agent} className="space-y-2">
                    <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                      {agent}
                    </h3>
                    <Counters totals={totals} />
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </>
      )}

      {usage.caveats.length > 0 ? (
        <Card className="border-dashed bg-muted/30">
          <CardHeader>
            <CardTitle className="text-base">What these numbers do not say</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {usage.caveats.map((caveat) => (
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

function Counters({ totals }: { totals: Totals }) {
  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-4">
      <Stat label="conversations" value={totals.conversations} />
      <Stat label="turns" value={totals.turns} />
      <Stat label="handed to a person" value={totals.escalations} />
      <Stat label="attacks blocked" value={totals.blocked} />
      <Stat label="tokens" value={totals.total_tokens.toLocaleString()} />
      {/* Words, never `$0.00`. Zero is what a free local model records and what
          a hosted model with no configured price records — the figure cannot
          tell a merchant which, so it does not pretend to. */}
      <Stat
        label="cost"
        value={totals.cost.measured ? `$${totals.cost.usd}` : "not priced"}
        muted={!totals.cost.measured}
      />
    </dl>
  );
}

function Stat({
  label,
  value,
  muted = false,
}: {
  label: string;
  value: string | number;
  muted?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd
        className={
          muted
            ? "text-base font-medium text-muted-foreground"
            : "text-xl font-semibold tabular-nums"
        }
      >
        {value}
      </dd>
    </div>
  );
}

/** The period, in words, on the card the numbers are on. */
function describePeriod(usage: Usage): string {
  if (usage.period.days === null) return "Everything recorded for this shop";
  if (usage.period.days === 1) return `Today, ${usage.period.through}`;
  return `${usage.period.days} days, ${usage.period.since} to ${usage.period.through}`;
}
