"use client";

/**
 * A moment, written the way a shop owner reads it — *"Today, 9:09 PM"*, not
 * `9/24/2026, 9:09:29 PM`.
 *
 * **Formatted in the browser, because only the browser knows the owner's time
 * zone.** These screens render on the server, and a server's clock is usually
 * UTC: a date formatted there tells a merchant in Colombo that last night's
 * conversation happened this afternoon. So the server writes the plain ISO date,
 * which is true everywhere, and the browser replaces it once it has taken over.
 * `useSyncExternalStore` is what makes that swap legitimate — the first render in
 * the browser matches the server's HTML exactly, and only then changes.
 *
 * One component rather than a helper per screen: the same moment reading
 * differently on two screens is how a merchant stops trusting both.
 */
import { useSyncExternalStore } from "react";

const noChange = () => () => {};

export function When({ iso, date = false }: { iso: string | null; date?: boolean }) {
  const inBrowser = useSyncExternalStore(
    noChange,
    () => true,
    () => false,
  );

  if (!iso) return null;
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return null;

  return (
    <time dateTime={iso} title={inBrowser ? moment.toLocaleString(undefined, FULL) : undefined}>
      {inBrowser ? readable(moment, date) : iso.slice(0, 10)}
    </time>
  );
}

const FULL: Intl.DateTimeFormatOptions = { dateStyle: "full", timeStyle: "short" };

/**
 * `Today, 9:09 PM` · `Yesterday, 9:07 PM` · `24 Sep, 9:09 PM` · `24 Sep 2025, 9:09 PM`.
 *
 * With `date`, the day alone and never *Today* — it sits mid-sentence
 * (*"last viewed 27 Sep"*, *"20 Sep to 27 Sep"*), where a relative word reads
 * wrong. The month is always a word, so no reader has to guess whether 9/10 is
 * September or October.
 */
function readable(moment: Date, dateOnly: boolean): string {
  const now = new Date();
  const day = moment.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(moment.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
  if (dateOnly) return day;

  const time = moment.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);

  if (sameDay(moment, now)) return `Today, ${time}`;
  if (sameDay(moment, yesterday)) return `Yesterday, ${time}`;
  return `${day}, ${time}`;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}
