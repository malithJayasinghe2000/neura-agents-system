"use client";

/**
 * Use the sign-up link in the URL (ADR-0058 §7), once.
 *
 * The response makes the account and the shop, waiting for approval, and its
 * cookie signs them in; then the shop's own address shows the waiting screen.
 * **Every failure says the same words** (R17 b), as the API gives one answer for
 * used, replaced and old links, with both next steps: someone who already
 * confirmed signs in; anyone else creates their account again.
 *
 * The token is read from the address and never stored. `replace`, not `push`,
 * so the credential does not stay in the back button.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { confirmSignUp } from "@/lib/api";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** The API's words for a link that no longer works. */
const NOT_VALID =
  "Sign-up links expire after 15 minutes and work once. If you already confirmed, sign in. If not, create your account again.";

export function ConfirmSignUp() {
  const params = useSearchParams();
  const router = useRouter();
  const [failed, setFailed] = useState<string | null>(null);
  // Effects run twice in development; a one-time link used twice fails itself.
  const attempted = useRef(false);

  const token = params.get("token");

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;

    confirmSignUp(token)
      .then((result) => {
        if (result.signed_in && result.tenant_id) {
          router.replace(`/console/${encodeURIComponent(result.tenant_id)}`);
        } else {
          setFailed(result.message ?? NOT_VALID);
        }
      })
      .catch(() => setFailed(NOT_VALID));
  }, [token, router]);

  if (token && failed === null) {
    return <p className="text-sm text-muted-foreground">Signing you in…</p>;
  }

  return (
    <Card className="w-full max-w-sm" data-sign-up-failed>
      <CardHeader className="space-y-4">
        <Brand />
        <div className="space-y-1.5">
          <CardTitle className="text-xl">That link didn&apos;t work</CardTitle>
          <CardDescription>{failed ?? NOT_VALID}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button className="h-11 w-full" onClick={() => router.replace("/")}>
          Sign in
        </Button>
        <Button
          variant="outline"
          className="h-11 w-full"
          onClick={() => router.replace("/sign-up")}
        >
          Create an account
        </Button>
      </CardContent>
    </Card>
  );
}
