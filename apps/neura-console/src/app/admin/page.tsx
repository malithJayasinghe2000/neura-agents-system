/**
 * Shops: every shop on NEURA, and its state (ADR-0061, board 46; phone board 49).
 *
 * Waiting shops first, each with *Look and decide*; then every shop, waiting
 * first and then the newest, with its last 7 days. **Facts only**: the API can
 * return nothing about a shopper. Cost is *Not priced* or *No AI use*, never
 * $0.00 (console.md §3.5's rule).
 */
import Link from "next/link";
import { AdminStateBadge } from "@/components/admin/admin-parts";
import {
  assistantsShort,
  bareWebsite,
  costWords,
  day,
  type AdminShop,
  type AdminShops,
} from "@/lib/admin";
import { fromApi } from "@/lib/server-api";

export default async function AdminShopsPage() {
  const result = await fromApi<AdminShops>("/shops", "/v1/admin");
  if (!result.ok) {
    return <p className="text-sm text-destructive">{result.message}</p>;
  }
  const { shops } = result.data;
  const waiting = shops.filter((shop) => shop.status === "waiting");

  return (
    <>
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight md:text-[28px]">Shops</h1>
        <p className="text-muted-foreground">
          Every shop on NEURA, and its state. Facts about shops only: no shopper&apos;s chat or
          details are shown here.
        </p>
      </header>

      {waiting.length ? (
        <section aria-labelledby="waiting" className="space-y-3">
          <h2 id="waiting" className="text-lg font-semibold">
            Waiting for approval · {waiting.length}
          </h2>
          {waiting.map((shop) => (
            <div
              key={shop.tenant_id}
              className="flex flex-col gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-4 sm:flex-row sm:items-center sm:px-5 dark:border-amber-800 dark:bg-amber-950/40"
              data-waiting-shop={shop.tenant_id}
            >
              <div className="min-w-0 flex-1 space-y-1">
                <p className="font-semibold break-words">{shop.name}</p>
                <p className="text-sm break-words text-foreground/80">
                  {[bareWebsite(shop.website), `signed up ${day(shop.since, true)}`]
                    .filter(Boolean)
                    .join(" · ")}
                  {shop.owners.length ? ` by ${shop.owners.join(", ")}` : ""}
                </p>
              </div>
              <Link
                href={`/admin/shops/${encodeURIComponent(shop.tenant_id)}`}
                className="inline-flex h-11 shrink-0 items-center justify-center rounded-lg bg-foreground px-4 text-sm font-medium text-background hover:bg-foreground/85 sm:h-10"
              >
                Look and decide
              </Link>
            </div>
          ))}
        </section>
      ) : null}

      <section aria-labelledby="all" className="space-y-3">
        <h2 id="all" className="text-lg font-semibold">
          All shops · {shops.length}
        </h2>

        <div className="hidden overflow-hidden rounded-xl border md:block">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b text-left text-[13px] text-muted-foreground">
                <th className="px-3.5 py-2.5 font-medium">Shop</th>
                <th className="px-3.5 py-2.5 font-medium">State</th>
                <th className="px-3.5 py-2.5 font-medium">Assistants</th>
                <th className="px-3.5 py-2.5 font-medium">Shop connected</th>
                <th className="px-3.5 py-2.5 text-right font-medium">Chats, 7 days</th>
                <th className="px-3.5 py-2.5 font-medium">AI cost, 7 days</th>
                <th className="px-3.5 py-2.5 font-medium">Since</th>
              </tr>
            </thead>
            <tbody>
              {shops.map((shop) => (
                <ShopRow key={shop.tenant_id} shop={shop} />
              ))}
            </tbody>
          </table>
        </div>

        <ul className="space-y-2.5 md:hidden">
          {shops.map((shop) => (
            <li key={shop.tenant_id}>
              <ShopCard shop={shop} />
            </li>
          ))}
        </ul>

        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Chats and AI cost are for the last 7 days.{" "}
          <strong className="font-semibold text-foreground/80">Not priced</strong>: the AI model in
          use has no price set, so NEURA records no cost. The full numbers are on{" "}
          <Link href="/admin/usage" className="underline underline-offset-2">
            AI use and cost
          </Link>
          .
        </p>
      </section>
    </>
  );
}

function ShopRow({ shop }: { shop: AdminShop }) {
  const waiting = shop.status === "waiting";
  const dim = "text-muted-foreground";
  return (
    <tr className="border-b last:border-b-0 hover:bg-muted/40" data-shop={shop.tenant_id}>
      <td className="px-3.5 py-3 align-middle">
        {waiting ? (
          <Link
            href={`/admin/shops/${encodeURIComponent(shop.tenant_id)}`}
            className="font-semibold underline underline-offset-3"
          >
            {shop.name}
          </Link>
        ) : (
          <span className="font-medium">{shop.name}</span>
        )}
        {waiting && shop.website ? (
          <span className="mt-0.5 block text-[13px] text-muted-foreground">
            {bareWebsite(shop.website)}
          </span>
        ) : null}
      </td>
      <td className="px-3.5 py-3">
        <AdminStateBadge shop={shop} />
      </td>
      <td className={`px-3.5 py-3 ${shop.assistants.length ? "" : dim}`}>
        {shop.assistants.length ? assistantsShort(shop.assistants) : "None yet"}
      </td>
      <td className={`px-3.5 py-3 ${shop.connected ? "" : dim}`}>
        {shop.connected ? "Yes" : "Not yet"}
      </td>
      <td className={`px-3.5 py-3 text-right tabular-nums ${shop.chats_7d ? "" : dim}`}>
        {shop.chats_7d}
      </td>
      <td className={`px-3.5 py-3 ${shop.ai_calls_7d ? "" : dim}`}>
        {costWords(shop.cost_7d, shop.ai_calls_7d)}
      </td>
      <td className={`px-3.5 py-3 ${dim}`}>{day(shop.since)}</td>
    </tr>
  );
}

function ShopCard({ shop }: { shop: AdminShop }) {
  const facts = [
    shop.assistants.length ? assistantsShort(shop.assistants) : "no assistant yet",
    shop.connected ? "connected" : "not connected yet",
    `${shop.chats_7d} ${shop.chats_7d === 1 ? "chat" : "chats"} in 7 days`,
    shop.ai_calls_7d ? `AI cost ${costWords(shop.cost_7d, shop.ai_calls_7d).toLowerCase()}` : "",
    `since ${day(shop.since)}`,
  ].filter(Boolean);
  const body = (
    <>
      <span className="flex items-start justify-between gap-2">
        <span className="font-semibold break-words">{shop.name}</span>
        <AdminStateBadge shop={shop} />
      </span>
      <span className="text-[13px] leading-snug text-muted-foreground">{facts.join(" · ")}</span>
    </>
  );
  const className = "flex flex-col gap-2 rounded-xl border px-4 py-3.5";
  return shop.status === "waiting" ? (
    <Link
      href={`/admin/shops/${encodeURIComponent(shop.tenant_id)}`}
      className={`${className} hover:bg-muted/40`}
    >
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}
