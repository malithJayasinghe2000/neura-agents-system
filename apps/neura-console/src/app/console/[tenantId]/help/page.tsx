/**
 * Help — *Connecting your shop*. New 2026-09-28, from the owner's approved
 * mockup (console.md §3.4, canvas board 22).
 *
 * **Decided in ADR-0026 §7 and never built until now:** merchant help lives
 * inside the console, so a help page can link straight into the screen it
 * describes. This one answers the owner's question *"what does connecting a new
 * shop take?"* — who does what, the steps in order with how you'll know each is
 * done (the same ticks as Shop connection's checklist), what to hand a
 * developer, and what to do when something doesn't work.
 *
 * **Nothing here is about one shop's data**, so it reads nothing but the chat
 * box line — from the API, exactly as the API serves it, so this page cannot
 * show a line a developer would not be given. No platform's name, settings or
 * commands (AGENTS.md rule 1), no time estimates and no numbers.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { CopySteps } from "@/components/help/copy-steps";
import { hasSell, shopAssistants } from "@/lib/shop-assistants";
import { STEPS, TROUBLE, TWO_KEYS } from "@/lib/help";
import { hasSession, widgetSnippet } from "@/lib/server-api";

export default async function HelpPage({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const base = `/console/${encodeURIComponent(tenantId)}`;
  const [snippet, assistants] = await Promise.all([widgetSnippet(), shopAssistants(tenantId)]);
  // Sold out is NEURA-SELL's; a shop without it is not told how to set it up.
  const sell = hasSell(assistants);

  return (
    <>
      <div className="max-w-3xl space-y-2">
        <p className="text-sm font-medium text-muted-foreground">Help</p>
        <h1 className="text-2xl font-semibold tracking-tight">Connecting your shop</h1>
        <p className="leading-relaxed text-foreground/80">
          Your shop and NEURA talk through a small add-on in your shop, called the{" "}
          <strong className="font-semibold text-foreground">NEURA bridge</strong>. It only lets
          NEURA read — products, stock, orders and policy pages — and never change anything. Here is
          who does what, and in which order.
        </p>
      </div>

      <section aria-labelledby="who" className="space-y-3">
        <h2 id="who" className="text-lg font-semibold">
          Who does what
        </h2>
        <div className="grid gap-3 md:grid-cols-3">
          <Who title="You">
            Follow the checklist on{" "}
            <Link href={`${base}/shops`} className="underline underline-offset-3">
              Shop connection
            </Link>
            . Read and grade replies in{" "}
            <Link href={`${base}/review`} className="underline underline-offset-3">
              Review
            </Link>{" "}
            while practice mode is on. Decide when to go live.
          </Who>
          <Who title="Your developer">
            Installs the NEURA bridge in your shop, and adds the chat box to your shop&apos;s pages.
            {sell ? " Switches on product views if you want Sold out." : null}
          </Who>
          <Who title="FiveNeurals" aside="(for now)">
            Creates your account, connects your shop and copies your catalogue the first time.
            {sell ? " Records a data agreement if you want Sold out." : null}
          </Who>
        </div>
      </section>

      <section aria-labelledby="steps" className="space-y-3">
        <h2 id="steps" className="text-lg font-semibold">
          The steps
        </h2>
        {/* Numbered because it is a sequence: each step needs the one before. */}
        <ol className="divide-y overflow-hidden rounded-2xl border">
          {STEPS.map((step, i) => (
            <li
              key={step.title}
              data-help-step
              className="flex flex-col gap-2 px-4 py-4 sm:flex-row sm:gap-4 sm:px-5"
            >
              <span className="flex items-start gap-3 sm:contents">
                <span
                  aria-hidden
                  className="grid size-7 shrink-0 place-items-center rounded-full border text-sm font-semibold"
                >
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1 space-y-1">
                  <span className="block font-semibold">{step.title}</span>
                  <span className="block text-sm leading-relaxed text-foreground/80">
                    {step.body}
                  </span>
                  <span className="block text-sm text-muted-foreground">
                    How you&apos;ll know: {step.check}
                  </span>
                </span>
              </span>
              <span className="ml-10 inline-flex h-6 shrink-0 items-center self-start rounded-full bg-muted px-2.5 text-xs font-medium sm:ml-0">
                {step.who}
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="dev" className="space-y-3 rounded-2xl border p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="dev" className="text-lg font-semibold">
            For your developer
          </h2>
          <CopySteps snippet={snippet} />
        </div>
        <p className="text-sm leading-relaxed text-foreground/80">
          The bridge answers nine read-only addresses that NEURA calls with a secret token. The chat
          box is one line on your shop&apos;s pages, with a public key that only works from your
          shop&apos;s own address:
        </p>
        {snippet ? (
          <pre
            data-snippet
            className="overflow-x-auto rounded-xl bg-foreground px-4 py-3.5 font-mono text-[13px] leading-relaxed break-all whitespace-pre-wrap text-background"
          >
            {snippet}
          </pre>
        ) : (
          <p className="rounded-xl border border-dashed p-3.5 text-sm text-muted-foreground">
            The chat box line couldn&apos;t be loaded just now. FiveNeurals can send it.
          </p>
        )}
        <p className="text-sm text-muted-foreground">
          The key in it is a placeholder — FiveNeurals gives you the chat box key for your shop.
        </p>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {TWO_KEYS} The full technical guide covers the nine addresses, change messages and product
          views.
        </p>
      </section>

      <section aria-labelledby="trouble" className="space-y-3">
        <h2 id="trouble" className="text-lg font-semibold">
          If something doesn&apos;t work
        </h2>
        <dl className="divide-y overflow-hidden rounded-2xl border">
          {TROUBLE.filter((row) => sell || !row.sell).map((row) => (
            <div
              key={row.seen}
              className="grid gap-1 px-4 py-3 text-sm sm:grid-cols-[18rem_1fr] sm:gap-4 sm:px-5"
            >
              <dt className="font-medium">{row.seen}</dt>
              <dd className="leading-relaxed text-foreground/80">{row.fix}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}

function Who({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2 rounded-2xl border p-4">
      <p className="font-semibold">
        {title} {aside ? <span className="font-normal text-muted-foreground">{aside}</span> : null}
      </p>
      <p className="text-sm leading-relaxed text-foreground/80">{children}</p>
    </div>
  );
}
