"use client";

/**
 * The code from an admin's phone (ADR-0067, canvas row 18, boards 64 to 66).
 *
 * Shown by the admin layout instead of any admin page when the API answers
 * `ADMIN_CODE_SETUP` (no code yet: **set it up**, board 64) or
 * `ADMIN_CODE_NEEDED` (not typed in this sign-in: **type it**, board 65). The
 * API is the lock: these only ask, and a correct code makes the API issue the
 * sign-in cookie again, after which the page is read again.
 *
 * **The key is kept nowhere here.** Until setup is finished the API gives the
 * same key each time this page opens (G116: it opened twice at once, and two
 * keys showed one and stored the other); once finished, never again.
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { confirmAdminCode, signOut, startAdminCode, typeAdminCode } from "@/lib/api";
import type { AdminCodeSetup } from "@/lib/admin";
import { cn } from "@/lib/utils";

/** The API's code for 5 wrong codes in a row (ADR-0067 §5). */
const TOO_MANY_CODES = "TOO_MANY_CODES";

export function AdminCodeSetupPage() {
  const router = useRouter();
  const [setup, setSetup] = useState<AdminCodeSetup | null>(null);
  const [failed, setFailed] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    let current = true;
    startAdminCode()
      .then((made) => {
        if (current) setSetup(made);
      })
      .catch((caught) => {
        if (current) setFailed(caught instanceof Error ? caught.message : "Something went wrong.");
      });
    return () => {
      current = false;
    };
  }, []);

  return (
    <Card wide>
      {done ? (
        <div role="status" className="space-y-3" data-code-set-up>
          <h1 className="text-xl font-semibold">Your phone is set up</h1>
          <p className="text-sm leading-relaxed text-foreground/80">
            From now on, each time you sign in as an admin, you type a code from it. If you lose
            your phone, ask another FiveNeurals admin to reset your code.
          </p>
          <Button className="h-11 w-full" onClick={() => router.refresh()} data-go-to-shops>
            Go to Shops
          </Button>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="space-y-1.5">
            <h1 className="text-xl font-semibold">Protect your admin sign-in</h1>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Admin pages now need a code from your phone as well as the email link. Set it up once.
            </p>
          </div>
          <Step n={1}>
            <p className="text-sm leading-relaxed">
              Install an authenticator app on your phone, for example Google Authenticator or
              Microsoft Authenticator.
            </p>
          </Step>
          <Step n={2}>
            <p className="text-sm leading-relaxed">
              In the app, add an account and scan this code.
            </p>
            {setup ? (
              <>
                {/* A data: URL in an <img>: the SVG is drawn, never run. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={setup.qr_svg}
                  alt="QR code to scan with your authenticator app"
                  className="size-44 rounded-lg border bg-white p-2"
                />
                <p className="text-[13px] leading-relaxed text-muted-foreground">
                  Can&apos;t scan it? Type this key instead:
                  <br />
                  <span className="font-mono text-sm text-foreground" data-code-key>
                    {setup.key}
                  </span>
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">{failed || "Making your code…"}</p>
            )}
          </Step>
          <Step n={3}>
            <CodeForm
              label="Type the 6-digit code the app shows"
              action="Turn on"
              disabled={!setup}
              send={confirmAdminCode}
              onDone={() => setDone(true)}
            />
          </Step>
        </div>
      )}
    </Card>
  );
}

export function AdminCodePage() {
  const router = useRouter();
  return (
    <Card>
      <div className="space-y-1.5">
        <h1 className="text-xl font-semibold">Type the code from your phone</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Open your authenticator app and type the 6-digit code for FiveNeurals.
        </p>
      </div>
      <CodeForm
        label="Code"
        action="Continue"
        send={typeAdminCode}
        onDone={() => router.refresh()}
      />
      <p className="text-[13px] leading-relaxed text-muted-foreground">
        Lost your phone? Ask another FiveNeurals admin to reset your code.
      </p>
    </Card>
  );
}

function CodeForm({
  label,
  action,
  disabled = false,
  send,
  onDone,
}: {
  label: string;
  action: string;
  disabled?: boolean;
  send: (code: string) => Promise<unknown>;
  onDone: () => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stopped, setStopped] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await send(code);
      onDone();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Something went wrong.";
      setStopped((caught as { code?: string } | null)?.code === TOO_MANY_CODES);
      setError(message);
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  if (stopped) {
    return (
      <p
        role="alert"
        data-code-stopped
        className="rounded-lg border border-red-300 bg-red-50 px-3.5 py-3 text-sm leading-relaxed dark:border-red-900 dark:bg-red-950/40"
      >
        <strong className="font-semibold">Too many wrong codes.</strong> Wait 15 minutes, then try
        again.
      </p>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">{label}</span>
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={7}
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/[^\d ]/g, ""))}
          placeholder="123456"
          aria-invalid={Boolean(error)}
          data-code-input
          className={cn(
            "h-12 w-full rounded-lg border bg-background px-3 font-mono text-xl tracking-[0.3em] outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
            error ? "border-red-400" : "border-input",
          )}
        />
      </label>
      {error ? (
        <p role="alert" className="text-sm leading-relaxed text-red-700 dark:text-red-400">
          {error}
        </p>
      ) : null}
      <Button
        type="submit"
        className="h-11 w-full"
        disabled={disabled || busy || code.replace(/\s/g, "").length !== 6}
        data-code-submit
      >
        {busy ? "Checking…" : action}
      </Button>
    </form>
  );
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="grid size-6 shrink-0 place-items-center rounded-full bg-muted text-[13px] font-semibold">
        {n}
      </span>
      <div className="min-w-0 flex-1 space-y-2.5">{children}</div>
    </div>
  );
}

function Card({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  const router = useRouter();
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-12 sm:px-6">
      <div className="flex w-full flex-col items-center gap-4">
        <section
          className={cn(
            "flex w-full flex-col gap-5 rounded-xl border bg-card p-6",
            wide ? "max-w-md" : "max-w-sm",
          )}
          data-admin-code
        >
          <div className="flex items-center gap-2.5">
            <Brand />
            <span className="rounded-full bg-foreground px-2 py-0.5 text-xs font-semibold text-background">
              Admin
            </span>
          </div>
          {children}
        </section>
        <button
          type="button"
          className="text-sm text-foreground/80 underline underline-offset-3"
          onClick={async () => {
            await signOut().catch(() => undefined);
            router.replace("/");
            router.refresh();
          }}
        >
          Sign out
        </button>
      </div>
    </main>
  );
}
