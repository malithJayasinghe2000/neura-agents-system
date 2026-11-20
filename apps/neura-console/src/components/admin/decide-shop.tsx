"use client";

/**
 * Approve or refuse a waiting shop (ADR-0061 §7, board 47).
 *
 * **The choices are every assistant the API discovered** (G136), so one added
 * later is never missing; their words are `lib/assistants.ts`'s. **CARE is
 * ticked, the others are not** (R14: CARE is the usual start; R46: GROW is chosen
 * per shop, like SELL); at least one must be ticked, and the API refuses none. **Refuse asks first**, because it
 * cannot be undone. When an email could not be sent, the screen says so rather
 * than claiming it was.
 *
 * **The result stays on the screen until the admin leaves it.** The page is not
 * re-read when it appears: re-read, a shop no longer waiting has no decision to
 * show, and the result vanished the moment it was drawn. *Back to Shops* re-reads
 * the list and the menu's waiting count instead.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { approveShop, refuseShop } from "@/lib/api";
import { AssistantChoices } from "@/components/admin/assistant-choices";
import { assistantName, inReadingOrder } from "@/lib/assistants";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** R14: CARE is the usual start, so it alone is ticked at first. */
const USUAL_START: string = "care";

type Step =
  | { kind: "deciding" }
  | { kind: "asking" }
  | { kind: "approved"; assistants: string[]; emailed: boolean }
  | { kind: "refused"; emailed: boolean };

export function DecideShop({
  tenantId,
  name,
  owners,
  offered,
}: {
  tenantId: string;
  name: string;
  owners: string[];
  /** Every assistant the API discovered, as keys. */
  offered: string[];
}) {
  const choices = inReadingOrder(offered);
  const [picked, setPicked] = useState(() => new Set(choices.filter((key) => key === USUAL_START)));
  const [step, setStep] = useState<Step>({ kind: "deciding" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const owner = owners.join(", ") || "its owner";

  async function run(action: () => Promise<Step>) {
    setBusy(true);
    setError("");
    try {
      setStep(await action());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (step.kind === "approved") {
    const named = step.assistants.map(assistantName).join(" and ");
    return (
      <Result tone="good" title={`${name} is approved`}>
        With {named}, in practice mode.{" "}
        {step.emailed ? `We emailed ${owner}.` : `The email to ${owner} could not be sent.`} It is
        in the shop list now, as Practice.
      </Result>
    );
  }
  if (step.kind === "refused") {
    return (
      <Result tone="plain" title={`${name} is refused and removed`}>
        {step.emailed ? `We emailed ${owner}.` : `The email to ${owner} could not be sent.`} They
        keep their account, in case they are in another shop.
      </Result>
    );
  }

  return (
    <div className="space-y-4">
      {step.kind === "asking" ? (
        <section
          role="alertdialog"
          aria-labelledby="refuse-title"
          className="space-y-2.5 rounded-xl border border-red-300 bg-red-50 p-5 dark:border-red-900 dark:bg-red-950/40"
        >
          <h2 id="refuse-title" className="text-lg font-semibold">
            Refuse {name}?
          </h2>
          <p className="text-sm leading-relaxed text-foreground/80">
            It is removed, and {owner} gets an email. This can&apos;t be undone.
          </p>
          <div className="flex flex-wrap gap-3 pt-1">
            <Button
              className="h-11 bg-red-700 px-4 text-white hover:bg-red-800 sm:h-10"
              disabled={busy}
              data-confirm-refuse
              onClick={() =>
                run(async () => {
                  const done = await refuseShop(tenantId);
                  return { kind: "refused", emailed: done.emailed };
                })
              }
            >
              {busy ? "Refusing…" : "Refuse"}
            </Button>
            <Button
              variant="outline"
              className="h-11 px-4 sm:h-10"
              disabled={busy}
              onClick={() => setStep({ kind: "deciding" })}
            >
              Keep waiting
            </Button>
          </div>
        </section>
      ) : (
        <section aria-labelledby="approve-title" className="space-y-4">
          <h2 id="approve-title" className="text-lg font-semibold">
            Approve
          </h2>
          <p className="text-sm text-foreground/80">
            Choose its assistants. CARE is the usual start.
          </p>
          <AssistantChoices choices={choices} picked={picked} onChange={setPicked} />
          <p className="text-sm leading-relaxed text-foreground/80">
            It starts in practice mode, with the daily spending limit every shop has. We email{" "}
            {owner}.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button
              className="h-11 px-5 sm:h-10"
              disabled={busy || picked.size === 0}
              data-approve
              onClick={() =>
                run(async () => {
                  const done = await approveShop(
                    tenantId,
                    choices.filter((key) => picked.has(key)),
                  );
                  return { kind: "approved", assistants: done.assistants, emailed: done.emailed };
                })
              }
            >
              {busy ? "Approving…" : "Approve"}
            </Button>
            <Button
              variant="outline"
              className="h-11 border-red-300 px-5 text-red-700 hover:bg-red-50 hover:text-red-800 sm:h-10 dark:border-red-900 dark:text-red-300"
              disabled={busy}
              data-refuse
              onClick={() => setStep({ kind: "asking" })}
            >
              Refuse
            </Button>
          </div>
        </section>
      )}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function Result({
  tone,
  title,
  children,
}: {
  tone: "good" | "plain";
  title: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  return (
    <section
      className={cn(
        "space-y-1.5 rounded-xl border p-5",
        tone === "good"
          ? "border-green-300 bg-green-50 dark:border-green-900 dark:bg-green-950/40"
          : "bg-muted/40",
      )}
      data-decided
    >
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="text-sm leading-relaxed text-foreground/80">{children}</p>
      <button
        type="button"
        onClick={() => {
          // To the list, then re-read it and the menu's count: the frame does
          // not re-render on its own when a page inside it navigates.
          router.push("/admin");
          router.refresh();
        }}
        className="inline-block pt-1.5 text-sm font-medium underline underline-offset-3"
        data-back-to-shops
      >
        Back to Shops
      </button>
    </section>
  );
}
