/**
 * What the agent was working from. `docs/console.md §3.2`, and the reason this
 * screen exists rather than a list of replies.
 *
 * > A grader who cannot see what the agent was working from is grading fluency.
 *
 * Two rules hold this component together, and both are about **not showing
 * nothing**:
 *
 * 1. Every citation gets a row, including the ones with no text behind them. A
 *    tool that ran and a policy that has since been deleted are both facts about
 *    what the turn had available; dropping them would leave a merchant believing
 *    the agent worked from less than it did.
 * 2. A row with no text says *why*, in words. This is ADR-0020's lesson pointed
 *    at the merchant instead of the shopper — an empty panel is indistinguishable
 *    from a bug, and it is the one outcome a naive implementation defaults to.
 */
import { FileText, Info, Wrench } from "lucide-react";
import type { Evidence } from "@/lib/review";
import { Badge } from "@/components/ui/badge";

export function EvidencePanel({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) {
    // Not a blank. "The agent cited nothing" is itself a strong signal about a
    // draft — very often the most important one on the card.
    return (
      <div className="rounded-lg border border-dashed px-3 py-2.5 text-sm text-muted-foreground">
        <span className="font-medium text-foreground">Nothing was cited.</span> The agent
        answered without retrieving a document or calling a lookup — so this draft rests on
        the model alone.
      </div>
    );
  }

  return (
    <ul className="space-y-2">
      {evidence.map((piece, index) => (
        <li key={`${piece.type}:${piece.id}:${index}`} className="rounded-lg border">
          <div className="flex items-center gap-2 border-b bg-muted/40 px-3 py-1.5">
            {piece.kind === "tool" ? (
              <Wrench className="size-3.5 text-muted-foreground" aria-hidden />
            ) : (
              <FileText className="size-3.5 text-muted-foreground" aria-hidden />
            )}
            <Badge variant="muted">{piece.type}</Badge>
            <code className="truncate text-xs text-muted-foreground">{piece.id}</code>
          </div>

          {piece.available ? (
            <div className="px-3 py-2.5">
              <pre className="max-h-64 overflow-auto text-sm whitespace-pre-wrap text-foreground/90">
                {piece.excerpt}
              </pre>
              {piece.truncated ? (
                <p className="mt-2 text-xs text-muted-foreground">
                  Shortened for this page — the agent saw the whole source.
                </p>
              ) : null}
              <p className="mt-2 text-xs text-muted-foreground">
                This is the source the reply cited, not the exact passage the search
                returned. The passage isn&apos;t recorded.
              </p>
            </div>
          ) : (
            <p className="flex items-start gap-2 px-3 py-2.5 text-sm text-muted-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {piece.reason}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}
