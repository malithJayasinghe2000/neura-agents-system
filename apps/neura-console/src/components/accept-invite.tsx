"use client";

/**
 * Use the invite link in the URL (ADR-0058 §4), once.
 *
 * Three outcomes, each said plainly:
 * - **a new person** is signed in by the response, and goes to the shop;
 * - **someone who already has an account** is added, and signs in as usual
 *   (R13): the link must not open their other shops for whoever holds it;
 * - **a link that no longer works**, whatever the reason, gets one message, as
 *   the API gives one answer for all of them.
 *
 * The token is read from the address and never stored. `replace`, not `push`,
 * so the credential does not stay in the back button.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { acceptInvite } from "@/lib/api";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Outcome = { kind: "joined" | "failed"; message: string } | null;

const NOT_VALID = "That invite link is no longer valid. Ask the shop's owner to send it again.";

export function AcceptInvite() {
  const params = useSearchParams();
  const router = useRouter();
  const [outcome, setOutcome] = useState<Outcome>(null);
  // Effects run twice in development; a one-time link used twice fails itself.
  const attempted = useRef(false);

  const shop = params.get("shop");
  const token = params.get("token");

  useEffect(() => {
    if (!shop || !token || attempted.current) return;
    attempted.current = true;

    acceptInvite(shop, token)
      .then((result) => {
        if (result.signed_in && result.tenant_id) {
          router.replace(`/console/${encodeURIComponent(result.tenant_id)}`);
        } else if (result.joined) {
          setOutcome({ kind: "joined", message: result.message ?? "" });
        } else {
          setOutcome({ kind: "failed", message: result.message ?? NOT_VALID });
        }
      })
      .catch(() => setOutcome({ kind: "failed", message: NOT_VALID }));
  }, [shop, token, router]);

  if (shop && token && !outcome) {
    return <p className="text-sm text-muted-foreground">Opening your invite…</p>;
  }

  const joined = outcome?.kind === "joined";
  return (
    <Card className="w-full max-w-sm" data-invite-outcome={outcome?.kind ?? "failed"}>
      <CardHeader className="space-y-4">
        <Brand />
        <div className="space-y-1.5">
          <CardTitle className="text-xl">
            {joined ? "You've joined" : "That link didn't work"}
          </CardTitle>
          <CardDescription>{outcome?.message ?? NOT_VALID}</CardDescription>
        </div>
      </CardHeader>
      {joined ? (
        <CardContent>
          <Button className="h-11 w-full" onClick={() => router.replace("/")}>
            Sign in
          </Button>
        </CardContent>
      ) : null}
    </Card>
  );
}
