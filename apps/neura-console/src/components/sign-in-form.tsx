"use client";

/**
 * Ask for a sign-in link. ADR-0026.
 *
 * **The confirmation screen is deliberately vague, and it must stay that way.**
 * It says the same thing whether or not the address has an account, because the
 * API says the same thing — "no account with that email" would let anyone walk a
 * list of shop owners' addresses and learn which merchants use us, which is a
 * customer list and a target list in one. A future change that makes this screen
 * more helpful re-opens that hole.
 *
 * It also means this screen **cannot report a delivery failure**. If mail is not
 * arriving, the answer is in the API's logs (`sign_in_mail_not_delivered`) or
 * `make user-link`, never here.
 */

import { useState } from "react";
import { requestSignInLink } from "@/lib/api";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type State = "idle" | "sending" | "sent" | "error";

export function SignInForm() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState("");

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setState("sending");
    setError("");
    try {
      await requestSignInLink(email.trim());
      setState("sent");
    } catch (caught) {
      // Only a transport or validation failure reaches here. An unknown address
      // is a success as far as this screen is concerned, on purpose.
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
      setState("error");
    }
  }

  if (state === "sent") {
    return (
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-4">
          <Brand />
          <div className="space-y-1.5">
            <CardTitle className="text-xl">Check your email</CardTitle>
            <CardDescription>
              If <span className="font-medium text-foreground">{email}</span> has an account, a
              sign-in link is on its way. It works once and expires in 15 minutes.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <Button
            variant="outline"
            className="w-full"
            onClick={() => {
              setState("idle");
              setEmail("");
            }}
          >
            Use a different address
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="space-y-4">
        <Brand />
        <div className="space-y-1.5">
          <CardTitle className="text-xl">Sign in</CardTitle>
          <CardDescription>We&apos;ll email you a link. No password to remember.</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="email">Email address</Label>
            <Input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              autoFocus
              required
              placeholder="you@yourshop.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={state === "sending"}
              aria-describedby={error ? "sign-in-error" : undefined}
              aria-invalid={state === "error" || undefined}
            />
          </div>

          {error ? (
            <p id="sign-in-error" role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}

          <Button type="submit" className="w-full" disabled={state === "sending" || !email.trim()}>
            {state === "sending" ? "Sending…" : "Email me a link"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
