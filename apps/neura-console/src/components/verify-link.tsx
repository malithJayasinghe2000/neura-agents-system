"use client";

/**
 * Redeem the one-time token from the URL. ADR-0026.
 *
 * **Every failure shows the same message**, matching the API: unknown, expired,
 * already used and malformed are one outcome to the person holding the link.
 * Distinguishing them would tell whoever found a stolen link whether it ever
 * worked.
 *
 * The token is read from the query string and never stored, never logged, and
 * never put anywhere it could persist — it is a live credential until redeemed.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { verifySignInToken } from "@/lib/api";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function VerifyLink() {
  const params = useSearchParams();
  const router = useRouter();
  const [failed, setFailed] = useState(false);
  // React runs effects twice in development. A one-time token redeemed twice
  // consumes itself and reports failure to a person who did nothing wrong —
  // exactly the single-use guarantee working correctly against us.
  const attempted = useRef(false);

  // Derived during render, not set from the effect. A link with no token at all
  // is a fact about the URL, knowable immediately; routing it through state
  // would render "signing you in…" for a request that was never going to happen.
  const token = params.get("token");

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;

    verifySignInToken(token)
      .then((result) => {
        if (result.signed_in) {
          // `replace`, not `push`: the token is in the current URL, and leaving
          // it in history puts a credential in the back button and in whatever
          // syncs that history between devices.
          router.replace("/console");
        } else {
          setFailed(true);
        }
      })
      .catch(() => setFailed(true));
  }, [token, router]);

  if (token && !failed) {
    return <p className="text-sm text-muted-foreground">Signing you in…</p>;
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="space-y-4">
        <Brand />
        <div className="space-y-1.5">
          <CardTitle className="text-xl">That link didn&apos;t work</CardTitle>
          <CardDescription>
            Sign-in links expire after 15 minutes and can only be used once.
            Ask for a fresh one and it&apos;ll work.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <Button className="w-full" onClick={() => router.replace("/")}>
          Get a new link
        </Button>
      </CardContent>
    </Card>
  );
}
