import type { Metadata } from "next";
import Link from "next/link";
import { STEPS, TROUBLE } from "@/lib/steps";

/**
 * Guide for shop owners — canvas board 26, approved by the owner 2026-09-30.
 *
 * Two corrections to the board, both from the owner's own rules: the practice
 * example's order number is made up (the board had the test shop's), and step 4
 * says FiveNeurals makes the chat box key, because the dashboard cannot yet
 * (lib/steps.ts).
 */
export const metadata: Metadata = {
  title: "Guide for shop owners",
  description:
    "Getting your shop's assistant ready: what you get, what you need, the five steps, and how you'll know each one worked.",
};

function H2({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="m-0 text-[22px] font-semibold tracking-[-0.01em] md:text-[26px]">
      {children}
    </h2>
  );
}

export default function OwnerGuide() {
  return (
    <div className="flex max-w-[1080px] flex-col gap-10 px-4 pt-7 pb-12 md:gap-[52px] md:px-14 md:pt-12 md:pb-16">
      <section className="flex max-w-[820px] flex-col gap-3.5">
        <p className="m-0 text-[13px] font-medium text-quiet">For shop owners</p>
        <h1 className="m-0 text-[30px] leading-[1.15] font-semibold tracking-[-0.02em] md:text-[40px]">
          Getting your shop&apos;s assistant ready
        </h1>
        <p className="m-0 text-base leading-[1.6] text-body md:text-lg">
          No code on this page. What you get, what you need, the steps in order, and how you&apos;ll
          know each one worked.
        </p>
      </section>

      <section aria-labelledby="get" className="flex flex-col gap-4">
        <H2 id="get">What you get</H2>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-2 rounded-[14px] border border-line p-[22px]">
            <span className="text-xl font-semibold">
              NEURA-CARE <span className="text-[15px] font-normal text-quiet">· Customer care</span>
            </span>
            <span className="text-[15px] leading-[1.55] text-body">
              Answers shoppers&apos; questions about their orders, your products and your policies.
              When it can&apos;t help, it hands the question to your team.
            </span>
          </div>
          <div className="flex flex-col gap-2 rounded-[14px] border border-line p-[22px]">
            <span className="text-xl font-semibold">
              NEURA-SELL <span className="text-[15px] font-normal text-quiet">· Shopping help</span>
            </span>
            <span className="text-[15px] leading-[1.55] text-body">
              Helps shoppers choose, and suggests what goes with what&apos;s in their basket. You
              can pick those suggestions yourself.
            </span>
          </div>
        </div>
      </section>

      <section aria-labelledby="need" className="flex flex-col gap-4">
        <H2 id="need">Before you start</H2>
        <ul className="m-0 flex list-disc flex-col gap-2 pl-5 text-base leading-[1.55] text-body">
          <li>
            <strong className="font-semibold text-ink">A developer</strong> who can add an add-on
            and one line to your shop. It&apos;s needed once, for steps 1 and 4. Send them the{" "}
            <Link href="/docs/developers/">developer guide</Link>.
          </li>
          <li>
            <strong className="font-semibold text-ink">Your shop&apos;s web address.</strong>
          </li>
          <li>
            <strong className="font-semibold text-ink">An email address</strong> you&apos;ll sign in
            with. There&apos;s no password: we send you a sign-in link.
          </li>
        </ul>
      </section>

      <section aria-labelledby="steps" className="flex flex-col gap-4">
        <H2 id="steps">The five steps</H2>
        <ol className="m-0 list-none overflow-hidden rounded-[14px] border border-line p-0">
          {STEPS.map((step, i) => (
            <li
              key={step.title}
              className={`flex flex-col gap-3 px-4 py-4 sm:flex-row sm:gap-4 md:px-5 ${i < STEPS.length - 1 ? "border-b border-[#efefef]" : ""}`}
            >
              <span className="flex size-[30px] shrink-0 items-center justify-center rounded-full border border-[#d4d4d4] text-sm font-semibold">
                {i + 1}
              </span>
              <span className="flex flex-1 flex-col gap-1">
                <span className="text-base font-semibold">{step.ownerTitle}</span>
                <span className="text-[15px] leading-[1.5] text-body">{step.body}</span>
                <span className="text-sm text-quiet">How you&apos;ll know: {step.check}</span>
              </span>
              <span className="flex h-6 shrink-0 items-center self-start rounded-full bg-[#f5f5f5] px-2.5 text-xs font-medium">
                {step.who}
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="practice" className="flex flex-col gap-4">
        <H2 id="practice">Practice mode, with an example</H2>
        <p className="m-0 max-w-[820px] text-base leading-[1.6] text-body">
          A shopper asks{" "}
          <strong className="font-semibold text-ink">&ldquo;Where is my order 1042?&rdquo;</strong>{" "}
          While practice mode is on, your assistant writes a reply, but the shopper doesn&apos;t see
          it yet.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-2.5 rounded-[14px] border border-line p-5">
            <span className="text-[13px] font-medium text-quiet">What the shopper sees</span>
            <span className="rounded-xl bg-[#f5f5f5] px-3.5 py-3 text-[15px] leading-[1.5]">
              Thanks — your message has been received. There is no automated answer available for it
              right now.
            </span>
          </div>
          <div className="flex flex-col gap-2.5 rounded-[14px] border border-dashed border-[#a3a3a3] p-5">
            <span className="text-[13px] font-medium text-quiet">What you see in Review</span>
            <span className="text-[15px] leading-[1.5] text-body">
              The reply your assistant wrote, what it looked at in your shop, and three buttons:{" "}
              <strong className="font-semibold text-ink">Good · Not good · Harmful</strong>.
            </span>
          </div>
        </div>
        <p className="m-0 text-[15px] leading-[1.55] text-body">
          When you go live, shoppers see the replies themselves.
        </p>
      </section>

      <section aria-labelledby="never" className="flex flex-col gap-4">
        <H2 id="never">What NEURA never does</H2>
        <ul className="m-0 grid list-none gap-x-8 gap-y-3 p-0 text-base leading-[1.5] md:grid-cols-2">
          {[
            "Change your orders, prices or stock",
            "Email or message your shoppers",
            "Watch your shoppers, unless you switch product views on",
            "Tell a shopper how many other people want something",
          ].map((line) => (
            <li key={line} className="border-t border-line pt-3">
              {line}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="trouble" className="flex scroll-mt-4 flex-col gap-4">
        <H2 id="trouble">If something doesn&apos;t work</H2>
        <dl className="m-0 overflow-hidden rounded-[14px] border border-line text-[15px]">
          {TROUBLE.map((row, i) => (
            <div
              key={row.seen}
              className={`grid gap-1 px-4 py-3.5 md:grid-cols-[320px_minmax(0,1fr)] md:gap-4 md:px-5 ${i < TROUBLE.length - 1 ? "border-b border-[#efefef]" : ""}`}
            >
              <dt className="font-medium">{row.seen}</dt>
              <dd className="m-0 leading-[1.5] text-body">{row.fix}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
