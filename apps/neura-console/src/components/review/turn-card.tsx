/**
 * One withheld turn, as a merchant grades it.
 *
 * The order on the card is the order a grader needs it in, and it is not the
 * order the row is stored in: **question → evidence → draft → verdict**. Putting
 * the draft first is what produces a queue graded on fluency (`console.md §3.2`,
 * open question E7) — by the time you have read a confident paragraph you are
 * checking whether the evidence agrees with it rather than the other way round.
 *
 * **Every card says it was withheld**, because every row in this queue is a
 * reply no shopper saw. That is the whole premise of shadow mode and it is
 * exactly the kind of fact a screen stops mentioning after the second sprint.
 *
 * And a turn with no draft is the case this card exists to get right. The agent
 * escalated, or `verify` discarded the draft, or the guard stopped the turn —
 * those are the interesting rows, they must appear in the queue
 * ([ADR-0020](../../../../../docs/architecture/adr/0020-a-withheld-turn-says-so.md)),
 * and they must not render as an empty box.
 */
import { EyeOff, ShieldAlert, TriangleAlert, UserRoundCheck } from "lucide-react";
import type { ReviewTurn } from "@/lib/review";
import { VERDICT_LABELS } from "@/lib/review";
import { GradeForm } from "@/components/review/grade-form";
import { EvidencePanel } from "@/components/review/evidence-panel";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

/** Tokens the guard leaves behind — `[EMAIL_1]`, `[ADDRESS_2]`, `[CARD_1]`. */
const PII_TOKEN = /\[[A-Z_]+_\d+\]/;

export function TurnCard({
  turn,
  tenantId,
  viewerId,
}: {
  turn: ReviewTurn;
  tenantId: string;
  viewerId: string;
}) {
  const hasDraft = turn.draft.trim().length > 0;
  const tokenised = PII_TOKEN.test(turn.question.text) || PII_TOKEN.test(turn.draft);

  return (
    <Card>
      <CardContent className="space-y-5">
        <header className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="secondary" className="gap-1">
            <EyeOff className="size-3" aria-hidden />
            Withheld — the shopper never saw this
          </Badge>
          <Badge variant="outline">{turn.agent}</Badge>
          {turn.intent ? <Badge variant="muted">{turn.intent}</Badge> : null}
          {turn.escalated ? (
            <Badge variant="outline" className="gap-1">
              <UserRoundCheck className="size-3" aria-hidden />
              would have escalated
            </Badge>
          ) : null}
          {turn.verify.grounded === false ? (
            <Badge variant="destructive" className="gap-1">
              <ShieldAlert className="size-3" aria-hidden />
              failed the grounding check
            </Badge>
          ) : null}
          <span className="ml-auto">{formatWhen(turn.created_at)}</span>
        </header>

        <section className="space-y-1.5">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            The shopper asked
          </h3>
          {turn.question.recorded && turn.question.text ? (
            <p className="text-sm whitespace-pre-wrap">{turn.question.text}</p>
          ) : (
            <p className="text-sm text-muted-foreground">
              {turn.question.recorded
                ? "No question text was recorded for this turn."
                : "This message is no longer in the transcript — it may have been deleted under your retention policy."}
            </p>
          )}
        </section>

        <section className="space-y-1.5">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            What it worked from
          </h3>
          <EvidencePanel evidence={turn.evidence} />
        </section>

        <section className="space-y-1.5">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            What it would have replied
          </h3>
          {hasDraft ? (
            <p className="rounded-lg bg-muted/50 px-3 py-2.5 text-sm whitespace-pre-wrap">
              {turn.draft}
            </p>
          ) : (
            // Never an empty box. ADR-0020 §4's invariant, on the merchant's
            // side of the product: an empty reply with no words is a rendering
            // bug to whoever is reading it.
            <p className="flex items-start gap-2 rounded-lg border border-dashed px-3 py-2.5 text-sm text-muted-foreground">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {turn.no_draft_reason ||
                "No reply was recorded, and no reason was either. That is a bug — please report this turn."}
            </p>
          )}
          {turn.verify.reason ? (
            <p className="text-xs text-muted-foreground">
              <span className="font-medium text-foreground">The grounding check said:</span>{" "}
              {turn.verify.reason}
            </p>
          ) : null}
        </section>

        {tokenised ? (
          <p className="text-xs text-muted-foreground">
            Text like <code className="text-foreground">[EMAIL_1]</code> is a personal detail the
            guard replaced before the model saw it. The real value was never stored here.
          </p>
        ) : null}

        <footer className="space-y-3 border-t pt-4">
          <GradeForm tenantId={tenantId} turnId={turn.id} verdict={turn.verdict} note={turn.note} />
          {turn.verdict ? (
            <p className="text-xs text-muted-foreground">
              Graded {VERDICT_LABELS[turn.verdict].toLowerCase()}
              {turn.reviewed_by
                ? turn.reviewed_by === viewerId
                  ? " by you"
                  : ` by ${turn.reviewed_by}`
                : ""}
              {turn.reviewed_at ? ` · ${formatWhen(turn.reviewed_at)}` : ""}. You can change it.
            </p>
          ) : null}
          <TurnFacts turn={turn} />
        </footer>
      </CardContent>
    </Card>
  );
}

/**
 * The mechanical facts, last and quiet.
 *
 * `cost.measured` is why this is a component and not a template string. A local
 * model costs zero and an unpriced cloud model records zero, so "$0.00" would be
 * a measurement in one case and a gap in the other — `CLAUDE.md §4`. The screen
 * says which.
 */
function TurnFacts({ turn }: { turn: ReviewTurn }) {
  return (
    <dl className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
      <Fact label="took" value={`${turn.latency_ms} ms`} />
      <Fact label="model calls" value={String(turn.llm_calls)} />
      <Fact label="tool calls" value={String(turn.tool_calls)} />
      <Fact
        label="cost"
        value={turn.cost.measured ? `$${turn.cost.usd}` : "not priced"}
        title={
          turn.cost.measured
            ? undefined
            : "Recorded as zero. A local model is free, and a cloud model with no configured price also records zero — this figure cannot tell you which."
        }
      />
      {turn.prompt_revision ? <Fact label="prompt" value={turn.prompt_revision} /> : null}
    </dl>
  );
}

function Fact({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="flex gap-1" title={title}>
      <dt>{label}</dt>
      <dd className="text-foreground">{value}</dd>
    </div>
  );
}

function formatWhen(value: string | null): string {
  if (!value) return "";
  const when = new Date(value);
  return Number.isNaN(when.getTime()) ? "" : when.toLocaleString();
}
