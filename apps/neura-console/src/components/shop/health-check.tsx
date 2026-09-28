"use client";

/**
 * *Check now* on Shop connection — the one request on this screen that reaches
 * the merchant's own server, made only when the owner presses the button.
 *
 * Its answer fills two places on the page — the checklist's *Your shop
 * answers* and *What your shop lets the assistant do* — so it lives in a small
 * context rather than in the URL. That is what lets the rest of the page be
 * re-read (after *Sync now*) without asking the shop again: an address that
 * carried the check would repeat it on every refresh, and **a page load never
 * probes the shop** (console.md §3.4).
 */
import { createContext, useCallback, useContext, useState } from "react";
import { Check, RefreshCw } from "lucide-react";
import { checkShop } from "@/lib/api";
import { allowedWords, type Health } from "@/lib/shop";
import { SetupItem } from "@/components/shop/setup-item";
import { Button } from "@/components/ui/button";

type Answer =
  { state: "asking" } | { state: "answered"; health: Health } | { state: "error"; message: string };

type Checks = {
  answers: Record<string, Answer>;
  check: (storeId: string) => void;
};

const ChecksContext = createContext<Checks | null>(null);

export function HealthChecks({
  tenantId,
  children,
}: {
  tenantId: string;
  children: React.ReactNode;
}) {
  const [answers, setAnswers] = useState<Record<string, Answer>>({});

  const check = useCallback(
    (storeId: string) => {
      setAnswers((was) => ({ ...was, [storeId]: { state: "asking" } }));
      checkShop(tenantId, storeId)
        .then((health) =>
          setAnswers((was) => ({ ...was, [storeId]: { state: "answered", health } })),
        )
        .catch((error: unknown) =>
          setAnswers((was) => ({
            ...was,
            [storeId]: {
              state: "error",
              message: error instanceof Error ? error.message : "The check could not run.",
            },
          })),
        );
    },
    [tenantId],
  );

  return <ChecksContext value={{ answers, check }}>{children}</ChecksContext>;
}

function useAnswer(storeId: string): [Answer | undefined, () => void] {
  const checks = useContext(ChecksContext);
  if (!checks) throw new Error("useAnswer needs <HealthChecks> around it.");
  return [checks.answers[storeId], () => checks.check(storeId)];
}

/** *Your shop answers* — still a button, never a page load. */
export function AnswersItem({ storeId }: { storeId: string }) {
  const [answer, check] = useAnswer(storeId);
  const asking = answer?.state === "asking";

  const button = (
    <Button
      variant="outline"
      className="h-10 sm:h-9"
      disabled={asking}
      onClick={check}
      data-check-now
    >
      {asking ? <RefreshCw className="animate-spin" aria-hidden /> : null}
      {asking ? "Asking your shop…" : answer ? "Check again" : "Check now"}
    </Button>
  );

  if (!answer || answer.state === "asking") {
    return (
      <SetupItem
        item="answers"
        store={storeId}
        state="not-yet"
        title="Your shop answers"
        detail="Not checked yet — this asks your shop right now"
        action={button}
      />
    );
  }
  if (answer.state === "error") {
    return (
      <SetupItem
        item="answers"
        store={storeId}
        state="failed"
        title="The check could not run"
        detail={answer.message}
        action={button}
      />
    );
  }
  if (!answer.health.reachable) {
    return (
      <SetupItem
        item="answers"
        store={storeId}
        state="failed"
        title="Your shop did not answer"
        // The adapter's own words. A friendlier sentence invented here would
        // hide the one detail whoever fixes this needs.
        detail={answer.health.detail || "No detail was returned."}
        action={button}
      />
    );
  }
  return (
    <SetupItem
      item="answers"
      store={storeId}
      state="done"
      title="Your shop answers"
      detail="Answered just now"
      action={button}
    />
  );
}

/** *What your shop lets the assistant do* — the shop's own declaration, in plain words. */
export function AllowedList({ storeId }: { storeId: string }) {
  const [answer] = useAnswer(storeId);

  if (answer?.state !== "answered") {
    return (
      <p className="rounded-xl border border-dashed p-3.5 text-sm text-muted-foreground">
        {answer?.state === "asking" ? (
          "Asking your shop…"
        ) : answer?.state === "error" ? (
          "The check could not run, so this can't be shown yet."
        ) : (
          <>
            Press <strong className="font-semibold text-foreground">Check now</strong> above to ask
            your shop.
          </>
        )}
      </p>
    );
  }
  if (!answer.health.reachable) {
    return (
      <p className="rounded-xl border border-dashed p-3.5 text-sm text-muted-foreground">
        Your shop did not answer just now, so we can&apos;t say what it allows.
      </p>
    );
  }

  const allowed = allowedWords(answer.health.capabilities);
  if (allowed.length === 0) {
    return <p className="text-sm">Your shop declared nothing it allows.</p>;
  }
  return (
    <ul data-allowed className="grid gap-x-4 gap-y-2.5 text-sm sm:grid-cols-2">
      {allowed.map((entry) => (
        <li key={entry.what} className="flex items-start gap-2">
          <Check className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="space-y-0.5">
            <span className="block">{entry.what}</span>
            {entry.note ? (
              <span className="block text-xs text-muted-foreground">{entry.note}</span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
}
