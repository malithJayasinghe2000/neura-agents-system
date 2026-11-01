"use client";

/**
 * Switch one feature of a shop off, or on again (ADR-0065, boards 61 and 63).
 *
 * **Turn off asks first**, because the chats from while it is off are never read
 * later (R52) and the shop cannot undo it (R50); **Turn on does not**, because it
 * costs nothing until the night. Each switch's words, the question *Turn off*
 * asks included, come from its agent's manifest, through the API, so a later
 * feature needs nothing here (the calendar's plans were the first, G123).
 */
import { useState } from "react";
import { day, type AdminSwitch } from "@/lib/admin";
import { setSwitch } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function FeatureSwitches({
  tenantId,
  name,
  switches,
}: {
  tenantId: string;
  name: string;
  switches: AdminSwitch[];
}) {
  return (
    <section aria-labelledby="switches-title" className="space-y-3.5">
      <div className="space-y-1.5">
        <h2 id="switches-title" className="text-lg font-semibold">
          Switch a feature off
        </h2>
        <p className="text-sm leading-relaxed text-foreground/80">
          Stop one feature for this shop, for example if its AI costs too much. The rest of the
          assistant keeps working. Only FiveNeurals can switch these.
        </p>
      </div>
      {switches.map((item) => (
        <OneSwitch key={item.key} tenantId={tenantId} name={name} initial={item} />
      ))}
    </section>
  );
}

function OneSwitch({
  tenantId,
  name,
  initial,
}: {
  tenantId: string;
  name: string;
  initial: AdminSwitch;
}) {
  const [item, setItem] = useState(initial);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const who = item.changed_by_you ? "by you" : "by another admin";

  async function change(on: boolean) {
    setBusy(true);
    setError("");
    try {
      setItem((await setSwitch(tenantId, item.key, on)).switch);
      setAsking(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3.5 rounded-xl border p-4" data-switch={item.key}>
      <div className="flex flex-col gap-3.5 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1 space-y-1">
          <p className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">
              {item.assistant.toUpperCase()} · {item.name}
            </span>
            <span
              className={
                item.on
                  ? "rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-950 dark:text-green-300"
                  : "rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-foreground/80"
              }
            >
              {item.on ? "On" : "Off"}
            </span>
          </p>
          <p className="text-[13px] leading-snug text-muted-foreground">{item.text}</p>
          {item.changed_at && !item.on ? (
            <p className="text-[13px] leading-snug text-foreground/80">
              Off since {day(item.changed_at, true)}, {who}.
            </p>
          ) : null}
          {item.changed_at && item.on ? (
            <p className="text-[13px] leading-snug text-foreground/80">
              On again since {day(item.changed_at, true)}, {who}.
              {item.on_again ? ` ${item.on_again}` : ""}
            </p>
          ) : null}
        </div>
        {item.on ? (
          <Button
            variant="outline"
            className="h-11 w-full px-4 sm:h-10 sm:w-auto"
            disabled={busy || asking}
            data-switch-off
            onClick={() => setAsking(true)}
          >
            Turn off
          </Button>
        ) : (
          <Button
            className="h-11 w-full px-4 sm:h-10 sm:w-auto"
            disabled={busy}
            data-switch-on
            onClick={() => change(true)}
          >
            {busy ? "Turning on…" : "Turn on"}
          </Button>
        )}
      </div>
      {asking ? (
        <div
          role="alertdialog"
          aria-labelledby={`off-${item.key}`}
          className="space-y-2.5 rounded-xl border border-red-300 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950/40"
        >
          <h3 id={`off-${item.key}`} className="text-base font-semibold">
            {item.ask ? item.ask.replace("{shop}", name) : `Turn off ${item.name} for ${name}?`}
          </h3>
          <p className="text-sm leading-relaxed text-foreground/80">
            {item.while_off ||
              "While it is off, this feature uses no AI. What it already made stays on the shop's page, marked Paused. The shop can't turn it back on."}
          </p>
          <div className="flex flex-col gap-3 pt-1 sm:flex-row">
            <Button
              className="h-11 w-full bg-red-700 px-4 text-white hover:bg-red-800 sm:h-10 sm:w-auto"
              disabled={busy}
              data-confirm-switch-off
              onClick={() => change(false)}
            >
              {busy ? "Turning off…" : "Turn off"}
            </Button>
            <Button
              variant="outline"
              className="h-11 w-full px-4 sm:h-10 sm:w-auto"
              disabled={busy}
              onClick={() => setAsking(false)}
            >
              Keep it on
            </Button>
          </div>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
