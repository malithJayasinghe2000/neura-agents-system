"use client";

/**
 * The verdict, and the only thing on this screen that writes anything.
 *
 * Three buttons, and the third is the reason there are not two. `shadow.py`:
 * *"one harmful turn in fifty is not 96% agreement, it is a reason not to
 * launch"* — so `would_have_harmed` is its own verdict and its own colour, and
 * it is never folded into "disagree" to tidy the row up.
 *
 * **A grade can be changed.** The repository allows it deliberately: telling a
 * reviewer their mis-click is permanent is how a queue gets graded carelessly.
 * So an already-graded turn shows its verdict *selected* rather than locked.
 */

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { gradeTurn } from "@/lib/api";
import { VERDICT_HELP, VERDICT_LABELS, type Verdict } from "@/lib/review";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

const ORDER: Verdict[] = ["agree", "disagree", "would_have_harmed"];

export function GradeForm({
  tenantId,
  turnId,
  verdict,
  note,
}: {
  tenantId: string;
  turnId: string;
  verdict: Verdict | null;
  note: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [draftNote, setDraftNote] = useState(note);
  const [chosen, setChosen] = useState<Verdict | null>(verdict);

  function submit(next: Verdict) {
    // Optimistic only in the button's appearance. The list is re-read from the
    // server below, so what a merchant ends up looking at is what was stored,
    // not what this component hoped was stored.
    setChosen(next);
    startTransition(async () => {
      try {
        await gradeTurn(tenantId, turnId, next, draftNote);
        router.refresh();
      } catch (error) {
        setChosen(verdict);
        toast.error(error instanceof Error ? error.message : "That grade was not saved.");
      }
    });
  }

  return (
    <div className="space-y-3">
      <Textarea
        value={draftNote}
        onChange={(event) => setDraftNote(event.target.value)}
        maxLength={2000}
        rows={2}
        placeholder="Why? (optional — but the note is what makes a disagreement fixable)"
        aria-label="Note about this turn"
      />

      <div className="flex flex-wrap gap-2">
        {ORDER.map((option) => (
          <Button
            key={option}
            size="sm"
            variant={
              chosen === option
                ? option === "would_have_harmed"
                  ? "destructive"
                  : "default"
                : "outline"
            }
            disabled={pending}
            title={VERDICT_HELP[option]}
            onClick={() => submit(option)}
          >
            {VERDICT_LABELS[option]}
          </Button>
        ))}
      </div>

      {chosen ? <p className="text-xs text-muted-foreground">{VERDICT_HELP[chosen]}</p> : null}
    </div>
  );
}
