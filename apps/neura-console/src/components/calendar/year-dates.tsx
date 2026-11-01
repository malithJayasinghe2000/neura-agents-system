"use client";

/**
 * *This year's dates* (board 77): the ticks, a moving date's day, the shop's
 * own dates, and where the shop is.
 *
 * **What saves when** (R101): *Add* and *Remove* of an own date act at once;
 * the ticks, a moving date's day and *Your shop is in* are kept by **Save this
 * year's dates**, one decision for the year. An unticked date greys and says
 * *No plan will be made*.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Check, Plus } from "lucide-react";
import { addOwnDate, removeOwnDate, saveCalendarDates } from "@/lib/api";
import {
  shortDay,
  usuallyIn,
  type OwnDate,
  type SuggestedDate,
  type YearDates,
} from "@/lib/calendar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const GROUPS = {
  festivals: "Festivals in Sri Lanka",
  monthly: "Every month",
  shopping: "Shopping days",
} as const;

const DATE_INPUT =
  "h-10 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

export function YearDatesForm({ tenantId, initial }: { tenantId: string; initial: YearDates }) {
  const router = useRouter();
  const year = initial.year;
  const all = initial.groups.flatMap((group) => group.dates);
  const [country, setCountry] = useState(initial.country);
  const [ticks, setTicks] = useState<Record<string, boolean>>(
    Object.fromEntries(all.map((d) => [d.key, d.kept])),
  );
  // A moving date's day the owner set (AD12: *you can set one yourself*).
  const [days, setDays] = useState<Record<string, string>>(
    Object.fromEntries(all.flatMap((d) => (d.set_by_owner && d.day ? [[d.key, d.day]] : []))),
  );
  const [setting, setSetting] = useState<Record<string, boolean>>({});
  const [own, setOwn] = useState<OwnDate[]>(initial.own);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const shown = initial.groups.filter((g) => country === "lk" || g.group === "shopping");

  async function save() {
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      await saveCalendarDates(tenantId, {
        country,
        dates: all
          .filter((d) => country === "lk" || !d.sri_lanka)
          .map((d) => ({
            key: d.key,
            kept: ticks[d.key] ?? true,
            day: d.moving ? (days[d.key] ?? null) : null,
          })),
        own: own.map((d) => ({ id: d.id, kept: d.kept })),
      });
      setSaved(true);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <fieldset className="space-y-2" data-country={country}>
        <legend className="text-sm font-medium">Your shop is in</legend>
        <div className="flex flex-wrap gap-2">
          {(
            [
              ["lk", "Sri Lanka"],
              ["other", "Another country"],
            ] as const
          ).map(([value, label]) => (
            <label
              key={value}
              className={cn(
                "inline-flex h-11 cursor-pointer items-center gap-2 rounded-lg border px-4 text-sm font-medium has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 sm:h-10",
                country === value
                  ? "border-foreground bg-foreground text-background"
                  : "bg-background",
              )}
            >
              <input
                type="radio"
                name="country"
                value={value}
                className="sr-only"
                checked={country === value}
                data-country-choice={value}
                onChange={() => {
                  setCountry(value);
                  setSaved(false);
                }}
              />
              {label}
            </label>
          ))}
        </div>
        {country === "other" ? (
          <p className="text-sm text-muted-foreground">
            A shop outside Sri Lanka gets the shopping days and its own dates.
          </p>
        ) : null}
      </fieldset>

      {shown.map((group) => (
        <section key={group.group} className="space-y-3" aria-labelledby={`dates-${group.group}`}>
          <h2 id={`dates-${group.group}`} className="text-[17px] font-semibold">
            {GROUPS[group.group]}
          </h2>
          <ul className="divide-y overflow-hidden rounded-xl border">
            {group.dates.map((date) => (
              <SuggestedRow
                key={date.key}
                date={date}
                year={year}
                kept={ticks[date.key] ?? true}
                day={days[date.key] ?? null}
                setting={!!setting[date.key]}
                onTick={(kept) => {
                  setTicks({ ...ticks, [date.key]: kept });
                  setSaved(false);
                }}
                onSet={() => setSetting({ ...setting, [date.key]: true })}
                onDay={(value) => {
                  const next = { ...days };
                  if (value) next[date.key] = value;
                  else delete next[date.key];
                  setDays(next);
                  setSaved(false);
                }}
              />
            ))}
          </ul>
        </section>
      ))}

      <OwnDates
        tenantId={tenantId}
        year={year}
        today={initial.today}
        own={own}
        onChange={setOwn}
        onTick={(id, kept) => {
          setOwn(own.map((d) => (d.id === id ? { ...d, kept } : d)));
          setSaved(false);
        }}
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
        <Button
          className="h-11 px-5 sm:h-10 sm:shrink-0"
          disabled={busy}
          data-save-dates
          onClick={save}
        >
          {busy ? "Saving…" : "Save this year's dates"}
        </Button>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Moving dates are checked by FiveNeurals each January. You can set one yourself if it is
          not set yet.
        </p>
      </div>
      {saved ? (
        <p role="status" data-dates-saved className="flex items-center gap-2 text-sm font-medium">
          <Check className="size-4" aria-hidden />
          Saved. Your assistant writes a plan 21 days before each ticked date.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function SuggestedRow({
  date,
  year,
  kept,
  day,
  setting,
  onTick,
  onSet,
  onDay,
}: {
  date: SuggestedDate;
  year: number;
  kept: boolean;
  /** The owner's day for a moving date, as typed on this page. */
  day: string | null;
  setting: boolean;
  onTick: (kept: boolean) => void;
  onSet: () => void;
  onDay: (value: string) => void;
}) {
  // A moving date whose day came from FiveNeurals' January check is shown as a
  // fixed one; one nobody set yet can be set here (AD12).
  const listed = date.moving && !date.set_by_owner ? date.day : null;
  const open = date.moving && !listed && (setting || day !== null);
  const notSet = date.moving && !listed && !open;
  const fixed = date.moving ? listed : date.day;
  const lines = [
    date.line,
    notSet ? ["Date not set yet", usuallyIn(date.usually)].filter(Boolean).join(" · ") : null,
    kept ? null : "No plan will be made",
  ].filter(Boolean);

  return (
    <li
      data-date={date.key}
      data-kept={kept ? "yes" : "no"}
      className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
    >
      <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 size-[18px] shrink-0 accent-foreground"
          checked={kept}
          data-tick={date.key}
          onChange={(event) => onTick(event.target.checked)}
        />
        <span className="min-w-0 space-y-0.5">
          <span className={cn("block font-semibold", kept ? "" : "text-muted-foreground")}>
            {date.name}
          </span>
          {lines.map((line) => (
            <span key={line} className="block text-[13px] text-muted-foreground">
              {line}
            </span>
          ))}
        </span>
      </label>
      <div className="flex shrink-0 items-center gap-2 pl-[30px] sm:pl-0">
        {fixed ? <span className="text-sm text-foreground/80">{shortDay(fixed, year)}</span> : null}
        {notSet ? (
          <Button
            variant="outline"
            className="h-11 px-4 sm:h-10"
            data-set-date={date.key}
            onClick={onSet}
          >
            Set the date
          </Button>
        ) : null}
        {open ? (
          <input
            type="date"
            aria-label={`${date.name}: its day in ${year}`}
            className={DATE_INPUT}
            min={`${year}-01-01`}
            max={`${year}-12-31`}
            value={day ?? ""}
            data-date-day={date.key}
            onChange={(event) => onDay(event.target.value)}
          />
        ) : null}
      </div>
    </li>
  );
}

function OwnDates({
  tenantId,
  year,
  today,
  own,
  onChange,
  onTick,
}: {
  tenantId: string;
  year: number;
  today: string;
  own: OwnDate[];
  onChange: (next: OwnDate[]) => void;
  onTick: (id: string, kept: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [day, setDay] = useState("");
  const [everyYear, setEveryYear] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function add() {
    if (!name.trim() || !day) {
      setError("Give the date a name and a day.");
      return;
    }
    setBusy("add");
    setError("");
    try {
      const added = await addOwnDate(tenantId, { name, day, every_year: everyYear });
      onChange([...own, added].sort((a, b) => a.day.localeCompare(b.day)));
      setName("");
      setDay("");
      setEveryYear(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy("");
    }
  }

  async function remove(id: string) {
    setBusy(id);
    setError("");
    try {
      await removeOwnDate(tenantId, id);
      onChange(own.filter((d) => d.id !== id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="space-y-3" aria-labelledby="dates-own">
      <h2 id="dates-own" className="text-[17px] font-semibold">
        Your own dates
      </h2>
      <ul className="divide-y overflow-hidden rounded-xl border">
        {own.map((date) => (
          <li
            key={date.id}
            data-own-date={date.id}
            className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
          >
            <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
              <input
                type="checkbox"
                className="mt-1 size-[18px] shrink-0 accent-foreground"
                checked={date.kept}
                onChange={(event) => onTick(date.id, event.target.checked)}
              />
              <span className="min-w-0 space-y-0.5">
                <span
                  className={cn(
                    "block font-semibold break-words",
                    date.kept ? "" : "text-muted-foreground",
                  )}
                >
                  {date.name}
                </span>
                {date.every_year ? (
                  <span className="block text-[13px] text-muted-foreground">Every year</span>
                ) : null}
                {date.kept ? null : (
                  <span className="block text-[13px] text-muted-foreground">
                    No plan will be made
                  </span>
                )}
              </span>
            </label>
            <div className="flex shrink-0 items-center gap-3 pl-[30px] sm:pl-0">
              <span className="text-sm text-foreground/80">{shortDay(date.day, year)}</span>
              <Button
                variant="ghost"
                className="h-11 px-3 sm:h-10"
                disabled={busy === date.id}
                data-remove-own={date.id}
                onClick={() => remove(date.id)}
              >
                {busy === date.id ? "Removing…" : "Remove"}
              </Button>
            </div>
          </li>
        ))}
        <li className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:flex-wrap sm:items-center sm:px-5">
          <Input
            placeholder="Name, e.g. Our big sale"
            aria-label="The date's name"
            className="h-10 sm:max-w-xs sm:flex-1"
            maxLength={60}
            value={name}
            data-own-name
            onChange={(event) => setName(event.target.value)}
          />
          <input
            type="date"
            aria-label="Its day"
            className={DATE_INPUT}
            min={today}
            max={`${year + 1}-12-31`}
            value={day}
            data-own-day
            onChange={(event) => setDay(event.target.value)}
          />
          <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-[18px] accent-foreground"
              checked={everyYear}
              data-own-every-year
              onChange={(event) => setEveryYear(event.target.checked)}
            />
            Every year
          </label>
          <Button
            variant="outline"
            className="h-11 self-start px-4 sm:h-10 sm:self-auto"
            disabled={busy === "add"}
            data-add-own
            onClick={add}
          >
            <Plus aria-hidden />
            {busy === "add" ? "Adding…" : "Add"}
          </Button>
        </li>
      </ul>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </section>
  );
}
