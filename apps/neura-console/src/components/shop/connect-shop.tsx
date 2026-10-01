"use client";

/**
 * *Connect your shop* — ADR-0052, the owner's approved mockup (canvas row 10,
 * boards 31-35). Replaces *"No shop connected yet"*, which said FiveNeurals
 * connects it.
 *
 * Three steps, each saying who does it:
 *
 * 1. **You** make the shop token. NEURA makes it and shows it **once**, here,
 *    in the response that made it: after a reload the page only knows *when* it
 *    was made. The browser never sends a token anywhere.
 * 2. **Your developer** builds the bridge and puts the token in it.
 * 3. **You** type the bridge's address and press **Check**, which runs the full
 *    check in the background (see `full-check.tsx`). **Connect** is allowed only
 *    after a clean check of that same address, made after the token.
 *
 * A problem is said in one sentence first (G48); the full list is for the
 * developer, behind *Copy the full check*.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, CheckCircle2, RefreshCw, XCircle } from "lucide-react";
import Link from "next/link";
import { connectShop, makeShopToken } from "@/lib/api";
import { CopyButton, useShopCheck } from "@/components/shop/full-check";
import { When } from "@/components/when";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  DEVELOPER_GUIDE_URL,
  PASSED_WORDS,
  checkWords,
  type ShopCheck,
  type ShopView,
} from "@/lib/shop";
import { cn } from "@/lib/utils";

/** The address as the server keeps it: trimmed, no trailing slash. */
function tidy(address: string): string {
  return address.trim().replace(/\/+$/, "");
}

export function ConnectShop({
  tenantId,
  initial,
}: {
  tenantId: string;
  initial: NonNullable<ShopView["connect"]>;
}) {
  const router = useRouter();
  const [refreshing, startTransition] = useTransition();

  const [madeAt, setMadeAt] = useState<string | null>(initial.token_made_at);
  /** Shown once: only in the visit that made it, never read back. */
  const [token, setToken] = useState<string | null>(null);
  const [making, setMaking] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);

  const [address, setAddress] = useState(initial.last_check?.address ?? "");
  const check = useShopCheck(tenantId, initial.last_check);

  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  function make() {
    setMaking(true);
    setTokenError(null);
    makeShopToken(tenantId)
      .then((made) => {
        setToken(made.token);
        setMadeAt(made.made_at);
      })
      .catch((error: unknown) =>
        setTokenError(error instanceof Error ? error.message : "The token could not be made."),
      )
      .finally(() => setMaking(false));
  }

  function connect() {
    setConnecting(true);
    setConnectError(null);
    connectShop(tenantId, tidy(address))
      .then(() => {
        setConnected(true);
        // The page re-reads our own data: it now shows the connection and the
        // first copy of the catalogue being made. The shop is not asked again.
        startTransition(() => router.refresh());
      })
      .catch((error: unknown) =>
        setConnectError(error instanceof Error ? error.message : "Could not connect."),
      )
      .finally(() => setConnecting(false));
  }

  // The result shown belongs to the address typed now, or it is not shown.
  const last: ShopCheck | null =
    check.check && tidy(check.check.address) === tidy(address) ? check.check : null;
  const result = last?.status === "done" ? last.result : null;
  const madeAfterToken =
    !!last && !!madeAt && new Date(last.requested_at).getTime() >= new Date(madeAt).getTime();
  const canConnect = !!result?.conformant && madeAfterToken && !check.busy;
  const hasToken = madeAt !== null;

  return (
    <section aria-labelledby="connect" data-connect className="overflow-hidden rounded-2xl border">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b px-4 py-3.5 sm:px-5">
        <h2 id="connect" className="text-lg font-semibold">
          Connect your shop
        </h2>
        <Link
          href={`/console/${encodeURIComponent(tenantId)}/help`}
          className="text-sm font-medium underline-offset-3 hover:underline"
        >
          Help: connecting your shop →
        </Link>
      </div>
      <p className="px-4 pt-3.5 leading-relaxed text-muted-foreground sm:px-5">
        Three steps. Your developer adds a small bridge to your shop; you make its password and
        connect it here.
      </p>

      <ol className="divide-y">
        <Step n={1} done={hasToken} title="Make your shop token" who="You">
          <p className="leading-relaxed text-muted-foreground">
            A long secret password. Your shop&apos;s bridge asks for it before it answers, so nobody
            else can read your shop.
          </p>
          {token ? (
            <div data-token-once className="space-y-2.5 rounded-xl border border-foreground p-3.5">
              <p className="text-sm font-semibold">Your shop token. Shown once: copy it now.</p>
              <div className="flex flex-col gap-2 sm:flex-row">
                <code className="min-w-0 flex-1 rounded-lg bg-muted px-3 py-2.5 font-mono text-sm break-all">
                  {token}
                </code>
                <CopyButton text={token} label="Copy" className="sm:h-auto" />
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Send it to your developer through a password manager or a one-time link.{" "}
                <strong className="font-semibold text-foreground">
                  Never in a plain email or chat.
                </strong>{" "}
                Lost it? Make a new one here, and tell your developer at once.
              </p>
            </div>
          ) : hasToken ? (
            <p className="text-sm text-muted-foreground">
              Made <When iso={madeAt} inline />. It is kept locked away and can&apos;t be shown
              again.{" "}
              <button
                type="button"
                onClick={make}
                disabled={making}
                className="font-medium text-foreground underline underline-offset-3"
              >
                Lost it? Make a new one
              </button>
            </p>
          ) : (
            <Button className="h-11 w-full px-5 sm:h-10 sm:w-fit" onClick={make} disabled={making}>
              {making ? <RefreshCw className="animate-spin" aria-hidden /> : null}
              {making ? "Making…" : "Make the token"}
            </Button>
          )}
          {tokenError ? (
            <p role="alert" className="text-sm text-destructive">
              {tokenError}
            </p>
          ) : null}
        </Step>

        <Step
          n={2}
          done={!!result?.conformant}
          title="Your developer builds the bridge"
          who="Your developer"
        >
          <p className="leading-relaxed text-muted-foreground">
            They follow the guide for developers, put the token in the bridge&apos;s settings and
            put the bridge online. Then they send you its address.
          </p>
          <CopyButton
            text={DEVELOPER_GUIDE_URL}
            label="Copy the guide link for your developer"
            className="w-full sm:w-fit"
          />
        </Step>

        <Step n={3} done={connected} title="Check and connect" who="You">
          {!hasToken ? (
            <p className="text-muted-foreground">Make the token first.</p>
          ) : (
            <form
              className="space-y-1.5"
              onSubmit={(event) => {
                event.preventDefault();
                if (tidy(address)) check.start({ address: tidy(address) });
              }}
            >
              <Label htmlFor="bridge-address">Your bridge&apos;s address</Label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  id="bridge-address"
                  type="url"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="https://yourshop.example/neura/v1"
                  value={address}
                  onChange={(event) => setAddress(event.target.value)}
                  className="h-11 flex-1 font-mono sm:h-10"
                />
                <Button
                  type="submit"
                  className="h-11 px-5 sm:h-10"
                  disabled={check.busy || !tidy(address)}
                  data-check
                >
                  {check.busy ? <RefreshCw className="animate-spin" aria-hidden /> : null}
                  {check.busy ? "Checking…" : last ? "Check again" : "Check"}
                </Button>
              </div>
              <p className="text-sm text-muted-foreground">
                Asks your shop about 20 questions, the way the assistant will. Nothing in your shop
                changes.
              </p>
            </form>
          )}

          {check.error ? (
            <p role="alert" className="text-sm text-destructive">
              {check.error}
            </p>
          ) : null}

          {last?.status === "failed" ? (
            <p role="status" className="rounded-xl bg-muted/60 px-3.5 py-3 text-sm">
              The check could not run. Something went wrong on our side; try again in a minute.
            </p>
          ) : null}

          {result && !result.conformant ? <Problem result={result} /> : null}
          {result?.conformant ? <Passed text={result.text} total={result.passed} /> : null}

          {hasToken && !connected ? (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
              <Button
                className="h-11 px-5 sm:h-10"
                disabled={!canConnect || connecting}
                onClick={connect}
                data-connect-button
              >
                {connecting ? <RefreshCw className="animate-spin" aria-hidden /> : null}
                Connect and copy my catalogue
              </Button>
              <span className="text-sm text-muted-foreground">
                {canConnect
                  ? "Copies your products into NEURA. Nothing in your shop changes."
                  : result && !result.conformant
                    ? "Fix the problem above first."
                    : "Works after a check with no problems."}
              </span>
            </div>
          ) : null}
          {connectError ? (
            <p role="alert" className="text-sm text-destructive">
              {connectError}
            </p>
          ) : null}

          {connected ? (
            <div role="status" className="flex items-start gap-2.5 rounded-xl border p-3.5">
              <CheckCircle2 className="mt-0.5 size-5 shrink-0" aria-hidden />
              <span className="space-y-0.5">
                <span className="block font-semibold">Your shop is connected</span>
                <span className="block text-sm text-muted-foreground">
                  {refreshing
                    ? "Copying your catalogue now. This page shows the rest of your setup in a moment."
                    : "Copying your catalogue now."}
                </span>
              </span>
            </div>
          ) : null}
        </Step>
      </ol>
    </section>
  );
}

function Step({
  n,
  done,
  title,
  who,
  children,
}: {
  n: number;
  done: boolean;
  title: string;
  who: string;
  children: React.ReactNode;
}) {
  return (
    <li data-step-n={n} data-done={done} className="flex gap-3.5 px-4 py-4 sm:px-5">
      <span
        aria-label={done ? "Done" : undefined}
        className={cn(
          "flex size-7.5 shrink-0 items-center justify-center rounded-full text-sm font-semibold",
          done ? "bg-foreground text-background" : "border-[1.5px] border-foreground",
        )}
      >
        {done ? <Check className="size-4" aria-hidden /> : n}
      </span>
      <div className="min-w-0 flex-1 space-y-2.5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold">{title}</h3>
          <span className="shrink-0 rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
            {who}
          </span>
        </div>
        {children}
      </div>
    </li>
  );
}

function Problem({ result }: { result: NonNullable<ShopCheck["result"]> }) {
  const words = checkWords(result);
  return (
    <div
      role="status"
      data-check-result="problem"
      className="space-y-3 rounded-xl border border-destructive/30 bg-destructive/5 p-3.5"
    >
      <p className="flex items-center gap-2.5 font-semibold">
        <XCircle className="size-5.5 shrink-0 text-destructive" aria-hidden />
        {words.title}
      </p>
      <p className="text-sm leading-relaxed">{words.body}</p>
      {result.passed + result.failed > 0 && result.cause === "token_refused" ? (
        <p className="text-sm text-muted-foreground">
          {result.passed} checks passed and {result.failed} failed, all for this one reason.
        </p>
      ) : null}
      <CopyButton
        text={result.text}
        label="Copy the full check for your developer"
        className="w-full sm:w-fit"
      />
      <details className="border-t border-destructive/20 pt-2.5">
        <summary className="cursor-pointer text-sm font-medium">
          The full check, for your developer
        </summary>
        <pre className="mt-2.5 overflow-x-auto rounded-lg bg-foreground p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-background">
          {result.text}
        </pre>
      </details>
    </div>
  );
}

function Passed({ text, total }: { text: string; total: number }) {
  return (
    <div role="status" data-check-result="passed" className="space-y-3 rounded-xl border p-3.5">
      <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1 font-semibold">
        <CheckCircle2 className="size-5.5 shrink-0" aria-hidden />
        Your shop passed the check
        <span className="font-normal text-muted-foreground">
          {total} of {total}
        </span>
      </p>
      <ul className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
        {PASSED_WORDS.map((line) => (
          <li key={line} className="flex items-start gap-2">
            <Check className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
            {line}
          </li>
        ))}
      </ul>
      <p className="rounded-lg bg-muted/60 px-3.5 py-3 text-sm leading-relaxed">
        <strong className="font-semibold">The check proves the format, not the facts.</strong> A
        sold-out product marked &ldquo;in stock&rdquo; still passes. Ask your developer to look at a
        few products by hand.
      </p>
      <CopyButton
        text={text}
        label="Copy the full check for your developer"
        className="w-full sm:w-fit"
      />
    </div>
  );
}
