import type { Metadata } from "next";
import Link from "next/link";
import { ContactLine } from "@/components/contact";
import { CONTACT_HREF } from "@/lib/site";
import { STEPS } from "@/lib/steps";

/** Docs home — canvas board 24 (and 27 on a phone), approved by the owner 2026-09-30. */
export const metadata: Metadata = {
  title: "Connect your shop",
  description:
    "How a shop gets connected to NEURA: who does what, and how you'll know each step worked.",
};

function Door({
  href,
  who,
  title,
  body,
  cta,
}: {
  href: string;
  who: string;
  title: string;
  body: string;
  cta: string;
}) {
  return (
    <Link
      href={href}
      className="flex flex-col gap-2.5 rounded-2xl border border-line p-5 text-ink no-underline hover:border-[#a3a3a3] md:p-7"
    >
      <span className="text-[13px] font-medium text-quiet">{who}</span>
      <span className="text-xl font-semibold tracking-[-0.01em] md:text-2xl">{title}</span>
      <span className="text-[15px] leading-[1.55] text-body md:text-base">{body}</span>
      <span className="mt-1 text-[15px] font-medium md:mt-2">{cta}</span>
    </Link>
  );
}

export default function DocsHome() {
  return (
    <div className="flex flex-col gap-10 px-4 pt-7 pb-8 md:gap-14 md:px-14 md:pt-16 md:pb-14">
      <section aria-labelledby="hero" className="flex max-w-[860px] flex-col gap-3 md:gap-4">
        <h1
          id="hero"
          className="m-0 text-[32px] leading-[1.15] font-semibold tracking-[-0.02em] md:text-5xl md:leading-[1.1] md:tracking-[-0.025em]"
        >
          Connect your shop to NEURA
        </h1>
        <p className="m-0 text-base leading-[1.55] text-body md:text-[19px]">
          NEURA&apos;s assistants talk to your shoppers in a chat box on your shop.{" "}
          <strong className="font-semibold text-ink">NEURA-CARE</strong> answers questions about
          orders, products and your policies.{" "}
          <strong className="font-semibold text-ink">NEURA-SELL</strong> helps shoppers choose. This
          guide shows how a shop gets connected: who does what, and how you&apos;ll know each step
          worked.
        </p>
      </section>

      <section aria-label="Choose your guide" className="grid gap-3 md:grid-cols-2 md:gap-5">
        <Door
          href="/docs/owners/"
          who="I own the shop"
          title="Guide for shop owners"
          body="No code. What you need before you start, the five steps, practice mode, and what NEURA will and won't do."
          cta="Read the owner guide →"
        />
        <Door
          href="/docs/developers/"
          who="I'm the shop's developer"
          title="Guide for developers"
          body="The bridge: nine read-only addresses your shop answers. How to check your work, the keys, and the chat box line."
          cta="Read the developer guide →"
        />
      </section>

      <section aria-labelledby="how" className="flex flex-col gap-3 md:gap-5">
        <h2 id="how" className="m-0 text-[22px] font-semibold tracking-[-0.01em] md:text-[26px]">
          How it works
        </h2>
        <div className="grid items-center gap-2 md:gap-6 lg:grid-cols-[260px_minmax(0,1fr)_260px]">
          <div className="flex flex-col gap-1.5 rounded-[14px] border border-[#d4d4d4] bg-[#fafafa] p-4 md:p-[22px]">
            <span className="text-base font-semibold md:text-lg">Your shop</span>
            <span className="text-sm leading-[1.5] text-body">
              with the <strong className="font-semibold">NEURA bridge</strong>, a small add-on your
              developer installs
            </span>
          </div>
          <ul className="m-0 flex list-none flex-col gap-2 p-0 md:gap-3">
            <li className="flex flex-col gap-0.5 rounded-xl border border-[#efefef] px-[18px] py-3.5">
              <span className="text-[15px] font-semibold">
                NEURA reads products, stock, orders and policy pages
              </span>
              <span className="text-[13px] text-quiet">
                with a secret shop token that stays on your shop&apos;s server
              </span>
            </li>
            <li className="flex flex-col gap-0.5 rounded-xl border border-[#efefef] px-[18px] py-3.5">
              <span className="text-[15px] font-semibold">
                The chat box on your pages talks to NEURA
              </span>
              <span className="text-[13px] text-quiet">
                with a public chat box key that only works from your shop&apos;s address
              </span>
            </li>
            <li className="flex flex-col gap-0.5 rounded-xl border border-dashed border-[#d4d4d4] px-[18px] py-3.5">
              <span className="text-[15px] font-semibold">
                Product views <span className="font-normal text-quiet">optional</span>
              </span>
              <span className="text-[13px] text-quiet">
                only if you switch them on, for NEURA-SELL&apos;s Sold out list
              </span>
            </li>
          </ul>
          <div className="flex flex-col gap-1.5 rounded-[14px] bg-ink p-4 text-white md:p-[22px]">
            <span className="text-base font-semibold md:text-lg">NEURA</span>
            <span className="text-sm leading-[1.5] text-[#d4d4d4]">
              NEURA-CARE and NEURA-SELL, and your dashboard
            </span>
          </div>
        </div>
        <p className="m-0 rounded-xl bg-[#f5f5f5] px-[18px] py-3.5 text-sm leading-[1.5] text-body md:text-[15px]">
          <strong className="font-semibold text-ink">Read only.</strong> NEURA cannot change
          anything in your shop: no orders, prices or stock. Every address the bridge answers only
          reads.
        </p>
      </section>

      <section aria-labelledby="steps" className="flex flex-col gap-3 md:gap-5">
        <div className="flex flex-col gap-1.5">
          <h2
            id="steps"
            className="m-0 text-[22px] font-semibold tracking-[-0.01em] md:text-[26px]"
          >
            The five steps
          </h2>
          <p className="m-0 text-[15px] text-body md:text-base">
            Each step ends with a tick on your dashboard&apos;s Shop connection page, so you always
            know where you are.
          </p>
        </div>
        <ol className="m-0 grid list-none gap-3 p-0 md:grid-cols-2 md:gap-4 lg:grid-cols-3">
          {STEPS.map((step, i) => (
            <li
              key={step.title}
              className="flex flex-col gap-2 rounded-[14px] border border-line p-4 md:p-5"
            >
              <span className="flex items-center justify-between gap-2">
                <span className="flex size-[30px] items-center justify-center rounded-full border border-[#d4d4d4] text-sm font-semibold">
                  {i + 1}
                </span>
                <span className="flex h-6 items-center rounded-full bg-[#f5f5f5] px-2.5 text-xs font-medium">
                  {step.who}
                </span>
              </span>
              <span className="text-[17px] font-semibold">{step.title}</span>
              <span className="text-sm leading-[1.5] text-body">{step.short}</span>
              <span className="text-[13px] text-quiet">You&apos;ll know: {step.check}</span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="know" className="flex flex-col gap-4 md:gap-5">
        <h2 id="know" className="m-0 text-[22px] font-semibold tracking-[-0.01em] md:text-[26px]">
          Good to know
        </h2>
        <div className="grid gap-5 md:grid-cols-3 md:gap-4">
          {[
            {
              title: "Practice first",
              body: "While practice mode is on, your assistant writes replies and no shopper sees them. You decide when to go live.",
            },
            {
              title: "Signing in",
              body: "Your dashboard has no password. You type your email and we send you a sign-in link.",
            },
            {
              title: "Your shoppers",
              body: "Product views stay off unless you switch them on. We never contact your shoppers.",
            },
          ].map((item) => (
            <div key={item.title} className="flex flex-col gap-1.5 border-t-2 border-ink pt-3.5">
              <span className="text-[17px] font-semibold">{item.title}</span>
              <span className="text-[15px] leading-[1.55] text-body">{item.body}</span>
            </div>
          ))}
        </div>
      </section>

      <section
        aria-labelledby="start"
        className="flex flex-col gap-4 rounded-2xl border border-line p-5 md:flex-row md:items-center md:justify-between md:gap-6 md:p-7"
      >
        <div className="flex flex-col gap-1.5">
          <h2 id="start" className="m-0 text-xl font-semibold md:text-[22px]">
            Ready to connect a shop?
          </h2>
          <p className="m-0 text-[15px] text-body">
            Today FiveNeurals creates your account and connects your shop with you.
          </p>
          <ContactLine />
        </div>
        <a
          href={CONTACT_HREF}
          className="flex h-[46px] shrink-0 items-center justify-center rounded-xl bg-ink px-5 text-[15px] font-medium text-white no-underline"
        >
          Talk to FiveNeurals
        </a>
      </section>
    </div>
  );
}
