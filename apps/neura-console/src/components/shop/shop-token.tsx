"use client";

/**
 * *Your shop token* on a connected shop — ADR-0052 §2, canvas board 34.
 *
 * **Make a new token** is for a token that may have leaked. It asks first, and
 * says what really happens (G49): NEURA stops sending the old token at once, but
 * the shop's bridge still accepts it until the developer puts the new one in,
 * because the bridge, not NEURA, checks it. It must never say the old one
 * *"stops working"*.
 *
 * The new token is shown **once**, in this visit, by the response that made it.
 */
import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { replaceShopToken, type MadeBy } from "@/lib/api";
import { MadeByText } from "@/components/shop/made-by";
import { CopyButton } from "@/components/shop/full-check";
import { When } from "@/components/when";
import { Button } from "@/components/ui/button";

type Phase = "idle" | "asking" | "making" | "made";

export function ShopToken({
  tenantId,
  storeId,
  setAt,
  setBy,
  named,
}: {
  tenantId: string;
  storeId: string;
  /** When the token was last set. Never the token. */
  setAt: string | null;
  /** Who made it (ADR-0058 §6). */
  setBy?: MadeBy;
  /** The connection's host, when the shop has more than one. */
  named: string | null;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [token, setToken] = useState<string | null>(null);
  const [madeAt, setMadeAt] = useState<string | null>(setAt);
  const [madeBy, setMadeBy] = useState<MadeBy | undefined>(setBy);
  const [error, setError] = useState<string | null>(null);

  function make() {
    setPhase("making");
    setError(null);
    replaceShopToken(tenantId, storeId)
      .then((made) => {
        setToken(made.token);
        setMadeAt(made.made_at);
        setMadeBy(made.made_by);
        setPhase("made");
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "The token could not be made.");
        setPhase("asking");
      });
  }

  return (
    <section
      aria-label={named ? `Shop token for ${named}` : "Your shop token"}
      data-store={storeId}
      data-shop-token
      className="space-y-3 rounded-2xl border p-4 sm:p-5"
    >
      <h2 className="text-lg font-semibold">
        Your shop token
        {named ? <span className="font-normal text-muted-foreground"> · {named}</span> : null}
      </h2>
      <p className="leading-relaxed text-muted-foreground">
        {madeAt ? (
          <>
            Set <When iso={madeAt} inline />
            <MadeByText by={madeBy} />.{" "}
          </>
        ) : null}
        Only your shop and NEURA know it. It is kept locked away and can&apos;t be shown again, not
        even to you.
      </p>

      {phase === "idle" ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
          <Button
            variant="outline"
            className="h-11 sm:h-10"
            onClick={() => setPhase("asking")}
            data-new-token
          >
            Make a new token
          </Button>
          <span className="text-sm text-muted-foreground">
            If it may have leaked: a lost laptop, a developer who left.
          </span>
        </div>
      ) : null}

      {phase === "asking" || phase === "making" ? (
        <div className="space-y-3 rounded-xl border border-foreground p-3.5">
          <p className="font-semibold">Make a new token?</p>
          <p className="text-sm leading-relaxed">
            NEURA stops using the old token at once.{" "}
            <strong className="font-semibold">
              Your shop still accepts the old one until your developer puts the new one in
            </strong>
            , so tell them straight away. Until then, your assistant can&apos;t read your shop.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button
              className="h-11 sm:h-10"
              onClick={make}
              disabled={phase === "making"}
              data-new-token-confirm
            >
              {phase === "making" ? <RefreshCw className="animate-spin" aria-hidden /> : null}
              Make a new token
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

      {phase === "made" && token ? (
        <div data-token-once className="space-y-2.5 rounded-xl border border-foreground p-3.5">
          <p className="text-sm font-semibold">Your new shop token. Shown once: copy it now.</p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <code className="min-w-0 flex-1 rounded-lg bg-muted px-3 py-2.5 font-mono text-sm break-all">
              {token}
            </code>
            <CopyButton text={token} label="Copy" className="sm:h-auto" />
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Send it to your developer through a password manager or a one-time link, and ask them to
            put it in the bridge&apos;s settings now.{" "}
            <strong className="font-semibold text-foreground">
              Until they do, your shop still accepts the old token
            </strong>{" "}
            and your assistant can&apos;t read your shop. Then press Check again above.
          </p>
        </div>
      ) : null}
    </section>
  );
}
