/**
 * One held-back reply, opened for grading.
 *
 * The rules of `docs/console.md §3.2`, as this card keeps them:
 *
 * 1. **The evidence is in front of the grader.** *What it looked at* sits
 *    between the question and the buttons — the documents' own words, the
 *    lookups by name — so nobody grades a reply without seeing what it was
 *    working from. A grader who has to ask for it grades fluency (E7).
 * 2. **A reply that is not there says why.** An escalation, a failed check or a
 *    blocked turn has no draft, and the server's reason is shown instead of an
 *    empty box (ADR-0020).
 * 3. **No number that was not measured.** Cost is *not priced* rather than
 *    `$0`, and it lives under *Details* with the other figures a shop owner
 *    rarely needs: time, model calls, the prompt's version.
 *
 * Plain words over our words (the owner's mockup): "Fact check" for `verify`,
 * "looked up order status" for `get_order_status`.
 */
import { MessageSquare } from "lucide-react";
import { TokenNote, hasToken } from "@/components/shop/token-note";
import { When } from "@/components/when";
import { assistantName } from "@/lib/assistants";
import type { TranscriptMessage } from "@/lib/conversations";
import {
  OUTCOME_LABELS,
  VERDICT_BADGES,
  consulted,
  documentKind,
  type ReviewTurn,
} from "@/lib/review";
import { cn } from "@/lib/utils";

export function ReplyDetail({
  turn,
  earlier,
  viewerId,
  position,
  children,
}: {
  turn: ReviewTurn;
  /** What was said in the same chat before this question, oldest first. */
  earlier: TranscriptMessage[];
  viewerId: string | undefined;
  /** "2 of 6", when it can be said truthfully. */
  position?: string;
  /** The grade buttons. */
  children: React.ReactNode;
}) {
  const documents = turn.evidence.filter((piece) => piece.kind === "document");
  const lookupNote = turn.evidence.find((piece) => piece.kind === "tool")?.reason ?? "";
  const tokenised = hasToken(turn.question.text, turn.draft, ...earlier.map((m) => m.content));

  return (
    <article className="space-y-6 rounded-xl border p-5 sm:p-6">
      <header className="space-y-2">
        <p className="flex items-center justify-between text-sm text-muted-foreground">
          <span>The shopper asked</span>
          {position ? <span>{position}</span> : null}
        </p>
        <h2 className="text-xl font-semibold tracking-tight">
          {turn.question.recorded ? (
            `“${turn.question.text}”`
          ) : (
            // Kept honest after the transcript is gone (retention deletes chats;
            // the graded reply stays).
            <span className="text-muted-foreground italic">
              The shopper&apos;s question is no longer stored
            </span>
          )}
        </h2>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
          <span>{assistantName(turn.agent)}</span>
          <span aria-hidden>·</span>
          <When iso={turn.created_at} />
          <span
            className={cn(
              "inline-flex h-6 items-center rounded-md px-2 text-xs font-medium",
              turn.escalated ? "bg-foreground text-background" : "bg-muted text-foreground",
            )}
          >
            {OUTCOME_LABELS[turn.state] ?? turn.state}
          </span>
        </div>
      </header>

      {earlier.length > 0 ? (
        <section className="space-y-2 rounded-lg border bg-muted/30 p-3 sm:p-4">
          <h3 className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <MessageSquare className="size-3.5" aria-hidden />
            Earlier in this chat
          </h3>
          <ol className="space-y-1.5 text-sm">
            {earlier.map((message) => (
              <li key={message.id}>
                <span className="font-medium">
                  {message.role === "shopper" ? "Shopper" : "Assistant"}:
                </span>{" "}
                {message.content}
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section className="space-y-2">
        <h3 className="text-sm text-muted-foreground">What it looked at</h3>
        <p className="text-sm">{lookedAt(turn, documents.length)}</p>
        {documents.length > 0 ? (
          <ul className="space-y-2">
            {documents.map((piece, index) => {
              // "Product: Waxed Cotton…" already says what it is; a label above
              // it saying "Product" again is noise.
              const kind = documentKind(piece.type);
              const saysItself = piece.excerpt.startsWith(`${kind}:`);
              return (
                <li
                  key={`${piece.type}:${piece.id}:${index}`}
                  className="rounded-lg border px-3 py-2 text-sm"
                >
                  {saysItself ? null : (
                    <span className="text-xs font-medium text-muted-foreground">{kind}</span>
                  )}
                  {piece.available ? (
                    <p className="line-clamp-4 whitespace-pre-line">
                      {piece.excerpt}
                      {piece.truncated ? "…" : ""}
                    </p>
                  ) : (
                    <p className="text-muted-foreground">{piece.reason}</p>
                  )}
                </li>
              );
            })}
          </ul>
        ) : null}
        {turn.tools.length > 0 && lookupNote ? (
          <p className="text-xs text-muted-foreground">{lookupNote}</p>
        ) : null}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm text-muted-foreground">The reply it wrote</h3>
        {turn.draft.trim() ? (
          <div className="rounded-lg bg-muted px-4 py-3 leading-relaxed whitespace-pre-line">
            {turn.draft}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed px-4 py-3 text-sm">
            {turn.no_draft_reason ||
              // ADR-0020: an empty reply with no reason is an error, not a blank.
              "No reply was recorded, and no reason was given — this is a fault worth reporting."}
          </div>
        )}
        <FactCheck turn={turn} />
      </section>

      {tokenised ? <TokenNote /> : null}

      {turn.verdict ? (
        <p className="text-sm text-muted-foreground">
          Graded <span className="font-medium text-foreground">{VERDICT_BADGES[turn.verdict]}</span>
          {turn.reviewed_by
            ? turn.reviewed_by === viewerId
              ? " by you"
              : " by another person"
            : ""}
          {turn.reviewed_at ? (
            <>
              {" · "}
              <When iso={turn.reviewed_at} />
            </>
          ) : null}
          {turn.note ? <> · “{turn.note}”</> : null}. You can change it.
        </p>
      ) : null}

      {children}

      <details className="group text-sm text-muted-foreground">
        <summary className="cursor-pointer select-none hover:text-foreground">Details</summary>
        <p className="pt-2">
          Took {(turn.latency_ms / 1000).toFixed(1)} s · {plural(turn.llm_calls, "model call")} ·{" "}
          {plural(turn.tool_calls, "lookup")} · cost{" "}
          {turn.cost.measured ? `$${turn.cost.usd}` : "not priced"}
          {turn.intent ? ` · type: ${turn.intent.replaceAll("_", " ")}` : ""}
          {turn.prompt_revision ? ` · prompt ${turn.prompt_revision.slice(0, 12)}` : ""}
        </p>
      </details>
    </article>
  );
}

function FactCheck({ turn }: { turn: ReviewTurn }) {
  const { grounded, reason } = turn.verify;
  if (grounded === false) {
    return (
      <p className="text-sm font-medium text-red-700 dark:text-red-400">
        Fact check: failed{reason ? ` — ${reason}` : ""}
      </p>
    );
  }
  return (
    <p className="text-sm text-muted-foreground">
      {grounded === true
        ? `Fact check: passed${reason ? ` — ${reason}` : ""}`
        : `Fact check: not run${turn.escalated ? " — it handed the chat over instead of answering" : ""}`}
    </p>
  );
}

/** One sentence: what the assistant consulted before writing, or that it consulted nothing. */
function lookedAt(turn: ReviewTurn, documents: number): string {
  const said = consulted(turn.tools, documents);
  if (said) return said;

  if (turn.escalated) return "Nothing — it handed the chat to a person instead of answering.";
  if (turn.state === "blocked")
    return "Nothing — the guard stopped this before your assistant did any work.";
  return "Nothing from your shop — this reply rests on the assistant alone.";
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}
