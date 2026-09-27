/**
 * Calendar days in the reader's time zone, as `YYYY-MM-DD`.
 *
 * The API's date filters take days plus a zone (`since`, `until`, `tz`) and turn
 * them into instants itself, so the only arithmetic here is on day strings —
 * which is the arithmetic that cannot go wrong across a daylight-saving change.
 */

/** The day an instant falls on in `timeZone`. */
export function dayIn(instant: Date | string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(instant));
}

export function addDays(day: string, count: number): string {
  const moment = new Date(`${day}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + count);
  return moment.toISOString().slice(0, 10);
}

/** `Sep 24`, or `Sep 24, 2025` when it is not this year. */
export function dayWords(day: string, today: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    ...(day.slice(0, 4) === today.slice(0, 4) ? {} : { year: "numeric" }),
  });
}

/** A heading for a group of the day's items: `Today`, `Yesterday`, `Sep 24`. */
export function dayHeading(day: string, today: string): string {
  if (day === today) return "Today";
  if (day === addDays(today, -1)) return "Yesterday";
  return dayWords(day, today);
}

/** The date choices a list offers, the same on every screen that has one. */
export const ASKED_CHOICES: { key: string; label: string }[] = [
  { key: "", label: "Any time" },
  { key: "today", label: "Today" },
  { key: "7d", label: "Last 7 days" },
  { key: "30d", label: "Last 30 days" },
  { key: "custom", label: "Choose dates…" },
];

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * A choice → the first and last day it covers, both inclusive. `null` for
 * *Any time*. A chosen day that is not a day is dropped rather than guessed.
 */
export function askedWindow(
  asked: string,
  from: string,
  to: string,
  today: string,
): { since?: string; until?: string } | null {
  switch (asked) {
    case "today":
      return { since: today, until: today };
    case "7d":
      return { since: addDays(today, -6), until: today };
    case "30d":
      return { since: addDays(today, -29), until: today };
    case "custom":
      return {
        since: DAY.test(from) ? from : undefined,
        until: DAY.test(to) ? to : undefined,
      };
    default:
      return null;
  }
}

/** ` · asked Sep 21 – Sep 27` — the words that go after a filtered count. */
export function askedWords(
  window: { since?: string; until?: string } | null,
  today: string,
): string {
  if (!window || (!window.since && !window.until)) return "";
  if (window.since === today && window.until === today) return " · asked today";
  const from = window.since ? dayWords(window.since, today) : "the start";
  const to = window.until ? dayWords(window.until, today) : "today";
  return ` · asked ${from} – ${to}`;
}
