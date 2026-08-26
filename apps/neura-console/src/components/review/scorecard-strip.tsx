/**
 * What the queue says so far — and what it does not yet say.
 *
 * `docs/console.md §5`: *"a dashboard is exactly where that discipline usually
 * dies."* So three rules run this component, all of them subtractive:
 *
 * 1. **Counts first, and no rate without its count.** "100% agreement" over two
 *    graded turns and over two hundred read identically otherwise.
 * 2. **No rate at all until something is graded.** The API returns `null`, not
 *    `0`, and `null` renders as a sentence rather than as a zero — an unreviewed
 *    queue has not failed review.
 * 3. **Harm is a yes/no.** `shadow.py` keeps it a boolean on purpose: there is
 *    no acceptable percentage of harmful answers about a shopper's money.
 *
 * There is no chart, no trend and no target. Every one of those needs a
 * denominator this project has not measured yet (`CLAUDE.md §4`).
 */
import type { Scorecard } from "@/lib/review";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

export function ScorecardStrip({ card }: { card: Scorecard }) {
  return (
    <Card size="sm">
      <CardContent className="space-y-3">
        <dl className="flex flex-wrap gap-x-8 gap-y-3">
          <Stat
            label="recorded"
            value={card.recorded}
            hint="turns the agent drafted and withheld"
          />
          <Stat label="graded" value={card.graded} hint="turns a person has judged" />
          <Stat label="left to review" value={card.ungraded} />
          <Stat label="would have escalated" value={card.escalated} />
        </dl>

        {card.graded === 0 ? (
          // The honest empty scorecard. Not "0% agreement", which would read as
          // a measured failure of a queue nobody has opened.
          <p className="text-sm text-muted-foreground">
            Nothing has been graded yet, so there is no agreement figure to show. There will be one
            after the first verdict — reported beside the number of turns it is based on.
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">
              <span className="font-medium text-foreground">
                {card.verdicts.agree} of {card.graded}
              </span>{" "}
              graded turns you&apos;d have sent as written
              {card.agreement_rate !== null ? (
                <span className="text-muted-foreground">
                  {" "}
                  ({Math.round(card.agreement_rate * 100)}%)
                </span>
              ) : null}
              .
            </span>
            {card.harm_free === false ? (
              <Badge variant="destructive">
                {card.verdicts.would_have_harmed} would have caused harm
              </Badge>
            ) : (
              <Badge variant="muted">none marked harmful so far</Badge>
            )}
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          These are counts from this shop&apos;s own shadow traffic. Every turn recorded is listed —
          nothing is sampled.
        </p>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div title={hint}>
      <dt className="text-xs tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="text-xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
