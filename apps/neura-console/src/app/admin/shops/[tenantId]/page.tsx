/**
 * One shop, as an admin sees it (ADR-0061, board 47): its facts, and for a shop
 * waiting for approval, **Approve** with its assistants or **Refuse**.
 *
 * A shop that is not waiting shows its facts, and the features FiveNeurals may
 * switch off for it (ADR-0065, board 61): only those of assistants it has.
 */
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { AdminStateBadge } from "@/components/admin/admin-parts";
import { DecideShop } from "@/components/admin/decide-shop";
import { FeatureSwitches } from "@/components/admin/feature-switches";
import { assistantsShort, day, type AdminShop } from "@/lib/admin";
import { fromApi } from "@/lib/server-api";

export default async function AdminShopPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const result = await fromApi<{ shop: AdminShop }>(
    `/shops/${encodeURIComponent(tenantId)}`,
    "/v1/admin",
  );

  return (
    <div className="max-w-2xl space-y-6">
      <Link
        href="/admin"
        className="inline-flex items-center gap-1.5 text-sm text-foreground/80 hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Shops
      </Link>
      {result.ok ? (
        <Shop shop={result.data.shop} />
      ) : (
        <p className="text-sm text-muted-foreground">{result.message}</p>
      )}
    </div>
  );
}

function Shop({ shop }: { shop: AdminShop }) {
  const waiting = shop.status === "waiting";
  return (
    <>
      <div className="space-y-2.5">
        <h1 className="text-2xl font-semibold tracking-tight break-words md:text-[28px]">
          {shop.name}
        </h1>
        <AdminStateBadge shop={shop} />
      </div>

      <dl className="divide-y border-b text-sm" data-shop-facts>
        <Fact label="Website">
          {shop.website ? (
            <>
              <a
                href={shop.website}
                target="_blank"
                rel="noreferrer"
                className="break-all underline underline-offset-3"
              >
                {shop.website}
              </a>{" "}
              <span className="text-muted-foreground">(opens in a new tab)</span>
            </>
          ) : (
            <span className="text-muted-foreground">None given</span>
          )}
        </Fact>
        <Fact label={shop.owners.length > 1 ? "Owners" : "Owner"}>
          <span className="break-all">{shop.owners.join(", ") || "Nobody"}</span>
        </Fact>
        <Fact label={waiting ? "Signed up" : "Since"}>{day(shop.since, true)}</Fact>
        {waiting ? null : (
          <Fact label="Assistants">{assistantsShort(shop.assistants) || "None"}</Fact>
        )}
        <Fact label="Shop id">
          <span className="font-mono text-[13px] break-all">{shop.tenant_id}</span>
        </Fact>
      </dl>

      {waiting ? (
        <>
          <p className="text-sm text-foreground/80">
            Look at the website before you decide: is it a real shop that sells things?
          </p>
          <DecideShop tenantId={shop.tenant_id} name={shop.name} owners={shop.owners} />
        </>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            This shop is not waiting for approval, so there is nothing to decide here.
          </p>
          {shop.switches?.length ? (
            <FeatureSwitches tenantId={shop.tenant_id} name={shop.name} switches={shop.switches} />
          ) : null}
        </>
      )}
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 py-3 sm:flex-row sm:gap-4">
      <dt className="w-36 shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}
