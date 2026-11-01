/**
 * The Marketing calendar (NEURA-GROW, ADR-0072; console.md §3.14): what the
 * console's own routes return, and the few words the pages build from it.
 *
 * **A calendar day is a date, not a moment.** `2027-04-14` is Avurudu in every
 * time zone, so it is written from its own digits and never moved by the
 * browser's clock (the `When` component is for moments). The shop's own *today*
 * comes from the API, counted in the shop's time (G119).
 */
import type { Price } from "@/lib/suggestions";

/** What a kept date's plan is, on *Coming up*. */
export type ComingStatus =
  "ready" | "making" | "failed" | "planned" | "tonight" | "paused" | "not_set";

export type ComingDate = {
  date_key: string;
  /** A suggested date's key (`avurudu`), or `null` for the shop's own. */
  key: string | null;
  name: string;
  /** The line under a suggested date's name, e.g. *Sinhala and Tamil New Year*. */
  line: string | null;
  own: boolean;
  every_year: boolean;
  /** `null`: a moving date not set yet. */
  day: string | null;
  /** A moving date's usual months, 1 to 12. */
  usually: number[];
  days_left: number | null;
  /** The day its plan is written, 21 days before. */
  plan_day: string | null;
  status: ComingStatus;
  plan_id: string | null;
};

export type Calendar = {
  today: string;
  country: "lk" | "other";
  time_zone: string;
  year: number;
  /** Whether this year's list was saved: only then do suggested dates count. */
  saved: boolean;
  plan_days_before: number;
  /** When FiveNeurals paused the plans (ADR-0065), or `null`. */
  paused_since: string | null;
  coming_up: ComingDate[];
};

export type SuggestedDate = {
  key: string;
  name: string;
  line: string | null;
  kept: boolean;
  /** Its day this year; `null` for payday (twelve) or a moving date not set. */
  day: string | null;
  moving: boolean;
  usually: number[];
  /** The owner set this moving date's day themselves. */
  set_by_owner: boolean;
  /** Only for a shop in Sri Lanka (R85). */
  sri_lanka: boolean;
};

export type OwnDate = {
  id: string;
  name: string;
  day: string;
  every_year: boolean;
  kept: boolean;
};

export type YearDates = {
  year: number;
  today: string;
  country: "lk" | "other";
  saved: boolean;
  groups: { group: "festivals" | "monthly" | "shopping"; dates: SuggestedDate[] }[];
  own: OwnDate[];
};

export type PlanFact = {
  kind: "wanted" | "gap";
  label: string;
  shoppers: number;
  product_id: string | null;
  product_title: string | null;
};

export type PlanProduct = {
  product_id: string;
  /** `null` when the synced catalogue no longer has it. */
  title: string | null;
  url?: string | null;
  image?: string | null;
  price?: Price | null;
};

/** The draft texts, in the order the page shows them. */
export const TEXT_FIELDS = [
  "teaser",
  "launch",
  "last_chance",
  "email_subject",
  "email_body",
  "banner",
] as const;
export type TextField = (typeof TEXT_FIELDS)[number];

export type Plan = {
  id: string;
  date_key: string;
  own: boolean;
  name: string;
  day: string;
  today: string;
  days_left: number;
  state: "ready" | "making" | "failed";
  /** Whether a plan was ever made (a first try may fail the checks twice). */
  has_plan: boolean;
  made_at: string | null;
  /** The day it was made, in the shop's time. */
  made_on: string | null;
  /** The last try failed the checks twice. */
  failed: boolean;
  theme: string | null;
  idea: string | null;
  act_on: PlanFact[];
  products: PlanProduct[];
  catalogue_cut: boolean;
  schedule: { step: "ready" | "teaser" | "launch" | "last_chance" | "day"; day: string }[];
  texts: Partial<Record<TextField, string>>;
  edited: TextField[];
  paused_since: string | null;
  can_make_again: boolean;
  /** Which GROW pages this role may open, for the links under *Act on this first*. */
  links: { wanted: boolean; gaps: boolean };
};

/** Home's calendar lines (ADR-0072 §7), for the Owner and Support. */
export type CalendarHome = {
  add_dates: boolean;
  ready: { plan_id: string; name: string; day: string; days_left: number }[];
};

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function parts(iso: string): { year: number; month: number; day: number } {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return { year, month, day };
}

/** *Apr 14*, or *Jan 15, 2027* when it is not `year`. */
export function shortDay(iso: string, year?: number): string {
  const { year: y, month, day } = parts(iso);
  const text = `${MONTHS[month - 1].slice(0, 3)} ${day}`;
  return year !== undefined && y !== year ? `${text}, ${y}` : text;
}

/** *April 14*, or *January 15, 2027* when it is not `year`. */
export function longDay(iso: string, year?: number): string {
  const { year: y, month, day } = parts(iso);
  const text = `${MONTHS[month - 1]} ${day}`;
  return year !== undefined && y !== year ? `${text}, ${y}` : text;
}

/** The small date box on *Coming up*: *APR* above *14*. */
export function dateBox(
  iso: string | null,
  usually: number[] = [],
): { month: string; day: string } {
  if (!iso) {
    // The month it is placed under: the last of its usual months (board 75).
    const month = usually.length ? MONTHS[Math.max(...usually) - 1].slice(0, 3) : "";
    return { month, day: "?" };
  }
  const { month, day } = parts(iso);
  return { month: MONTHS[month - 1].slice(0, 3), day: String(day) };
}

/** *usually in May*, *usually in October or November*; `""` when it moves through the year. */
export function usuallyIn(months: number[]): string {
  if (!months.length) return "";
  return `usually in ${months.map((m) => MONTHS[m - 1]).join(" or ")}`;
}

/** *in 21 days*, *tomorrow*, *today*. */
export function inDays(days: number): string {
  if (days <= 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

/** Home's line: *Avurudu is in 21 days. Your plan is ready.* */
export function readyLine(name: string, days: number): string {
  const when = days <= 0 ? "is today" : days === 1 ? "is tomorrow" : `is in ${days} days`;
  return `${name} ${when}. Your plan is ready.`;
}

/** The line under a date on *Coming up* (board 75). */
export function comingLine(date: ComingDate): string {
  const parts: string[] = [];
  if (date.own) parts.push(date.every_year ? "Your own date · every year" : "Your own date");
  else if (date.line) parts.push(date.line);
  if (date.day === null) {
    const usually = usuallyIn(date.usually);
    if (usually) parts.push(usually.charAt(0).toUpperCase() + usually.slice(1));
  } else if (date.days_left !== null && date.days_left <= 21) {
    parts.push(inDays(date.days_left));
  }
  return parts.join(" · ");
}

/** The page of one plan. */
export function planHref(tenantId: string, planId: string): string {
  return `/console/${encodeURIComponent(tenantId)}/calendar/${encodeURIComponent(planId)}`;
}

/** *This year's dates*. */
export function datesHref(tenantId: string): string {
  return `/console/${encodeURIComponent(tenantId)}/calendar/dates`;
}

/** The placeholder a draft holds where the owner's offer goes (ADR-0072 §5). */
export const OFFER = /\[your offer\]/gi;

/** A draft as one text to copy: the email's subject on its own first line. */
export function copyText(
  field: "teaser" | "launch" | "last_chance" | "email" | "banner",
  texts: Plan["texts"],
): string {
  if (field === "email") {
    return `Subject: ${texts.email_subject ?? ""}\n\n${texts.email_body ?? ""}`;
  }
  return texts[field] ?? "";
}
