"use client";

/**
 * *Order questions from signed-in shoppers* on Shop connection. ADR-0057 §3.
 *
 * The owner makes one secret and gives it to their developer. The shop's server
 * signs a short pass with it for each signed-in shopper, so the assistant can
 * answer *"Where is my order?"* for that shopper and nobody else. Built without a
 * mockup, the owner's choice (2026-10-09), in the shop token's pattern: shown
 * **once**, by the response that made it; *Make a new secret* asks first.
 *
 * Unlike the shop token (G49), NEURA checks this secret itself, so a new one
 * really does stop the old one at once, and the words say so.
 */
import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { makeCustomerSecret, type MadeBy } from "@/lib/api";
import { MadeByText } from "@/components/shop/made-by";
import { DEVELOPER_GUIDE_URL } from "@/lib/shop";
import { CopyButton } from "@/components/shop/full-check";
import { When } from "@/components/when";
import { Button } from "@/components/ui/button";

type Phase = "idle" | "asking" | "making" | "made";

export function CustomerSecret({
  tenantId,
  madeAt: initialMadeAt,
  madeBy: initialMadeBy,
}: {
  tenantId: string;
  /** When the secret was made, or `null`. Never the secret. */
  madeAt: string | null;
  /** Who made it (ADR-0058 §6). */
  madeBy?: MadeBy;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [secret, setSecret] = useState<string | null>(null);
  const [madeAt, setMadeAt] = useState<string | null>(initialMadeAt);
  const [madeBy, setMadeBy] = useState<MadeBy | undefined>(initialMadeBy);
  const [replacing, setReplacing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function make() {
    setReplacing(madeAt !== null);
    setPhase("making");
    setError(null);
    makeCustomerSecret(tenantId)
      .then((made) => {
        setSecret(made.secret);
        setMadeAt(made.made_at);
        setMadeBy(made.made_by);
        setPhase("made");
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "The secret could not be made.");
        setPhase(madeAt ? "asking" : "idle");
      });
  }

  return (
    <section
      aria-labelledby="customer-secret"
      data-customer-secret
      className="space-y-3 rounded-2xl border p-4 sm:p-5"
    >
      <h2 id="customer-secret" className="text-lg font-semibold">
        Order questions from signed-in shoppers
      </h2>
      <p className="leading-relaxed text-muted-foreground">
        Your assistant can answer <em>&ldquo;Where is my order?&rdquo;</em> for shoppers who are
        signed in to your shop, and only about their own orders. For this, your developer needs a
        secret from you.
      </p>

      {madeAt === null && phase !== "made" ? (
        <div className="space-y-3">
          <p className="leading-relaxed" data-secret-state="none">
            <strong className="font-semibold">Not set up yet.</strong> Until it is, every shopper
            who asks about an order is asked to sign in, or to contact you.
          </p>
          <Button
            className="h-11 sm:h-10"
            onClick={make}
            disabled={phase === "making"}
            data-make-secret
          >
            {phase === "making" ? <RefreshCw className="animate-spin" aria-hidden /> : null}
            Make the secret
          </Button>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}

      {madeAt !== null && phase !== "made" ? (
        <p className="leading-relaxed text-muted-foreground" data-secret-state="made">
          Made <When iso={madeAt} inline />
          <MadeByText by={madeBy} />. Only your shop and NEURA know it. It is kept locked away and
          can&apos;t be shown again, not even to you.
        </p>
      ) : null}

      {madeAt !== null && phase === "idle" ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
          <Button
            variant="outline"
            className="h-11 sm:h-10"
            onClick={() => setPhase("asking")}
            data-new-secret
          >
            Make a new secret
          </Button>
          <span className="text-sm text-muted-foreground">
            If it may have leaked: a lost laptop, a developer who left.
          </span>
        </div>
      ) : null}

      {madeAt !== null && (phase === "asking" || phase === "making") ? (
        <div data-new-secret-ask className="space-y-3 rounded-xl border border-foreground p-3.5">
          <p className="font-semibold">Make a new secret?</p>
          <p className="text-sm leading-relaxed">
            The old secret stops working at once.{" "}
            <strong className="font-semibold">
              Signed-in shoppers can&apos;t get answers about their orders until your developer puts
              the new one in
            </strong>
            , so tell them straight away.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button
              className="h-11 sm:h-10"
              onClick={make}
              disabled={phase === "making"}
              data-new-secret-confirm
            >
              {phase === "making" ? <RefreshCw className="animate-spin" aria-hidden /> : null}
              Make a new secret
            </Button>
            <Button
              variant="outline"
              className="h-11 sm:h-10"
              onClick={() => setPhase("idle")}
              disabled={phase === "making"}
            >
              Keep the old one
            </Button>
          </div>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}

      {phase === "made" && secret ? (
        <div data-secret-once className="space-y-2.5 rounded-xl border border-foreground p-3.5">
          <p className="text-sm font-semibold">
            {replacing ? "Your new secret." : "Your secret."} Shown once: copy it now.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <code className="min-w-0 flex-1 rounded-lg bg-muted px-3 py-2.5 font-mono text-sm break-all">
              {secret}
            </code>
            <CopyButton text={secret} label="Copy" className="sm:h-auto" />
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Send it to your developer through a password manager or a one-time link, never in a
            plain email. They keep it in your shop&apos;s settings, never in a web page, and follow{" "}
            <a
              href={`${DEVELOPER_GUIDE_URL}#orders`}
              className="font-medium text-foreground underline underline-offset-2"
            >
              Order questions in the developer guide
            </a>
            .
            {replacing ? (
              <>
                {" "}
                <strong className="font-semibold text-foreground">
                  Until they put it in, signed-in shoppers are asked to sign in again.
                </strong>
              </>
            ) : null}
          </p>
        </div>
      ) : null}
    </section>
  );
}
