"use client";

/**
 * Create an account (ADR-0058 §7, console.md §3.8 board 43).
 *
 * **The confirmation says the same words for every email**, as the API does:
 * every email gets a link (R15: someone with an account may add a shop), so
 * *"A link is on its way"* is true for all of them, and the screen says nothing
 * about who already has an account. A future change that makes it more helpful
 * re-opens that hole.
 *
 * Nothing is made until the link is clicked. Mistakes in the form (a website
 * that is not one) come back from the API in plain words and are shown here.
 */

import Link from "next/link";
import { useState } from "react";
import { requestSignUp } from "@/lib/api";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type State = "idle" | "sending" | "sent" | "error";

export function SignUpForm() {
  const [email, setEmail] = useState("");
  const [shopName, setShopName] = useState("");
  const [website, setWebsite] = useState("");
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState("");

  const ready = Boolean(email.trim() && shopName.trim() && website.trim());

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setState("sending");
    setError("");
    try {
      await requestSignUp(email.trim(), shopName.trim(), website.trim());
      setState("sent");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
      setState("error");
    }
  }

  return (
    <div className="flex w-full max-w-sm flex-col items-center gap-4">
      {state === "sent" ? (
        <Card className="w-full" data-sign-up-sent>
          <CardHeader className="space-y-4">
            <Brand />
            <div className="space-y-1.5">
              <CardTitle className="text-xl">Check your email</CardTitle>
              <CardDescription>
                A link is on its way to{" "}
                <span className="font-medium break-words text-foreground">{email}</span>. It works
                once and expires in 15 minutes.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <Button
              variant="outline"
              className="h-10 w-full"
              onClick={() => {
                setState("idle");
                setEmail("");
              }}
            >
              Use a different address
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card className="w-full">
          <CardHeader className="space-y-4">
            <Brand />
            <div className="space-y-1.5">
              <CardTitle className="text-xl">Create an account</CardTitle>
              <CardDescription>
                Tell us about your shop. We&apos;ll email you a link to confirm. No password to
                remember.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-4" noValidate>
              <div className="space-y-2">
                <Label htmlFor="email">Your email address</Label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  autoFocus
                  required
                  className="h-10"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  disabled={state === "sending"}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="shop-name">Your shop&apos;s name</Label>
                <Input
                  id="shop-name"
                  name="shop_name"
                  type="text"
                  autoComplete="organization"
                  required
                  maxLength={100}
                  className="h-10"
                  value={shopName}
                  onChange={(event) => setShopName(event.target.value)}
                  disabled={state === "sending"}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="website">Your shop&apos;s website</Label>
                {/* Text, not `url`: a website typed without https:// is fine (R17 d). */}
                <Input
                  id="website"
                  name="website"
                  type="text"
                  inputMode="url"
                  autoComplete="url"
                  autoCapitalize="none"
                  spellCheck={false}
                  required
                  placeholder="yourshop.com"
                  className="h-10"
                  value={website}
                  onChange={(event) => setWebsite(event.target.value)}
                  disabled={state === "sending"}
                  aria-describedby={error ? "sign-up-error" : undefined}
                />
              </div>

              {error ? (
                <p id="sign-up-error" role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              ) : null}

              <Button
                type="submit"
                className="h-10 w-full"
                disabled={state === "sending" || !ready}
              >
                {state === "sending" ? "Sending…" : "Create my account"}
              </Button>
              <p className="text-[13px] leading-normal text-muted-foreground">
                FiveNeurals looks at every new shop before its assistant starts.
              </p>
            </form>
          </CardContent>
        </Card>
      )}
      <p className="text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/" className="font-medium text-foreground underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </div>
  );
}
