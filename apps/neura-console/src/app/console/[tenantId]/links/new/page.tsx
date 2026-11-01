/**
 * Make a link (NEURA-GROW, ADR-0074 D18; console.md §3.15, board 82, approved
 * 2026-11-01): a counted link for any product, any day. **The Owner and
 * Support** (R115).
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { MakeLink } from "@/components/links/make-link";
import { NotThisShopsLinks, TITLE } from "@/components/links/notes";
import { NotAllowed } from "@/components/not-allowed";
import { PERMISSION, refusal } from "@/lib/roles";
import { hasSession } from "@/lib/server-api";
import { hasGrow, shopAssistants } from "@/lib/shop-assistants";

export default async function MakeALinkPage({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const refused = await refusal(tenantId, PERMISSION.links);
  if (refused) return <NotAllowed refusal={refused} what={TITLE} />;
  if (!hasGrow(await shopAssistants(tenantId))) return <NotThisShopsLinks />;

  const back = `/console/${encodeURIComponent(tenantId)}/links`;
  return (
    <>
      <Link
        href={back}
        className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {TITLE}
      </Link>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Make a link</h1>
        <p className="max-w-3xl leading-relaxed text-muted-foreground">
          Pick a product and where you&apos;ll post it. You get a link that counts its clicks.
        </p>
      </div>
      <MakeLink tenantId={tenantId} back={back} />
      <p className="max-w-3xl text-[13px] text-muted-foreground">
        A link can only open your own shop&apos;s product pages.
      </p>
    </>
  );
}
