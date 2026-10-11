/**
 * AI use and cost across every shop (ADR-0061, board 48).
 *
 * The same counts each shop sees on its own Usage screen, added up: totals, by
 * shop, by assistant, and the rows add up to the totals. **Cost is said as a
 * number only when something was priced**; otherwise *Not priced*, with why.
 */
import Link from "next/link";
import { assistantName } from "@/lib/assistants";
import { count, money, type AdminUsage, type Counts } from "@/lib/admin";
import { fromApi } from "@/lib/server-api";
import { cn } from "@/lib/utils";

const PERIODS: { key: string; label: string; within: string }[] = [
  { key: "today", label: "Today", within: "today" },
  { key: "7d", label: "7 days", within: "in these 7 days" },
  { key: "30d", label: "30 days", within: "in these 30 days" },
];

export default async function AdminUsagePage({
  searchParams,
}: {
  searchParams: Promise<{ period?: string }>;
}) {
  const asked = (await searchParams).period;
  const period = PERIODS.find((p) => p.key === asked) ?? PERIODS[2];
  const result = await fromApi<AdminUsage>(`/usage?period=${period.key}`, "/v1/admin");

  return (
    <>
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end">
        <div className="flex-1 space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight md:text-[28px]">AI use and cost</h1>
          <p className="text-muted-foreground">
            Across every shop. The same counts each shop sees on its own Usage screen.
          </p>
        </div>
        <nav aria-label="Period" className="flex gap-2">
          {PERIODS.map((p) => (
            <Link
              key={p.key}
              href={`/admin/usage?period=${p.key}`}
              aria-current={p.key === period.key ? "page" : undefined}
              className={cn(
                "inline-flex h-11 items-center rounded-lg px-3.5 text-sm sm:h-9",
                p.key === period.key
                  ? "bg-foreground font-medium text-background"
                  : "border hover:bg-muted",
              )}
            >
              {p.label}
            </Link>
          ))}
        </nav>
      </header>

      {result.ok ? (
        <Usage usage={result.data} within={period.within} />
      ) : (
        <p className="text-sm text-destructive">{result.message}</p>
      )}
    </>
  );
}

function Usage({ usage, within }: { usage: AdminUsage; within: string }) {
  const { totals } = usage;
  const quiet = usage.shops_without_use;
  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" data-usage-totals>
        <Tile value={count(totals.conversations)} label="chats" />
        <Tile value={count(totals.turns)} label="questions" />
        <Tile value={count(totals.escalations)} label="handed to a person" />
        <Tile value={count(totals.llm_calls)} label="AI calls" />
        <Tile value={count(totals.total_tokens)} label="tokens" />
        {totals.cost.measured ? (
          <Tile value={money(totals.cost)} label="cost" />
        ) : (
          <Tile value="Not priced" label="cost" muted />
        )}
      </div>

      <section aria-labelledby="by-shop" className="space-y-3">
        <h2 id="by-shop" className="text-lg font-semibold">
          By shop
        </h2>
        {usage.by_shop.length ? (
          <Table
            first="Shop"
            rows={usage.by_shop.map((row) => ({
              key: row.tenant_id,
              label: row.name ?? row.tenant_id,
              counts: row,
            }))}
          />
        ) : null}
        {quiet ? (
          <p className="text-[13px] text-muted-foreground">
            {quiet === 1 ? "1 shop had" : `${count(quiet)} shops had`} no AI use {within}.
          </p>
        ) : null}
      </section>

      {usage.by_assistant.length ? (
        <section aria-labelledby="by-assistant" className="space-y-3">
          <h2 id="by-assistant" className="text-lg font-semibold">
            By assistant
          </h2>
          <Table
            first="Assistant"
            rows={usage.by_assistant.map((row) => ({
              key: row.agent_key,
              label: assistantName(row.agent_key),
              counts: row,
            }))}
          />
          <p className="text-[13px] text-muted-foreground">The rows add up to the totals above.</p>
        </section>
      ) : null}

      <div className="rounded-xl border border-dashed px-4 py-3.5 text-sm leading-relaxed text-foreground/80">
        <strong className="font-semibold">Why &quot;Not priced&quot;.</strong> The AI model in use
        has no price set in NEURA, so no cost is recorded, and a free local model records none
        either. NEURA never shows that as $0.00. The real amount is on the AI provider&apos;s own
        bill.
      </div>
    </>
  );
}

function Tile({ value, label, muted = false }: { value: string; label: string; muted?: boolean }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-xl px-4 py-3.5",
        muted ? "border border-dashed bg-muted/30" : "border",
      )}
    >
      <span
        className={cn(
          "text-2xl font-semibold tabular-nums",
          muted ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {value}
      </span>
      <span className="text-[13px] text-muted-foreground">{label}</span>
    </div>
  );
}

type Row = { key: string; label: string; counts: Counts };

const COLUMNS: { label: string; value: (c: Counts) => string }[] = [
  { label: "Chats", value: (c) => count(c.conversations) },
  { label: "Questions", value: (c) => count(c.turns) },
  { label: "Handed to a person", value: (c) => count(c.escalations) },
  { label: "AI calls", value: (c) => count(c.llm_calls) },
  { label: "Tokens", value: (c) => count(c.total_tokens) },
];

function cost(c: Counts): string {
  return c.cost.measured ? money(c.cost) : "not priced";
}

function Table({ first, rows }: { first: string; rows: Row[] }) {
  return (
    <>
      <div className="hidden overflow-hidden rounded-xl border md:block">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b text-[13px] text-muted-foreground">
              <th className="px-3.5 py-2.5 text-left font-medium">{first}</th>
              {COLUMNS.map((column) => (
                <th key={column.label} className="px-3.5 py-2.5 text-right font-medium">
                  {column.label}
                </th>
              ))}
              <th className="px-3.5 py-2.5 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-b last:border-b-0">
                <td className="px-3.5 py-3 font-medium">{row.label}</td>
                {COLUMNS.map((column) => (
                  <td key={column.label} className="px-3.5 py-3 text-right tabular-nums">
                    {column.value(row.counts)}
                  </td>
                ))}
                <td className="px-3.5 py-3 text-right text-muted-foreground">{cost(row.counts)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="space-y-2.5 md:hidden">
        {rows.map((row) => (
          <li key={row.key} className="space-y-1 rounded-xl border px-4 py-3.5">
            <p className="font-semibold break-words">{row.label}</p>
            <p className="text-[13px] leading-snug text-muted-foreground">
              {COLUMNS.map((column) => `${column.label} ${column.value(row.counts)}`).join(" · ")}
              {` · cost ${cost(row.counts)}`}
            </p>
          </li>
        ))}
      </ul>
    </>
  );
}
