"use client";

/**
 * The owner's choice before a plan is written (ADR-0078 §2, D21): the AI's
 * suggestion, then **Use these products**, **Choose other products**, **A
 * greeting only** or **Skip this date**. Only products or a greeting write the
 * plan, at once; the page then reads itself again and shows it being made.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { choosePlan } from "@/lib/api";
import type { PlanChoice } from "@/lib/calendar";
import { ChangeProducts } from "@/components/calendar/change-products";
import { Button } from "@/components/ui/button";

export function ChoosePlan({
  tenantId,
  planId,
  suggested,
  greetingFirst,
  canSkip,
}: {
  tenantId: string;
  planId: string;
  /** The AI's products, in its order; empty when it suggests a greeting. */
  suggested: PlanChoice[];
  /** The AI suggests a greeting: it is the first button. */
  greetingFirst: boolean;
  /** *Skip this date*: not once the date is skipped or a chosen plan failed. */
  canSkip: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function answer(choice: "products" | "greeting" | "skip") {
    setBusy(choice);
    setError("");
    try {
      await choosePlan(
        tenantId,
        planId,
        choice === "products"
          ? { choice, product_ids: suggested.map((product) => product.product_id) }
          : { choice },
      );
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy("");
    }
  }

  const greeting = (
    <Button
      key="greeting"
      variant={greetingFirst ? "default" : "outline"}
      className="h-11 px-4 sm:h-10"
      disabled={busy !== ""}
      data-choose-greeting
      onClick={() => answer("greeting")}
    >
      {busy === "greeting" ? "Asking…" : "A greeting only"}
    </Button>
  );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start gap-2">
        {suggested.length && !greetingFirst ? (
          <Button
            className="h-11 px-4 sm:h-10"
            disabled={busy !== ""}
            data-choose-suggested
            onClick={() => answer("products")}
          >
            {busy === "products"
              ? "Asking…"
              : suggested.length === 1
                ? "Use this product"
                : "Use these products"}
          </Button>
        ) : null}
        {greetingFirst ? greeting : null}
        <ChangeProducts
          tenantId={tenantId}
          planId={planId}
          current={suggested}
          edited={false}
          choose
        />
        {greetingFirst ? null : greeting}
        {canSkip ? (
          <Button
            variant="ghost"
            className="h-11 px-4 text-muted-foreground sm:h-10"
            disabled={busy !== ""}
            data-choose-skip
            onClick={() => answer("skip")}
          >
            {busy === "skip" ? "Asking…" : "Skip this date"}
          </Button>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
