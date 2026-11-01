/**
 * Links (NEURA-GROW, ADR-0074; console.md §3.15, board 81, approved 2026-11-01).
 *
 * Links that count their clicks: **your own** (any product, any day, D18), and
 * **your campaigns'** (the links copied from a plan's posts), with the clicks
 * each brought. A click is one tap on a link, never a person and never a sale
 * (ADR-0074 §5). **The Owner and Support** (R115).
 *
 * A campaign's clicks stay after its plan is deleted, 30 days after its date
 * (R116); *See the plan* shows only while the plan is kept.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { CouldNotLoad } from "@/components/calendar/notes";
import { LinkActions } from "@/components/links/link-actions";
import { NotThisShopsLinks, TITLE } from "@/components/links/notes";
import { NotAllowed } from "@/components/not-allowed";
import { When } from "@/components/when";
import { longDay, planHref } from "@/lib/calendar";
import {
  PLACE_NAME,
  POST_NAME,
  clicksByPlace,
  clicksWord,
  type Campaign,
  type LinksPage as Data,
  type OwnLink,
} from "@/lib/links";
import { PERMISSION, refusal } from "@/lib/roles";
import { fromApi, hasSession } from "@/lib/server-api";
import { hasGrow, shopAssistants } from "@/lib/shop-assistants";
import { Button } from "@/components/ui/button";

export default async function LinksPage({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const refused = await refusal(tenantId, PERMISSION.links);
  if (refused) return <NotAllowed refusal={refused} what={TITLE} />;
  if (!hasGrow(await shopAssistants(tenantId))) return <NotThisShopsLinks />;

  const shop = encodeURIComponent(tenantId);
  const result = await fromApi<Data>(`/shops/${shop}/links`);

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">{TITLE}</h1>
          <p className="max-w-3xl leading-relaxed text-muted-foreground">
            Links that count their clicks. Paste one with a post, and see how many people tapped it
            to open your shop. We count clicks only, never who clicked.
          </p>
        </div>
        <Button
          className="h-11 self-start px-4 sm:h-10 sm:shrink-0"
          nativeButton={false}
          data-make-a-link
          render={<Link href={`/console/${shop}/links/new`} />}
        >
          Make a link
        </Button>
      </div>

      {!result.ok ? (
        <CouldNotLoad status={result.status} message={result.message} />
      ) : (
        <>
          <section className="space-y-3" aria-labelledby="your-links">
            <h2 id="your-links" className="text-[17px] font-semibold">
              Your links
            </h2>
            {result.data.own.length ? (
              <ul data-own-links className="divide-y overflow-hidden rounded-xl border">
                {result.data.own.map((link) => (
                  <OwnRow key={link.id} tenantId={tenantId} link={link} />
                ))}
              </ul>
            ) : (
              <p
                data-no-links
                className="rounded-xl border px-4 py-4 text-sm text-muted-foreground sm:px-5"
              >
                No links yet. Make one for any product, or copy one from a campaign plan.
              </p>
            )}
          </section>

          {result.data.campaigns.length ? (
            <section className="space-y-3" aria-labelledby="campaigns">
              <h2 id="campaigns" className="text-[17px] font-semibold">
                From your campaigns
              </h2>
              {result.data.campaigns.map((campaign) => (
                <CampaignCard
                  key={`${campaign.date_key}:${campaign.day}`}
                  tenantId={tenantId}
                  campaign={campaign}
                />
              ))}
            </section>
          ) : null}

          <p className="max-w-3xl text-[13px] leading-relaxed text-muted-foreground">
            A click is one tap on a link: one person tapping twice counts twice. Facebook&apos;s and
            WhatsApp&apos;s link previews are not counted. If your shop uses a website analytics
            tool, like Google Analytics, it also sees each click&apos;s campaign and post. Remove
            deletes a link&apos;s clicks; the link keeps opening its product, so old posts never
            break.
          </p>
        </>
      )}
    </>
  );
}

function OwnRow({ tenantId, link }: { tenantId: string; link: OwnLink }) {
  return (
    <li
      data-own-link={link.id}
      className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
    >
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-semibold break-words">{link.name}</p>
        <p className="text-[13px] text-muted-foreground">
          {link.product_title ?? "A product no longer in your synced catalogue"} ·{" "}
          {PLACE_NAME[link.place]} · made <When iso={link.made_at} day />
        </p>
      </div>
      <p data-clicks className="shrink-0 text-[15px] sm:w-28 sm:text-right">
        <strong className="font-semibold">{link.clicks.toLocaleString("en")}</strong>{" "}
        {link.clicks === 1 ? "click" : "clicks"}
      </p>
      <LinkActions tenantId={tenantId} linkId={link.id} link={link.link} name={link.name} />
    </li>
  );
}

function CampaignCard({ tenantId, campaign }: { tenantId: string; campaign: Campaign }) {
  const year = campaign.day.slice(0, 4);
  return (
    <div data-campaign={campaign.date_key} className="overflow-hidden rounded-xl border">
      <div className="flex flex-col gap-3 border-b bg-muted/40 px-4 py-3.5 sm:flex-row sm:items-center sm:px-5">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="font-semibold break-words">
            {campaign.name} {year}
          </p>
          <p className="text-[13px] text-muted-foreground">
            {longDay(campaign.day)} ·{" "}
            {campaign.plan_id
              ? "the links in your plan’s posts"
              : "its plan was deleted; the clicks stay here"}
          </p>
        </div>
        {campaign.plan_id ? (
          <Button
            variant="outline"
            className="h-11 self-start px-4 sm:h-10 sm:self-auto"
            nativeButton={false}
            data-see-the-plan
            render={<Link href={planHref(tenantId, campaign.plan_id)} />}
          >
            See the plan
          </Button>
        ) : null}
      </div>
      <ul className="divide-y">
        {campaign.posts.map((post) => {
          const counted = clicksByPlace(post.places);
          return (
            <li
              key={post.post}
              data-campaign-post={post.post}
              className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 sm:flex-nowrap sm:px-5"
            >
              <span className="w-28 shrink-0 font-medium">{POST_NAME[post.post]}</span>
              <span className="min-w-0 flex-1 text-sm text-foreground/80">
                {counted
                  ? post.post === "email"
                    ? "One link"
                    : counted.map(([place, n]) => `${PLACE_NAME[place]} ${n}`).join(" · ")
                  : "No clicks yet"}
              </span>
              {post.clicks ? (
                <span className="shrink-0 text-[15px] sm:w-28 sm:text-right">
                  <strong className="font-semibold">{post.clicks.toLocaleString("en")}</strong>{" "}
                  {post.clicks === 1 ? "click" : "clicks"}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
      <p className="sr-only">{clicksWord(campaign.clicks)} in all</p>
    </div>
  );
}
