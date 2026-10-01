import { Check } from "lucide-react";
import { CONTACT_HREF } from "@/lib/site";

/**
 * The pieces both product pages are made of (canvas row 9, boards 28–30).
 *
 * Every example on these pages is made up — Summit Shell, Trail Boots — and
 * never the test shop's data (the owner's rule). Every sentence describes
 * something `docs/FEATURES.md` lists as built.
 */

export function Eyebrow({ children, tag }: { children: React.ReactNode; tag?: string }) {
  return (
    <span className="flex flex-wrap items-center gap-2.5">
      <span className="text-sm font-semibold text-accent">{children}</span>
      {tag ? (
        <span className="flex h-6 items-center rounded-full border border-[#d4d4d4] px-2.5 text-xs font-medium text-body">
          {tag}
        </span>
      ) : null}
    </span>
  );
}

export function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="flex h-[30px] items-center self-start rounded-full bg-accent-soft px-3 text-sm font-semibold text-accent">
      {children}
    </span>
  );
}

export function Hero({
  pill,
  title,
  lede,
  ticks,
  picture,
}: {
  pill: string;
  title: string;
  lede: string;
  ticks: string[];
  picture: React.ReactNode;
}) {
  return (
    <section
      aria-labelledby="hero"
      className="grid items-center gap-10 px-5 pt-9 pb-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:gap-[72px] lg:px-16 lg:pt-[88px] lg:pb-24"
    >
      <div className="flex flex-col gap-5 lg:gap-6">
        <Pill>{pill}</Pill>
        <h1
          id="hero"
          className="m-0 text-[40px] leading-[1.05] font-bold tracking-[-0.03em] lg:text-[68px] lg:leading-[1.02] lg:tracking-[-0.035em]"
        >
          {title}
        </h1>
        <p className="m-0 max-w-[560px] text-[17px] leading-[1.55] text-body lg:text-[21px]">
          {lede}
        </p>
        <div className="flex flex-col gap-3 pt-2 sm:flex-row">
          <a
            href={CONTACT_HREF}
            className="flex h-[52px] items-center justify-center rounded-xl bg-ink px-6 text-[17px] font-medium text-white no-underline hover:bg-[#262626]"
          >
            Talk to us
          </a>
          <a
            href="#how"
            className="flex h-[52px] items-center justify-center rounded-xl border border-[#d4d4d4] px-6 text-[17px] font-medium no-underline hover:bg-[#f5f5f5]"
          >
            See how it works
          </a>
        </div>
        <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-2 p-0 pt-1 text-sm text-[#525252]">
          {ticks.map((tick) => (
            <li key={tick} className="flex items-center gap-1.5">
              <Check className="size-4" strokeWidth={2} aria-hidden />
              {tick}
            </li>
          ))}
        </ul>
      </div>
      {picture}
    </section>
  );
}

export function HowItWorks({
  lede,
  steps,
}: {
  lede: string;
  steps: { title: string; body: string }[];
}) {
  return (
    <section
      id="how"
      aria-labelledby="how-h"
      className="flex flex-col gap-8 border-y border-[#efefef] bg-[#fafaf9] px-5 py-12 lg:gap-12 lg:px-16 lg:py-[88px]"
    >
      <div className="flex max-w-[720px] flex-col gap-3">
        <h2
          id="how-h"
          className="m-0 text-[30px] leading-[1.1] font-bold tracking-[-0.025em] lg:text-[44px]"
        >
          How it works
        </h2>
        <p className="m-0 text-[17px] leading-[1.55] text-body lg:text-[19px]">{lede}</p>
      </div>
      <ol className="m-0 grid list-none gap-3 p-0 md:grid-cols-3 md:gap-6">
        {steps.map((step, i) => (
          <li
            key={step.title}
            className="flex flex-col gap-2 rounded-[18px] border border-[#ececec] bg-white p-5 lg:gap-3.5 lg:rounded-[20px] lg:p-7"
          >
            <span className="font-mono text-[15px] font-medium text-accent">0{i + 1}</span>
            <span className="text-[19px] font-semibold tracking-[-0.01em] lg:text-[23px]">
              {step.title}
            </span>
            <span className="text-[15px] leading-[1.55] text-body lg:text-base">{step.body}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * One feature: the words on one side, the picture on the other; `flip` swaps
 * them on wide screens. `id` lets a guide link straight to it.
 */
export function Feature({
  id,
  eyebrow,
  tag,
  title,
  children,
  picture,
  flip,
}: {
  id?: string;
  eyebrow: string;
  tag?: string;
  title: string;
  children: React.ReactNode;
  picture: React.ReactNode;
  flip?: boolean;
}) {
  return (
    <div id={id} className="grid scroll-mt-6 items-center gap-8 lg:grid-cols-2 lg:gap-20">
      <div className={`flex flex-col gap-4 ${flip ? "lg:order-2" : ""}`}>
        <Eyebrow tag={tag}>{eyebrow}</Eyebrow>
        <h3 className="m-0 text-[28px] leading-[1.15] font-bold tracking-[-0.02em] lg:text-[38px] lg:leading-[1.12]">
          {title}
        </h3>
        {children}
      </div>
      <div className={flip ? "lg:order-1" : ""}>{picture}</div>
    </div>
  );
}

export function FeatureText({ children }: { children: React.ReactNode }) {
  return <p className="m-0 text-base leading-[1.6] text-body lg:text-lg">{children}</p>;
}

export function Features({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section
      aria-label={label}
      className="flex flex-col gap-16 px-5 pt-14 pb-6 lg:gap-[104px] lg:px-16 lg:pt-[104px] lg:pb-10"
    >
      {children}
    </section>
  );
}

/** The grey stage a feature's picture sits on. */
export function Stage({
  children,
  dark,
  tall,
}: {
  children: React.ReactNode;
  dark?: boolean;
  tall?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-center rounded-[24px] px-4 py-8 ${dark ? "bg-ink" : "bg-hush"} ${tall ? "lg:min-h-[460px]" : "lg:min-h-[380px]"}`}
    >
      {children}
    </div>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`w-full max-w-[440px] overflow-hidden rounded-[18px] bg-white shadow-[0_14px_36px_rgba(10,10,10,0.10)] ${className}`}
    >
      {children}
    </div>
  );
}

export function ChatHead() {
  return (
    <div className="flex h-12 items-center justify-between bg-ink px-[18px] text-sm font-semibold text-white">
      <span>Chat with us</span>
      <span className="size-2 rounded-full bg-accent" />
    </div>
  );
}

export function Asked({ children }: { children: React.ReactNode }) {
  return (
    <span className="max-w-[300px] self-end rounded-[16px_16px_4px_16px] bg-ink px-3.5 py-[11px] text-[15px] leading-[1.45] text-white">
      {children}
    </span>
  );
}

export function Answered({ children, soft }: { children: React.ReactNode; soft?: boolean }) {
  return (
    <span
      className={`max-w-[360px] self-start text-[15px] leading-[1.55] ${soft ? "text-body" : "text-ink"}`}
    >
      {children}
    </span>
  );
}

export function Caption({ children, dark }: { children: React.ReactNode; dark?: boolean }) {
  return (
    <span className={`text-[13px] ${dark ? "text-[#a3a3a3]" : "text-quiet"}`}>{children}</span>
  );
}

export function Band({
  title,
  lede,
  items,
}: {
  title: string;
  lede: string;
  items: { title: string; body: string }[];
}) {
  return (
    <section
      aria-labelledby="band"
      className="mx-4 mt-12 flex flex-col gap-8 rounded-[24px] bg-ink px-6 py-9 text-white lg:mx-16 lg:mt-20 lg:gap-11 lg:rounded-[32px] lg:px-16 lg:py-[72px]"
    >
      <div className="flex max-w-[800px] flex-col gap-3">
        <h2
          id="band"
          className="m-0 text-[30px] leading-[1.1] font-bold tracking-[-0.025em] lg:text-[44px]"
        >
          {title}
        </h2>
        <p className="m-0 text-[17px] leading-[1.55] text-[#d4d4d4] lg:text-[19px]">{lede}</p>
      </div>
      <div
        className={`grid gap-6 ${items.length === 4 ? "md:grid-cols-2 lg:grid-cols-4" : "md:grid-cols-3"}`}
      >
        {items.map((item) => (
          <div key={item.title} className="flex flex-col gap-2 border-t border-[#404040] pt-5">
            <span className="text-[19px] font-semibold">{item.title}</span>
            <span className="text-[15px] leading-[1.55] text-[#bdbdbd]">{item.body}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function Questions({ items }: { items: { q: string; a: React.ReactNode }[] }) {
  return (
    <section
      aria-labelledby="faq"
      className="grid gap-8 px-5 pt-14 lg:grid-cols-[360px_minmax(0,1fr)] lg:gap-20 lg:px-16 lg:pt-[104px]"
    >
      <h2
        id="faq"
        className="m-0 text-[30px] leading-[1.1] font-bold tracking-[-0.025em] lg:text-[44px]"
      >
        Questions
      </h2>
      <div className="flex flex-col border-t border-line">
        {items.map((item, i) => (
          <details key={item.q} open={i === 0} className="border-b border-line py-[22px]">
            <summary className="text-lg font-semibold lg:text-xl">{item.q}</summary>
            <p className="mt-3 mb-0 text-base leading-[1.6] text-body lg:text-[17px]">{item.a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

export function CallToAction({ title, lede }: { title: string; lede: string }) {
  return (
    <section
      aria-labelledby="cta"
      className="mx-4 mt-12 mb-10 flex flex-col gap-5 rounded-[24px] bg-accent-soft px-6 py-8 lg:mx-16 lg:mt-[104px] lg:mb-[88px] lg:flex-row lg:items-center lg:justify-between lg:gap-10 lg:rounded-[32px] lg:p-[72px]"
    >
      <div className="flex flex-col gap-2.5">
        <h2
          id="cta"
          className="m-0 text-[26px] leading-[1.15] font-bold tracking-[-0.025em] lg:text-[40px] lg:leading-[1.1]"
        >
          {title}
        </h2>
        <p className="m-0 text-base text-body lg:text-lg">{lede}</p>
      </div>
      <a
        href={CONTACT_HREF}
        className="flex h-[52px] shrink-0 items-center justify-center rounded-xl bg-ink px-7 text-[17px] font-medium text-white no-underline hover:bg-[#262626] lg:h-14 lg:rounded-[14px]"
      >
        Talk to us
      </a>
    </section>
  );
}
