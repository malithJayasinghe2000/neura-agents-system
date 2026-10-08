"use client";

/**
 * The full check on Shop connection (ADR-0052 §4), replacing *Check now*, which
 * only asked `/health`.
 *
 * **Pressed, never automatic.** The check runs in the background on NEURA's own
 * server; the page asks **our** server every few seconds whether the result is
 * ready, exactly as *Sync now* watches a sync, and stops when it is. A page load
 * never asks the shop: what the page shows first is the **last** check, read
 * from our own table.
 *
 * Its answer fills two places, the checklist's *Your shop passes the check* and
 * *What your shop lets the assistant do*, so it lives in a small context, as
 * *Check now*'s answer did.
 */
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { AlertTriangle, Check, Copy, RefreshCw } from "lucide-react";
import { readShopCheck, startShopCheck } from "@/lib/api";
import {
  allowedWords,
  checkWords,
  warningWords,
  type CheckResult,
  type ShopCheck,
} from "@/lib/shop";
import { SetupItem } from "@/components/shop/setup-item";
import { When } from "@/components/when";
import { Button } from "@/components/ui/button";

/** How often to look while a check runs, and for how long. Not shown anywhere. */
export const LOOK_EVERY_MS = 3000;
export const LOOKS = 60;

type CheckState = {
  check: ShopCheck | null;
  /** Asking our server to start one, or watching one run. */
  busy: boolean;
  /** Could not start, or stopped watching. Plain words. */
  error: string | null;
};

/**
 * One check's life: start it, watch it, keep the last one. Shared by the
 * connected page and *Connect your shop*.
 */
export function useShopCheck(tenantId: string, initial: ShopCheck | null) {
  const [state, setState] = useState<CheckState>({
    check: initial,
    busy: initial?.status === "pending",
    error: null,
  });
  const [looks, setLooks] = useState(0);
  const pendingId = state.check?.status === "pending" ? state.check.id : null;

  // Past the last look, stop watching: said during render, not set in the effect.
  const gaveUp = !!pendingId && looks >= LOOKS;

  useEffect(() => {
    if (!pendingId || looks >= LOOKS) return;
    const timer = setTimeout(() => {
      readShopCheck(tenantId, pendingId)
        .then(({ check }) =>
          setState((was) => ({ ...was, check, busy: check.status === "pending" })),
        )
        .catch(() => undefined)
        .finally(() => setLooks((n) => n + 1));
    }, LOOK_EVERY_MS);
    return () => clearTimeout(timer);
  }, [pendingId, looks, tenantId]);

  const start = useCallback(
    (what: { address: string } | { store_id: string }) => {
      setState((was) => ({ ...was, busy: true, error: null }));
      setLooks(0);
      startShopCheck(tenantId, what)
        .then(({ check }) => setState({ check, busy: check.status === "pending", error: null }))
        .catch((error: unknown) =>
          setState((was) => ({
            ...was,
            busy: false,
            error: error instanceof Error ? error.message : "The check could not start.",
          })),
        );
    },
    [tenantId],
  );

  return {
    ...state,
    busy: state.busy && !gaveUp,
    error: gaveUp
      ? "The check is taking longer than usual. Reload this page in a minute."
      : state.error,
    start,
  };
}

// ── The connected page ───────────────────────────────────────────────────────

type Checks = Record<string, ReturnType<typeof useShopCheck>>;

const ChecksContext = createContext<Checks | null>(null);

/**
 * One running check per connection, for the two places that show it. One
 * provider per connection, nested, so each keeps its own hook however many
 * connections a page render has.
 */
export function ShopChecks({
  tenantId,
  stores,
  children,
}: {
  tenantId: string;
  stores: { id: string; last_check: ShopCheck | null }[];
  children: React.ReactNode;
}) {
  let tree = <>{children}</>;
  for (const store of [...stores].reverse()) {
    tree = (
      <StoreCheck key={store.id} tenantId={tenantId} storeId={store.id} initial={store.last_check}>
        {tree}
      </StoreCheck>
    );
  }
  return tree;
}

function StoreCheck({
  tenantId,
  storeId,
  initial,
  children,
}: {
  tenantId: string;
  storeId: string;
  initial: ShopCheck | null;
  children: React.ReactNode;
}) {
  const parent = useContext(ChecksContext);
  const state = useShopCheck(tenantId, initial);
  return <ChecksContext value={{ ...parent, [storeId]: state }}>{children}</ChecksContext>;
}

function useStoreCheck(storeId: string) {
  const checks = useContext(ChecksContext);
  if (!checks?.[storeId]) throw new Error("useStoreCheck needs <ShopChecks> around it.");
  return checks[storeId];
}

/** *Your shop passes the check*: the last full check, and **Check again**. */
export function CheckItem({ storeId }: { storeId: string }) {
  const { check, busy, error, start } = useStoreCheck(storeId);
  const result = check?.status === "done" ? check.result : null;
  // A warning is a check that did not pass cleanly, so it is counted, not passed (G75).
  const total = result ? result.passed + result.failed + result.warnings : 0;

  const button = (
    <Button
      variant="outline"
      className="h-10 sm:h-9"
      disabled={busy}
      onClick={() => start({ store_id: storeId })}
      data-check-now
    >
      {busy ? <RefreshCw className="animate-spin" aria-hidden /> : null}
      {busy ? "Checking…" : check ? "Check again" : "Check now"}
    </Button>
  );

  if (busy || !check) {
    return (
      <SetupItem
        item="check"
        store={storeId}
        state="not-yet"
        title="Your shop passes the check"
        detail={
          busy
            ? "Checking your shop now. This takes a few seconds."
            : "Not checked yet · this asks your shop about 20 questions, and changes nothing"
        }
        action={button}
      />
    );
  }
  if (error || check.status === "failed" || !result) {
    return (
      <SetupItem
        item="check"
        store={storeId}
        state="failed"
        title="The check could not run"
        detail={error ?? "Something went wrong on our side. Try again in a minute."}
        action={button}
      />
    );
  }
  if (!result.conformant) {
    const words = checkWords(result);
    return (
      <SetupItem
        item="check"
        store={storeId}
        state="failed"
        title={words.title}
        detail={
          <>
            {words.body}
            <span className="mt-2 block">
              <CopyButton text={result.text} label="Copy the full check for your developer" />
            </span>
          </>
        }
        action={button}
      />
    );
  }
  return (
    <SetupItem
      item="check"
      store={storeId}
      state="done"
      title="Your shop passes the check"
      detail={
        <>
          {result.passed} of {total} · checked{" "}
          {check.finished_at ? <When iso={check.finished_at} inline /> : "just now"}
          {result.warnings > 0 ? (
            <>
              <CheckWarnings result={result} className="mt-2.5" />
              <span className="mt-2.5 block">
                <CopyButton text={result.text} label="Copy the full check for your developer" />
              </span>
            </>
          ) : null}
        </>
      }
      action={button}
    />
  );
}

/**
 * A clean check's warnings, in the owner's words (G75). They do not stop
 * Connect, but some change what shoppers get, so the owner reads them here and
 * not only in the copy for the developer. Spans, so it fits inside a row's text.
 */
export function CheckWarnings({
  result,
  className = "",
}: {
  result: CheckResult;
  className?: string;
}) {
  const lines = warningWords(result);
  if (lines.length === 0) return null;
  return (
    <span
      data-check-warnings
      className={`block space-y-1.5 rounded-lg border px-3.5 py-3 text-sm leading-relaxed text-foreground ${className}`}
    >
      <span className="block font-semibold">
        {result.warnings === 1 ? "1 thing to look at" : `${result.warnings} things to look at`}
      </span>
      {lines.map((line) => (
        <span key={line} className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          {line}
        </span>
      ))}
      <span className="block text-muted-foreground">
        Your developer sees the details in the full check.
      </span>
    </span>
  );
}

/** *What your shop lets the assistant do*: the shop's own declaration, from the last check. */
export function AllowedList({ storeId }: { storeId: string }) {
  const { check, busy } = useStoreCheck(storeId);
  const result = check?.status === "done" ? check.result : null;

  if (!result || (result.cause !== null && result.cause !== "token_refused")) {
    return (
      <p className="rounded-xl border border-dashed p-3.5 text-sm text-muted-foreground">
        {busy ? (
          "Checking your shop…"
        ) : result ? (
          "Your shop did not answer the last check, so we can't say what it allows."
        ) : (
          <>
            Press <strong className="font-semibold text-foreground">Check now</strong> above to ask
            your shop.
          </>
        )}
      </p>
    );
  }

  const allowed = allowedWords(result.capabilities);
  if (allowed.length === 0) {
    return <p className="text-sm">Your shop declared nothing it allows.</p>;
  }
  return (
    <ul data-allowed className="grid gap-x-4 gap-y-2.5 text-sm sm:grid-cols-2">
      {allowed.map((entry) => (
        <li key={entry.what} className="flex items-start gap-2">
          <Check className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="space-y-0.5">
            <span className="block">{entry.what}</span>
            {entry.note ? (
              <span className="block text-xs text-muted-foreground">{entry.note}</span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Copies text, and says so. Nothing is shown in a toast that could be missed. */
export function CopyButton({
  text,
  label,
  className = "",
}: {
  text: string;
  label: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      variant="outline"
      className={`h-10 sm:h-9 ${className}`}
      onClick={() => {
        void navigator.clipboard
          .writeText(text)
          .then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 2500);
          })
          .catch(() => setCopied(false));
      }}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      {copied ? "Copied" : label}
    </Button>
  );
}
