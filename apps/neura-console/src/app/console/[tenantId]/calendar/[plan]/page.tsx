/**
 * One campaign plan (ADR-0072 §5; console.md §3.14, board 76, approved 2026-11-01).
 *
 * **What comes from where** (ADR-0072 §5): the theme, the idea and the drafts
 * are the AI's words, after the checks in code (§6); the facts under *Act on
 * this first* and their counts come from the stored plan; the products' names,
 * photos, prices and links from the synced catalogue; the days under *When to
 * post* are worked out in code. Nothing here is posted or sent: the owner edits,
 * copies and posts it themselves.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowLeft, ExternalLink, ImageIcon, Link as LinkIcon, LoaderCircle } from "lucide-react";
import { ChangeProducts, SoldOutNow } from "@/components/calendar/change-products";
import { DraftCard } from "@/components/calendar/draft-card";
import { PostLinks } from "@/components/links/post-links";
import { MakeAgain, WhileMaking } from "@/components/calendar/make-again";
import { CouldNotLoad, NotThisShopsPlan, PausedNote, TITLE } from "@/components/calendar/notes";
import { NotAllowed } from "@/components/not-allowed";
import { longDay, shortDay, type Plan, type PlanFact, type PlanProduct } from "@/lib/calendar";
import { PERMISSION, refusal } from "@/lib/roles";
import { fromApi, hasSession } from "@/lib/server-api";
import { hasGrow, shopAssistants } from "@/lib/shop-assistants";
import { money } from "@/lib/suggestions";
import { Button } from "@/components/ui/button";

export default async function PlanPage({
  params,
}: {
  params: Promise<{ tenantId: string; plan: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId, plan: planId } = await params;
  const refused = await refusal(tenantId, PERMISSION.calendar);
  if (refused) return <NotAllowed refusal={refused} what={TITLE} />;
  if (!hasGrow(await shopAssistants(tenantId))) return <NotThisShopsPlan />;

  const shop = encodeURIComponent(tenantId);
  const result = await fromApi<Plan>(`/shops/${shop}/calendar/plans/${encodeURIComponent(planId)}`);
  const back = (
    <Link
      href={`/console/${shop}/calendar`}
      className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-4" aria-hidden />
      {TITLE}
    </Link>
  );

  if (!result.ok) {
    return (
      <>
        {back}
        {result.status === 404 && result.message === "No such plan." ? (
          <section className="max-w-xl space-y-2 rounded-xl border px-5 py-5">
            <h1 className="text-lg font-semibold">This plan is gone</h1>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Its date was removed, or the plan was deleted 30 days after its date.
            </p>
          </section>
        ) : (
          <CouldNotLoad status={result.status} message={result.message} />
        )}
      </>
    );
  }

  const plan = result.data;
  const year = Number(plan.today.slice(0, 4));
  const made = plan.made_on
    ? plan.made_on === plan.today
      ? "today"
      : `on ${shortDay(plan.made_on, year)}`
    : null;
  const day = (step: Plan["schedule"][number]["step"]) =>
    plan.schedule.find((s) => s.step === step)?.day ?? plan.day;
  // A post's link opens one of the plan's products that has a page (R110).
  const linkable = plan.products
    .filter((product) => product.url)
    .map((product) => ({ product_id: product.product_id, title: product.title ?? null }));
  const dayBefore = new Date(`${plan.day}T00:00:00Z`);
  dayBefore.setUTCDate(dayBefore.getUTCDate() - 1);

  return (
    <>
      {back}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight break-words">
            {plan.name} · {longDay(plan.day, year)}
          </h1>
          {made ? (
            <p className="max-w-3xl leading-relaxed text-muted-foreground">
              Your plan, made {made} by your assistant from your shop&apos;s own data.
            </p>
          ) : null}
        </div>
        {plan.can_make_again && plan.has_plan ? (
          <MakeAgain
            tenantId={tenantId}
            planId={plan.id}
            edited={plan.edited.length > 0}
            className="sm:shrink-0"
          />
        ) : null}
      </div>

      {plan.paused_since ? <PausedNote since={plan.paused_since} /> : null}

      {plan.state === "making" ? (
        <div
          role="status"
          data-making
          className="flex items-start gap-3 rounded-xl border bg-muted/40 px-4 py-4 sm:px-5"
        >
          <LoaderCircle
            className="mt-0.5 size-[18px] shrink-0 animate-spin motion-reduce:animate-none"
            aria-hidden
          />
          <div className="space-y-1">
            <p className="text-sm font-semibold">Making a new plan</p>
            <p className="text-sm leading-relaxed text-foreground/80">
              Your assistant is writing it now. It takes about a minute, and it shows here when it
              is ready.
            </p>
          </div>
          <WhileMaking />
        </div>
      ) : null}

      {!plan.has_plan && plan.state === "failed" ? (
        <section
          data-plan-failed
          className="max-w-3xl space-y-3 rounded-xl border border-red-300 bg-red-50 px-4 py-4 sm:px-5 dark:border-red-900 dark:bg-red-950/40"
        >
          <h2 className="font-semibold">Your plan could not be made</h2>
          <p className="text-sm leading-relaxed text-foreground/80">
            Your assistant wrote it twice, and both times it held words we don&apos;t let through,
            such as a price, a health claim or a phone number. Make it again to try once more.
          </p>
          {plan.can_make_again ? <MakeAgain tenantId={tenantId} planId={plan.id} /> : null}
        </section>
      ) : null}

      {plan.has_plan && plan.failed && plan.state !== "making" ? (
        <p
          role="status"
          className="max-w-3xl rounded-xl border bg-muted/40 px-4 py-3 text-sm sm:px-5"
        >
          A new plan could not be made just now. This is your earlier plan.
        </p>
      ) : null}

      {plan.has_plan ? (
        <>
          <section className="space-y-3" aria-labelledby="idea">
            <h2 id="idea" className="text-[17px] font-semibold">
              The idea
            </h2>
            <div className="space-y-1.5 rounded-xl border px-4 py-4 sm:px-5">
              <p className="font-semibold">{plan.theme}</p>
              <p className="leading-relaxed text-foreground/85">{plan.idea}</p>
            </div>
          </section>

          <section className="space-y-3" aria-labelledby="act-on">
            <h2 id="act-on" className="text-[17px] font-semibold">
              Act on this first
            </h2>
            {plan.act_on.length ? (
              <>
                <p className="text-sm text-muted-foreground">
                  From what your shoppers asked in the last 30 days.
                </p>
                <ul className="divide-y overflow-hidden rounded-xl border">
                  {plan.act_on.map((fact) => (
                    <ActOn
                      key={`${fact.kind}:${fact.label}`}
                      tenantId={tenantId}
                      fact={fact}
                      launch={shortDay(day("launch"), year)}
                      links={plan.links}
                    />
                  ))}
                </ul>
              </>
            ) : (
              <p data-products-alone className="text-sm text-muted-foreground">
                {/* G125: say why there is nothing, not that shoppers asked nothing. */}
                {plan.facts_given === 0
                  ? "Your shoppers haven't asked about anything for this yet, so this plan is from your products alone."
                  : "Nothing your shoppers asked fits this date, so this plan is from your products alone."}
              </p>
            )}
          </section>

          {plan.products.length ? (
            <section className="space-y-3" aria-labelledby="products">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="space-y-0.5">
                  <h2 id="products" className="text-[17px] font-semibold">
                    Products to show
                  </h2>
                  {plan.owner_products ? (
                    <p data-chosen-by-you className="text-[13px] text-muted-foreground">
                      Chosen by you. Make it again keeps them.
                    </p>
                  ) : null}
                </div>
                {plan.can_make_again ? (
                  <ChangeProducts
                    tenantId={tenantId}
                    planId={plan.id}
                    edited={plan.edited.length > 0}
                    current={plan.products.map((product) => ({
                      product_id: product.product_id,
                      title: product.title,
                      in_stock: product.in_stock !== false,
                    }))}
                  />
                ) : null}
              </div>
              <ul className="grid gap-3 sm:grid-cols-3">
                {plan.products.map((product) => (
                  <ProductCard key={product.product_id} product={product} />
                ))}
              </ul>
              {plan.catalogue_cut ? (
                <p className="text-[13px] text-muted-foreground">
                  Your shop has more than 100 products in stock. Your assistant chose from 100 of
                  them.
                </p>
              ) : null}
            </section>
          ) : null}

          <section className="space-y-3" aria-labelledby="when">
            <h2 id="when" className="text-[17px] font-semibold">
              When to post
            </h2>
            <ul data-schedule className="divide-y overflow-hidden rounded-xl border">
              {/* In date order: a plan made late is ready after its teaser's day. */}
              {[...plan.schedule]
                .sort((a, b) => a.day.localeCompare(b.day))
                .map((step) => (
                  <li
                    key={step.step}
                    data-step={step.step}
                    className="flex items-center gap-4 px-4 py-3 sm:px-5"
                  >
                    <span className="w-16 shrink-0 text-sm font-semibold">
                      {shortDay(step.day, year)}
                    </span>
                    <span className="min-w-0 flex-1 text-sm">
                      {stepWords(step.step, plan.name)}
                    </span>
                    <span className="shrink-0 text-[13px] text-muted-foreground">
                      {stepLabel(step, plan.today, day("ready"))}
                    </span>
                  </li>
                ))}
            </ul>
          </section>

          <section className="space-y-3" aria-labelledby="drafts">
            <div className="space-y-1">
              <h2 id="drafts" className="text-[17px] font-semibold">
                Draft texts
              </h2>
              <p className="text-sm text-muted-foreground">
                Fill in [your offer] yourself. Edit any word, then copy it into your own Facebook,
                Instagram or email tool.
              </p>
            </div>
            {plan.post_links ? (
              <div
                data-links-intro
                className="flex items-start gap-3 rounded-xl border bg-muted/40 px-4 py-3.5 sm:px-5"
              >
                <LinkIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
                <div className="space-y-1">
                  <p className="text-sm font-semibold">Each post has its own links</p>
                  <p className="text-sm leading-relaxed text-foreground/80">
                    Paste the link with the post. When someone taps it, we count the click and open
                    the product on your shop, so you can see which post brought people. On Instagram
                    a link inside a post can&apos;t be tapped: put the Instagram link in your bio or
                    a story.
                  </p>
                </div>
              </div>
            ) : null}
            <div className="space-y-3">
              {(
                [
                  ["teaser", "Teaser post", `For ${shortDay(day("teaser"), year)}`],
                  ["launch", "Launch post", `For ${shortDay(day("launch"), year)}`],
                  ["last_chance", "Last chance post", `For ${shortDay(day("last_chance"), year)}`],
                  [
                    "email",
                    "Email",
                    `For ${shortDay(day("launch"), year)}, from your own email tool`,
                  ],
                  [
                    "banner",
                    "Banner",
                    `For your home page, ${shortDay(day("launch"), year)} to ${shortDay(
                      dayBefore.toISOString().slice(0, 10),
                      year,
                    )}`,
                  ],
                ] as const
              ).map(([kind, title, when]) => (
                <DraftCard
                  key={kind}
                  tenantId={tenantId}
                  planId={plan.id}
                  kind={kind}
                  title={title}
                  when={when}
                  text={(kind === "email" ? plan.texts.email_body : plan.texts[kind]) ?? ""}
                  subject={kind === "email" ? (plan.texts.email_subject ?? "") : undefined}
                  editable={plan.state !== "making"}
                >
                  {plan.post_links === null ? null : kind === "banner" ? (
                    <div data-banner-no-link className="border-t pt-3">
                      <p className="text-[13px] leading-relaxed text-muted-foreground">
                        No counted link here: whoever sees your banner is already in your shop. Link
                        it to your product as you usually do.
                      </p>
                    </div>
                  ) : (
                    <PostLinks
                      tenantId={tenantId}
                      planId={plan.id}
                      post={kind}
                      products={linkable}
                      current={plan.post_links[kind]}
                    />
                  )}
                </DraftCard>
              ))}
            </div>
          </section>

          <p className="max-w-3xl text-[13px] leading-relaxed text-muted-foreground">
            Written by AI from your shop&apos;s data. Check every word before you post it: your shop
            publishes it under its own name. We never post or send anything.
            {plan.post_links
              ? " The links are made by your dashboard, not by AI, and count clicks only, never who clicked."
              : null}
          </p>
        </>
      ) : null}
    </>
  );
}

function stepWords(step: Plan["schedule"][number]["step"], name: string): string {
  return {
    ready: "Your plan is ready",
    teaser: "Post the teaser",
    launch: "Post the launch and send the email",
    last_chance: "Post the last chance",
    day: name,
  }[step];
}

/**
 * *Done* for a day passed, *Today*, or how long before the date (board 76).
 * A step whose day passed before the plan was made says *Passed*: nobody did
 * it, so *Done* would not be true (a date kept late, R94).
 */
function stepLabel(step: Plan["schedule"][number], today: string, ready: string): string {
  if (step.step === "ready") return step.day <= today ? "Done" : "";
  if (step.day < today) return step.day < ready ? "Passed" : "Done";
  if (step.day === today) return "Today";
  return {
    teaser: "2 weeks before",
    launch: "1 week before",
    last_chance: "2 days before",
    day: "",
  }[step.step];
}

function ActOn({
  tenantId,
  fact,
  launch,
  links,
}: {
  tenantId: string;
  fact: PlanFact;
  launch: string;
  links: Plan["links"];
}) {
  const shop = `/console/${encodeURIComponent(tenantId)}`;
  const count = <strong className="font-semibold">{fact.shoppers} shoppers</strong>;
  const link =
    fact.kind === "wanted"
      ? links.wanted
        ? { href: `${shop}/wanted`, label: "See Shoppers asked for" }
        : null
      : links.gaps
        ? { href: `${shop}/gaps`, label: "See Missing from your pages" }
        : null;
  return (
    <li
      data-act-on={fact.kind}
      className="flex flex-col gap-2 px-4 py-3.5 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
    >
      <p className="min-w-0 flex-1 text-sm leading-relaxed">
        {fact.kind === "wanted" ? (
          <>
            {count} asked for &ldquo;{fact.label}&rdquo; in the last 30 days. You don&apos;t sell
            it: consider adding it before {launch}.
          </>
        ) : fact.product_id ? (
          <>
            {count} asked about &ldquo;{fact.label}&rdquo; for {fact.product_title ?? "a product"}.
            Your page doesn&apos;t say. Add it before you promote it.
          </>
        ) : (
          <>
            {count} asked about &ldquo;{fact.label}&rdquo;. Your shop&apos;s pages don&apos;t say.
            Add it before you promote it.
          </>
        )}
      </p>
      {link ? (
        <Link
          href={link.href}
          className="inline-flex min-h-10 items-center text-sm font-medium whitespace-nowrap underline underline-offset-3"
        >
          {link.label}
        </Link>
      ) : null}
    </li>
  );
}

function ProductCard({ product }: { product: PlanProduct }) {
  return (
    <li
      data-plan-product={product.product_id}
      className="flex flex-col overflow-hidden rounded-xl border"
    >
      {product.image ? (
        // The shop's own photo, from the synced catalogue; the name below says what it is.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={product.image}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          className="aspect-[4/3] w-full bg-muted object-cover"
        />
      ) : (
        <span className="flex aspect-[4/3] w-full items-center justify-center bg-muted">
          <ImageIcon className="size-6 text-muted-foreground" aria-hidden />
        </span>
      )}
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="space-y-0.5">
          <p className="font-semibold break-words">
            {product.title ?? "No longer in your synced catalogue"}
          </p>
          {product.in_stock === false ? (
            <div className="pt-1">
              <SoldOutNow />
            </div>
          ) : null}
          {money(product.price ?? null) ? (
            <p className="text-sm text-muted-foreground">{money(product.price ?? null)}</p>
          ) : null}
        </div>
        {product.url ? (
          <Button
            variant="outline"
            className="mt-auto h-11 self-start px-4 sm:h-10"
            nativeButton={false}
            data-open-page
            render={
              <a
                href={product.url}
                target="_blank"
                rel="noreferrer"
                aria-label={`Open the page for ${product.title ?? "this product"} in a new tab`}
              />
            }
          >
            Open the page
            <ExternalLink className="size-3.5" aria-hidden />
          </Button>
        ) : null}
      </div>
    </li>
  );
}
