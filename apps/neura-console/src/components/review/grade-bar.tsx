"use client";

/**
 * The verdict — the one thing on the Review screen that writes anything.
 *
 * Three buttons, and the third is the reason there are not two. `shadow.py`:
 * *"one harmful turn in fifty is not 96% agreement, it is a reason not to
 * launch"* — so *Harmful* is its own verdict and its own colour, and it is never
 * folded into *Not good* to tidy the row up.
 *
 * **How it moves (the owner's approved mockup, 2026-09-27).** *Good* is saved
 * and the next waiting reply opens. *Not good* and *Harmful* are saved at once —
 * a verdict never waits on a note — and then ask *what was wrong?*, because the
 * note is what makes a disagreement fixable; the next reply opens when the owner
 * says so. On the *Already graded* tab nothing moves on: a grade there is being
 * changed, deliberately, and the page stays put to show it changed.
 *
 * **A grade can be changed.** The repository allows it on purpose: telling a
 * reviewer their mis-click is permanent is how a queue gets graded carelessly.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Check, X } from "lucide-react";
import { toast } from "sonner";
import { gradeTurn } from "@/lib/api";
import { HARMFUL_MEANS, VERDICT_BADGES, VERDICT_LABELS, type Verdict } from "@/lib/review";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const ICONS: Record<Verdict, typeof Check> = {
  agree: Check,
  disagree: X,
  would_have_harmed: AlertTriangle,
};

export function GradeBar({
  tenantId,
  turnId,
  verdict,
  note,
  nextHref,
}: {
  tenantId: string;
  turnId: string;
  verdict: Verdict | null;
  note: string;
  /** Where to go once this one is graded. `null` on the graded tab — stay here. */
  nextHref: string | null;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [chosen, setChosen] = useState<Verdict | null>(verdict);
  const [asking, setAsking] = useState(false);
  const [draftNote, setDraftNote] = useState(note);

  function done(message: string) {
    toast.success(message);
    if (nextHref) router.push(nextHref);
    // The badge in the side menu and the tab counts live outside this page.
    router.refresh();
  }

  function pick(next: Verdict) {
    const was = chosen;
    setChosen(next);
    startTransition(async () => {
      try {
        await gradeTurn(tenantId, turnId, next, draftNote);
        if (next === "agree") {
          done(nextHref ? "Saved as Good — here is the next one." : "Saved as Good.");
        } else {
          setAsking(true);
          if (!nextHref) router.refresh();
        }
      } catch (error) {
        setChosen(was);
        toast.error(error instanceof Error ? error.message : "That grade was not saved.");
      }
    });
  }

  function saveNote() {
    if (!chosen) return;
    startTransition(async () => {
      try {
        await gradeTurn(tenantId, turnId, chosen, draftNote);
        done(
          nextHref ? `Saved as ${VERDICT_BADGES[chosen]} — here is the next one.` : "Note saved.",
        );
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "That note was not saved.");
      }
    });
  }

  return (
    <div className="sticky bottom-0 -mx-5 space-y-3 border-t bg-background px-5 py-4 sm:-mx-6 sm:px-6 lg:static lg:mx-0 lg:border-t lg:bg-transparent lg:px-0 lg:pb-0">
      <p className="font-semibold">Would you have sent this?</p>
      <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
        {(["agree", "disagree", "would_have_harmed"] as Verdict[]).map((option) => {
          const Icon = ICONS[option];
          const on = chosen === option;
          return (
            <Button
              key={option}
              type="button"
              variant="outline"
              disabled={pending}
              aria-pressed={on}
              onClick={() => pick(option)}
              className={cn(
                "h-11 gap-2 px-4 text-sm",
                option === "agree" && "col-span-2",
                on &&
                  option === "agree" &&
                  "border-foreground bg-foreground text-background hover:bg-foreground/90 hover:text-background",
                on &&
                  option === "disagree" &&
                  "border-neutral-700 bg-neutral-700 text-white hover:bg-neutral-700/90 hover:text-white",
                option === "would_have_harmed" &&
                  (on
                    ? "border-red-700 bg-red-700 text-white hover:bg-red-700/90 hover:text-white"
                    : "border-red-700/40 text-red-700 hover:bg-red-50 hover:text-red-800 dark:text-red-400"),
              )}
            >
              <Icon aria-hidden />
              {VERDICT_LABELS[option]}
            </Button>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">{HARMFUL_MEANS}</p>

      {asking ? (
        <div className="space-y-2 rounded-lg border bg-muted/30 p-3">
          <label className="block space-y-1.5 text-sm font-medium">
            <span>What was wrong? (optional — it&apos;s how we fix it)</span>
            <Textarea
              value={draftNote}
              onChange={(event) => setDraftNote(event.target.value)}
              maxLength={2000}
              rows={2}
              autoFocus
              className="font-normal"
            />
          </label>
          <Button type="button" disabled={pending} onClick={saveNote} className="h-10 px-4">
            {nextHref ? "Save and open the next one" : "Save note"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
