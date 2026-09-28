/**
 * Screen 5 — Usage and cost. The one that is easiest to make dishonest.
 *
 * `docs/console.md §5`: *"Every number carries its own honesty… a dashboard is
 * exactly where that discipline usually dies."* Four rules follow from that,
 * and every one of them is subtractive:
 *
 * 1. **No rate.** Not a deflection rate, not a resolution rate, not a trend.
 *    Every ratio this data supports is a business claim in disguise; the screen
 *    shows "36 of 53", which a merchant can check.
 * 2. **No cost figure that means nothing.** Zero is what a local model records
 *    *and* what an unpriced hosted model records. Words, not `$0.00`.
 * 3. **The period is on the screen, always** — and since 2026-09-28 every part
 *    follows it, including the split by assistant (it was today only).
 * 4. **Practice mode is stated first**, once. True numbers describing work no
 *    shopper ever saw is the most misleading page this console could produce.
 *
 * Redesigned 2026-09-28 from the owner's approved mockup (console.md §3.5):
 * *questions*, not *turns*; normal labels; dates in words; conversations with
 * links to them; **AI use** — calls, tokens said in one line, cost said once
 * with its reason; a sentence when AI worked with no conversation (background
 * suggestions), which otherwise reads as a broken assistant; and a table by
 * assistant, named as the merchant buys them (NEURA-CARE, NEURA-SELL).
 *
 * The sentences under the figures come from the server, chosen **by key**, not
 * from this file: a merchant-facing sentence living in a JavaScript bundle is
 * one nobody reviews and nobody can change (ADR-0020 §3).
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { EyeOff, Info, Sparkles } from "lucide-react";
import { assistantName, assistantPurpose } from "@/lib/assistants";
import { dayWords } from "@/lib/days";
import { fromApi, hasSession } from "@/lib/server-api";
import { PERIODS, type Cost, type Totals, type Usage } from "@/lib/usage";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export default async function UsagePage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ period?: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const { period = "30d" } = await searchParams;
  const chosen = PERIODS.some((p) => p.key === period) ? period : "30d";

  const result = await fromApi<Usage>(
    `/shops/${encodeURIComponent(tenantId)}/usage?period=${encodeURIComponent(chosen)}`,
  );

  return (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Usage and cost</h1>
        <p className="text-muted-foreground">
          What your assistant did, and what these numbers do not say.
        </p>
      </div>

      {!result.ok ? (
        <Alert variant="destructive">
          <AlertTitle>
            {result.status === 404 ? "No such shop, or no access to it" : "Could not load"}
          </AlertTitle>
          <AlertDescription>
            {result.status === 404
              ? "Your account does not hold a live membership for this shop."
              : result.message}
          </AlertDescription>
        </Alert>
      ) : (
        <UsageBody tenantId={tenantId} chosen={chosen} usage={result.data} />
      )}
    </>
  );
}

/** The caveats this screen places next to their own figures; any other is listed at the end. */
const PLACED = new Set([
  "practice_mode",
  "handed_to_a_person",
  "cost_not_recorded",
  "background_ai",
]);

function UsageBody({
  tenantId,
  chosen,
  usage,
}: {
  tenantId: string;
  chosen: string;
  usage: Usage;
}) {
  const base = `/console/${encodeURIComponent(tenantId)}`;
  const caveat = (key: string) => usage.caveats.find((c) => c.key === key)?.text;
  const others = usage.caveats.filter((c) => !PLACED.has(c.key));
  const { totals } = usage;
  const nothing = totals.conversations === 0 && totals.turns === 0 && totals.llm_calls === 0;

  return (
    <>
      <nav aria-label="Period" className="flex flex-wrap gap-2">
        {PERIODS.map((option) => {
          const on = option.key === chosen;
          return (
            <Link
              key={option.key}
              href={`${base}/usage?period=${option.key}`}
              aria-current={on ? "page" : undefined}
              className={cn(
                "inline-flex h-10 items-center rounded-full border px-4 text-sm font-medium transition-colors",
                on
                  ? "border-foreground bg-foreground text-background"
                  : "text-muted-foreground hover:border-foreground/40 hover:text-foreground",
              )}
            >
              {option.label}
            </Link>
          );
        })}
      </nav>

      {/* Stated before any figure, and once. A merchant reading "53
          conversations" in practice mode is reading about an assistant no
          shopper has met. */}
      {usage.withheld ? (
        <p className="flex items-start gap-3 rounded-xl border bg-muted/40 px-4 py-3.5 text-sm sm:items-center">
          <EyeOff className="mt-0.5 size-4 shrink-0 text-muted-foreground sm:mt-0" aria-hidden />
          <span className="text-muted-foreground">
            <strong className="font-semibold text-foreground">Practice mode is on.</strong> No
            shopper saw any of this. The replies are waiting in{" "}
            <Link className="text-foreground underline underline-offset-3" href={`${base}/review`}>
              Review
            </Link>
            .
          </span>
        </p>
      ) : null}

      <h2 className="text-lg font-semibold">
        <PeriodWords usage={usage} />
      </h2>

      {nothing ? (
        <div className="space-y-1.5 rounded-2xl border border-dashed p-5">
          <p className="font-semibold">Nothing recorded in this period</p>
          <p className="text-sm text-muted-foreground">
            {usage.period.days === null
              ? "Nothing has ever been recorded for this shop. Usage appears here from the first time a shopper talks to your assistant."
              : "Nothing was recorded in this window. Try a longer one — there may be older activity."}
          </p>
        </div>
      ) : (
        <>
          <section aria-labelledby="conversations" className="space-y-2.5">
            <h3 id="conversations" className="text-sm font-medium text-muted-foreground">
              Conversations
            </h3>
            <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4 lg:gap-3">
              <Tile
                value={count(totals.conversations)}
                label={plural(totals.conversations, "conversation", "conversations")}
                href={`${base}/conversations`}
              />
              <Tile
                value={count(totals.turns)}
                label={plural(totals.turns, "question a shopper asked", "questions shoppers asked")}
              />
              <Tile
                value={count(totals.escalations)}
                label="handed to a person"
                href={`${base}/conversations?state=escalated`}
              />
              <Tile
                value={count(totals.blocked)}
                label={plural(totals.blocked, "blocked as an attack", "blocked as attacks")}
              />
            </div>
            <Note text={caveat("handed_to_a_person")} />
          </section>

          <section aria-labelledby="ai-use" className="space-y-2.5">
            <h3 id="ai-use" className="text-sm font-medium text-muted-foreground">
              AI use
            </h3>
            <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-3 lg:gap-3">
              <Tile
                value={count(totals.llm_calls)}
                label={plural(totals.llm_calls, "AI call", "AI calls")}
                detail="each time your assistant asked the AI"
              />
              <Tile
                value={count(totals.total_tokens)}
                label={plural(totals.total_tokens, "token", "tokens")}
                detail="the unit AI providers charge by"
              />
              <CostTile cost={totals.cost} />
            </div>
            <Note text={caveat("cost_not_recorded")} />
            {caveat("background_ai") ? (
              <p className="flex items-start gap-2.5 rounded-lg bg-muted/60 px-3.5 py-3 text-sm">
                <Sparkles className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                {caveat("background_ai")}
              </p>
            ) : null}
          </section>

          <ByAssistant usage={usage} />
        </>
      )}

      {/* A caveat this screen has no place for yet is still shown, not dropped. */}
      {others.map((other) => (
        <p key={other.key} className="flex items-start gap-2 text-sm text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {other.text}
        </p>
      ))}
    </>
  );
}

/** "Last 30 days · Aug 30 – Sep 28" — the meter's days, in words. */
function PeriodWords({ usage }: { usage: Usage }) {
  const { period } = usage;
  const today = period.through;
  const [title, dates] =
    period.days === null
      ? [
          "Everything recorded",
          period.first_recorded ? `since ${dayWords(period.first_recorded, today)}` : null,
        ]
      : period.days === 1
        ? ["Today", dayWords(today, today)]
        : [
            `Last ${period.days} days`,
            `${dayWords(period.since ?? today, today)} – ${dayWords(today, today)}`,
          ];
  return (
    <>
      {title}
      {dates ? <span className="font-normal text-muted-foreground"> · {dates}</span> : null}
    </>
  );
}

function Tile({
  value,
  label,
  detail,
  href,
}: {
  value: string;
  label: string;
  detail?: string;
  href?: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border px-3.5 py-3.5 sm:px-4.5 sm:py-4">
      <span className="text-2xl font-semibold tracking-tight tabular-nums sm:text-3xl">
        {value}
      </span>
      <span className="text-sm text-muted-foreground">{label}</span>
      {detail ? <span className="text-xs text-muted-foreground">{detail}</span> : null}
      {href ? (
        <Link
          href={href}
          className="mt-1 text-sm font-medium underline-offset-3 hover:underline"
          aria-label={`See the ${label}`}
        >
          See them →
        </Link>
      ) : null}
    </div>
  );
}

/**
 * Words, never `$0.00`. Zero is what a free local model records and what a
 * hosted model with no configured price records — the figure cannot tell a
 * merchant which, so it does not pretend to.
 */
function CostTile({ cost }: { cost: Cost }) {
  if (cost.measured) {
    return <Tile value={money(cost)} label="cost" detail="what the AI providers charged" />;
  }
  return (
    <div className="col-span-2 flex flex-col gap-1 rounded-xl border border-dashed bg-muted/30 px-3.5 py-3.5 sm:px-4.5 sm:py-4 lg:col-span-1">
      <span className="text-xl leading-9 font-semibold text-muted-foreground">Not priced</span>
      <span className="text-sm text-muted-foreground">cost</span>
      <span className="text-xs text-muted-foreground">
        said in words, never as a zero — the reason is below
      </span>
    </div>
  );
}

function ByAssistant({ usage }: { usage: Usage }) {
  const agents = Object.entries(usage.by_agent);
  if (agents.length === 0) return null;
  const heading =
    usage.period.days === null
      ? "Everything recorded"
      : usage.period.days === 1
        ? "Today"
        : `Last ${usage.period.days} days`;

  return (
    <section aria-labelledby="by-assistant" className="space-y-2.5">
      <h3 id="by-assistant" className="text-sm font-medium text-muted-foreground">
        By assistant · {heading}
      </h3>

      {/* A table where there is room for one; a card per assistant on a phone. */}
      <div className="hidden overflow-hidden rounded-xl border md:block">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-muted-foreground">
            <tr className="border-b">
              <th scope="col" className="px-4 py-3 text-left font-medium">
                Assistant
              </th>
              {COLUMNS.map((column) => (
                <th key={column.label} scope="col" className="px-3 py-3 text-right font-medium">
                  {column.label}
                </th>
              ))}
              <th scope="col" className="px-4 py-3 text-right font-medium">
                Cost
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {agents.map(([key, totals]) => (
              <tr key={key} data-agent={key}>
                <th scope="row" className="px-4 py-3 text-left font-normal">
                  <span className="block font-medium">{assistantName(key)}</span>
                  {assistantPurpose(key) ? (
                    <span className="block text-xs text-muted-foreground">
                      {assistantPurpose(key)}
                    </span>
                  ) : null}
                </th>
                {COLUMNS.map((column) => (
                  <td key={column.label} className="px-3 py-3 text-right tabular-nums">
                    {count(column.value(totals))}
                  </td>
                ))}
                <td
                  className={cn(
                    "px-4 py-3 text-right",
                    totals.cost.measured ? "tabular-nums" : "text-muted-foreground",
                  )}
                >
                  {totals.cost.measured ? money(totals.cost) : "Not priced"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="space-y-2.5 md:hidden">
        {agents.map(([key, totals]) => (
          <li key={key} data-agent={key} className="space-y-1 rounded-xl border p-3.5">
            <p className="font-semibold">
              {assistantName(key)}
              {assistantPurpose(key) ? (
                <span className="font-normal text-muted-foreground">
                  {" "}
                  · {assistantPurpose(key)}
                </span>
              ) : null}
            </p>
            <p className="text-sm">
              {counted(totals.conversations, "conversation", "conversations")} ·{" "}
              {counted(totals.turns, "question", "questions")} · {count(totals.escalations)} handed
              to a person
            </p>
            <p className="text-xs text-muted-foreground">
              {counted(totals.llm_calls, "AI call", "AI calls")} ·{" "}
              {counted(totals.total_tokens, "token", "tokens")} · cost{" "}
              {totals.cost.measured ? money(totals.cost) : "not priced"}
            </p>
          </li>
        ))}
      </ul>

      <p className="text-sm text-muted-foreground">
        Same period as above. The rows add up to the totals.
      </p>
    </section>
  );
}

const COLUMNS: { label: string; value: (totals: Totals) => number }[] = [
  { label: "Conversations", value: (t) => t.conversations },
  { label: "Questions", value: (t) => t.turns },
  { label: "Handed to a person", value: (t) => t.escalations },
  { label: "Blocked", value: (t) => t.blocked },
  { label: "AI calls", value: (t) => t.llm_calls },
  { label: "Tokens", value: (t) => t.total_tokens },
];

function Note({ text }: { text: string | undefined }) {
  return text ? <p className="text-sm leading-relaxed text-muted-foreground">{text}</p> : null;
}

function count(value: number): string {
  return value.toLocaleString("en-US");
}

/** "1 conversation", never "1 conversations". */
function plural(value: number, one: string, many: string): string {
  return value === 1 ? one : many;
}

/** "3 questions" — a count and its word, for the phone's sentences. */
function counted(value: number, one: string, many: string): string {
  return `${count(value)} ${plural(value, one, many)}`;
}

/** A measured cost, to the cent — or to a tenth of a cent when it is that small. */
function money(cost: Cost): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(Number(cost.usd));
}
