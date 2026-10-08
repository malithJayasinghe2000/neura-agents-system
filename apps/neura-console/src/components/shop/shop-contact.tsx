"use client";

/**
 * *Your shop's contact details* on Shop connection (ADR-0055, G44).
 *
 * When the assistant cannot help a shopper, it tells them to contact the store
 * with these, and promises no person. Both are optional; an empty field clears
 * one. The sentence under the form is the **server's**, returned with the
 * details, so this screen never shows a copy that could drift from what a
 * shopper reads.
 */
import { useState } from "react";
import { Check, RefreshCw } from "lucide-react";
import { saveContact, type ShopContactView } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ShopContact({
  tenantId,
  initial,
}: {
  tenantId: string;
  /** `null`: the details could not be read just now. */
  initial: ShopContactView | null;
}) {
  const [email, setEmail] = useState(initial?.email ?? "");
  const [phone, setPhone] = useState(initial?.phone ?? "");
  const [shown, setShown] = useState(initial);
  const [phase, setPhase] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);

  function save(event: React.FormEvent) {
    event.preventDefault();
    setPhase("saving");
    setError(null);
    saveContact(tenantId, { email, phone })
      .then((saved) => {
        setShown(saved);
        setEmail(saved.email ?? "");
        setPhone(saved.phone ?? "");
        setPhase("saved");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
        setPhase("idle");
      });
  }

  return (
    <section aria-labelledby="contact" className="space-y-4 rounded-2xl border p-4 sm:p-5">
      <div className="space-y-1">
        <h2 id="contact" className="text-lg font-semibold">
          Your shop&apos;s contact details
        </h2>
        <p className="text-sm leading-relaxed text-muted-foreground">
          When your assistant can&apos;t help a shopper, it tells them to contact your store with
          these. Both are optional.
        </p>
      </div>

      {initial === null ? (
        <p role="alert" className="text-sm text-destructive">
          Your contact details couldn&apos;t be loaded just now.
        </p>
      ) : (
        // `noValidate`: the server's check says what is wrong in our words; the
        // browser's own popup would say it first, differently, in its language.
        <form onSubmit={save} noValidate className="space-y-4" data-contact-form>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="contact-email">Email</Label>
              <Input
                id="contact-email"
                name="email"
                type="email"
                autoComplete="email"
                placeholder="hello@yourshop.com"
                className="h-11 sm:h-10"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setPhase("idle");
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="contact-phone">Phone</Label>
              <Input
                id="contact-phone"
                name="phone"
                type="tel"
                autoComplete="tel"
                placeholder="+94 11 234 5678"
                className="h-11 sm:h-10"
                value={phone}
                onChange={(event) => {
                  setPhone(event.target.value);
                  setPhase("idle");
                }}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="submit"
              className="h-11 w-full sm:h-10 sm:w-auto"
              disabled={phase === "saving"}
              data-save-contact
            >
              {phase === "saving" ? <RefreshCw className="animate-spin" aria-hidden /> : null}
              Save
            </Button>
            {phase === "saved" ? (
              <span role="status" className="inline-flex items-center gap-1.5 text-sm">
                <Check className="size-4" aria-hidden /> Saved
              </span>
            ) : null}
          </div>
          {error ? (
            <p role="alert" className="text-sm text-destructive" data-contact-error>
              {error}
            </p>
          ) : null}
          {shown ? (
            <div className="space-y-1 rounded-xl bg-muted/50 px-3.5 py-3">
              <p className="text-xs font-medium text-muted-foreground">
                What a shopper reads when your assistant can&apos;t help
              </p>
              <p className="text-sm leading-relaxed" data-handover>
                {shown.handover}
              </p>
            </div>
          ) : null}
        </form>
      )}
    </section>
  );
}
