"use client";

/**
 * The box at the top of a chat whose handed-over shopper waits for an answer.
 * ADR-0062 §6 and §7, console.md §3.10 (the owner's approved mockup, board 53).
 *
 * **NEURA sends nothing.** *Answer by email* is a `mailto:` link: the team
 * member's own email app opens with the address, the subject and the shopper's
 * question, and they send it from the shop's email (R27). The words come from
 * the server (`…/waiting`), never the AI's unsent draft.
 *
 * **Mark as answered** asks first, because it deletes the shopper's email and
 * cannot be undone; then the page is read again, so the menu's count and the
 * badge follow.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Copy, Mail } from "lucide-react";
import { When } from "@/components/when";
import { Button } from "@/components/ui/button";
import { WAITING_CHANGED, markAnswered } from "@/lib/api";
import type { WaitingDetails, WaitingReach } from "@/lib/conversations";

type Step = "choosing" | "asking" | "saving" | "done";

export function WaitingAnswer({
  tenantId,
  conversationId,
  reach,
  since,
  details,
}: {
  tenantId: string;
  conversationId: string;
  reach: WaitingReach;
  since: string;
  /** `null` when `…/waiting` could not be read: the box still says who waits. */
  details: WaitingDetails | null;
}) {
  const router = useRouter();
  const [step, setStep] = useState<Step>("choosing");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [answeredBy, setAnsweredBy] = useState("");

  const email = details?.email ?? null;
  const typed = reach === "email";

  async function copy() {
    if (!email) return;
    try {
      await navigator.clipboard.writeText(email);
      setCopied(true);
    } catch {
      // A browser that refuses the clipboard: the address is on screen to select.
      setCopied(false);
    }
  }

  async function mark() {
    setStep("saving");
    setError("");
    try {
      const answered = await markAnswered(tenantId, conversationId);
      setAnsweredBy(answered.answered_by?.name ?? "");
      setStep("done");
      window.dispatchEvent(new Event(WAITING_CHANGED));
      router.refresh();
    } catch (failed) {
      setError(failed instanceof Error ? failed.message : "Could not mark it as answered.");
      setStep("asking");
    }
  }

  if (step === "done") {
    return <Answered by={answeredBy} at={null} typed={typed} />;
  }

  return (
    <section
      aria-label="Waiting for an answer"
      data-waiting-box
      className="space-y-3.5 rounded-xl border border-amber-300 bg-amber-50 px-4 py-4 text-amber-950 sm:px-5 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-50"
    >
      <div className="space-y-1">
        <h2 className="text-base font-semibold">This shopper is waiting for an answer</h2>
        <p className="text-sm leading-relaxed">
          {typed
            ? "They left their email after your assistant handed them over, "
            : "They were signed in to your shop when your assistant handed them over, "}
          <When iso={since} inline />.
        </p>
      </div>

      {email ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <span className="font-mono text-[15px] font-medium break-all" data-waiting-email>
            {email}
          </span>
          {typed ? null : (
            <span className="text-sm opacity-80">from your shop&apos;s customer record</span>
          )}
          <Button
            type="button"
            variant="outline"
            className="h-11 w-full bg-background sm:h-8 sm:w-auto"
            onClick={copy}
            data-copy-email
          >
            <Copy aria-hidden />
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      ) : reach === "customer" && details ? (
        <p className="rounded-lg border-[1.5px] border-dashed border-amber-400 px-3.5 py-3 text-sm leading-relaxed">
          Your shop didn&apos;t give us this customer&apos;s email. Find customer{" "}
          <span className="font-mono">{details.customer_id}</span> in your shop&apos;s admin, and
          write to them from there.
        </p>
      ) : null}

      {step === "choosing" ? (
        <>
          <div className="flex flex-col gap-2.5 sm:flex-row">
            {email && details ? (
              <Button
                className="h-11 w-full sm:h-10 sm:w-auto"
                nativeButton={false}
                render={<a href={mailtoFor(email, details.subject, details.body)} />}
                data-answer-by-email
              >
                <Mail aria-hidden />
                Answer by email
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              className="h-11 w-full bg-background sm:h-10 sm:w-auto"
              onClick={() => setStep("asking")}
              data-mark-answered
            >
              <Check aria-hidden />
              Mark as answered
            </Button>
          </div>
          {email ? (
            <p className="text-[13px] leading-relaxed opacity-80">
              {typed
                ? "Answer by email opens your email app with their address and question filled in. Send it from your shop's email. When you have answered, press Mark as answered: their email is deleted then, or after 30 days if nobody answers."
                : "Answer by email opens your email app with their address and question filled in. Send it from your shop's email, then press Mark as answered."}
            </p>
          ) : null}
        </>
      ) : (
        <div className="space-y-2.5 border-t border-amber-300 pt-3.5 dark:border-amber-700">
          <p className="font-semibold">Mark as answered?</p>
          <p className="text-sm leading-relaxed">
            {typed
              ? "We delete the shopper's email, and this chat leaves Waiting for an answer. This can't be undone."
              : "This chat leaves Waiting for an answer. This can't be undone."}
          </p>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <div className="flex flex-col gap-2.5 sm:flex-row">
            <Button
              type="button"
              className="h-11 w-full sm:h-10 sm:w-auto"
              onClick={mark}
              disabled={step === "saving"}
              data-confirm-answered
            >
              Mark as answered
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-11 w-full bg-background sm:h-10 sm:w-auto"
              onClick={() => setStep("choosing")}
              disabled={step === "saving"}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

/** *Answered*: who marked it, and that the address is gone (ADR-0062 §7). */
export function Answered({ by, at, typed }: { by: string; at: string | null; typed: boolean }) {
  return (
    <section
      data-answered
      className="flex items-start gap-3 rounded-xl border border-green-300 bg-green-50 px-4 py-4 text-green-950 sm:px-5 dark:border-green-800 dark:bg-green-950/40 dark:text-green-50"
    >
      <Check className="mt-0.5 size-4.5 shrink-0" aria-hidden />
      <div className="space-y-1">
        <p className="font-semibold">Answered</p>
        <p className="text-sm leading-relaxed">
          {by || "Someone on your team"} marked it, {at ? <When iso={at} inline /> : "just now"}.
          {typed ? " The shopper's email is deleted." : null}
        </p>
      </div>
    </section>
  );
}

/** The team member's own email app, filled in. The address passed the API's
 *  check, so only the subject and body need escaping; `@` stays readable. */
function mailtoFor(email: string, subject: string, body: string): string {
  const to = encodeURIComponent(email).replace(/%40/g, "@");
  return `mailto:${to}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}
