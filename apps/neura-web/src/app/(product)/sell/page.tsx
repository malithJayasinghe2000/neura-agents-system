import type { Metadata } from "next";
import { Shirt } from "lucide-react";
import {
  Answered,
  Asked,
  Band,
  CallToAction,
  Caption,
  Card,
  ChatHead,
  Feature,
  FeatureText,
  Features,
  Hero,
  HowItWorks,
  Questions,
  Stage,
} from "@/components/marketing";

/**
 * NEURA-SELL — canvas board 29, approved by the owner 2026-09-30.
 *
 * Two things here are shaped by the code, not by taste: a product card carries
 * a picture, a price and whether it is in stock — **no "reason" tag**
 * (agents/sell/tools/card.py); the reasons are in the reply's words. And the
 * "nothing fits" reply is quoted exactly: it is fixed text in
 * agents/sell/nodes/no_match.py and prompts/no_match_constraint.md, and no
 * model writes it.
 */
export const metadata: Metadata = {
  title: "NEURA-SELL",
  description:
    "NEURA-SELL helps shoppers find the right product in your catalogue, compares honestly, and suggests what goes with it.",
};

const PICKS = [
  { name: "Summit Shell", price: "$129" },
  { name: "Ridge Jacket", price: "$145" },
  { name: "Trail Lite", price: "$99" },
];

function Picks() {
  return (
    <div className="flex items-center justify-center rounded-[28px] bg-hush px-4 py-8 lg:min-h-[580px]">
      <Card className="max-w-[480px] rounded-[20px]">
        <ChatHead />
        <div className="flex flex-col gap-3.5 px-[18px] pt-5 pb-[22px]">
          <Asked>I need a waterproof jacket for hiking, under $150.</Asked>
          <Answered>
            Three fit, all under $150. The Summit Shell ($129) packs into its own pocket. The Ridge
            Jacket ($145) has a hood. The Trail Lite ($99) is the lightest of the three.
          </Answered>
          <ul className="m-0 grid list-none grid-cols-3 gap-2.5 p-0">
            {PICKS.map((pick) => (
              <li
                key={pick.name}
                className="flex flex-col overflow-hidden rounded-[14px] border border-[#ececec]"
              >
                <span className="flex h-[86px] items-center justify-center bg-[#e9e8e4]">
                  <Shirt className="size-7 text-[#8a8a8a]" strokeWidth={1.6} aria-hidden />
                </span>
                <span className="flex flex-col gap-1 px-2.5 pt-2 pb-2.5">
                  <span className="text-[13px] font-semibold">{pick.name}</span>
                  <span className="text-[13px] text-body">{pick.price}</span>
                  <span className="flex items-center gap-1.5 text-xs text-[#525252]">
                    <span className="size-1.5 rounded-full bg-accent" />
                    In stock
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <Caption>Each reason comes from your own product description.</Caption>
        </div>
      </Card>
    </div>
  );
}

export default function SellPage() {
  return (
    <>
      <Hero
        pill="NEURA-SELL · Shopping help"
        title="Helps shoppers find the right thing — and what goes with it."
        lede="A shopper says what they need. NEURA-SELL answers with a short list from your own catalogue — and the reason for every pick. It compares honestly, suggests what goes together, and shows you what shoppers wanted while it was sold out."
        ticks={["Only products you sell", "A reason for every pick", "No fake urgency"]}
        picture={<Picks />}
      />

      <HowItWorks
        lede={"From “I need something for…” to a short list, in three steps."}
        steps={[
          {
            title: "A shopper says what they need",
            body: "“Something warm for winter walks.” “Which of these two for commuting?” In their own words.",
          },
          {
            title: "It searches your catalogue",
            body: "Only your products, with their real prices, sizes and stock. Nothing from anywhere else.",
          },
          {
            title: "It shows a short list, with reasons",
            body: "A few good picks, each with why it's there. If nothing fits, it says what didn't — it never tells a shopper you don't sell something you do.",
          },
        ]}
      />

      <Features label="What NEURA-SELL does">
        <Feature
          eyebrow="Recommend"
          title="Described in their own words. Answered from your shelves."
          picture={
            <Stage tall>
              <div className="flex w-full max-w-[440px] flex-col gap-3">
                <span className="flex h-7 items-center self-start rounded-full border border-line bg-white px-3 text-[13px] font-semibold">
                  When nothing fits
                </span>
                <Card className="max-w-none">
                  <ChatHead />
                  <div className="flex flex-col gap-3 p-[18px]">
                    <Asked>A rain jacket under $60?</Asked>
                    <Answered>
                      I found 3 in this store&apos;s catalogue, but none under 60.00 USD. The
                      closest is 99.00 USD.
                    </Answered>
                    <Answered soft>
                      If you&apos;d like to stretch a little I can show you what&apos;s closest, or
                      tell me more about what you need and I&apos;ll look again.
                    </Answered>
                  </div>
                </Card>
                <Caption>
                  Fixed words and your catalogue&apos;s own numbers — no AI writes this reply.
                </Caption>
              </div>
            </Stage>
          }
        >
          <FeatureText>
            No filters to work out. A shopper says what it&apos;s for and what they want to spend.
            NEURA-SELL picks from your catalogue and says why each one fits, from your own product
            descriptions. Every pick is a card with its picture, its price, whether it&apos;s in
            stock, and a link to its page.
          </FeatureText>
          <div className="mt-2 flex flex-col gap-1.5 rounded-2xl border border-[#ececec] px-5 py-[18px]">
            <span className="text-[17px] font-semibold">And when nothing fits, it says so.</span>
            <span className="text-base leading-[1.55] text-body">
              If the shopper&apos;s budget rules everything out, it tells them how many it found and
              the closest price — and never passes off a near-miss as a match.
            </span>
          </div>
        </Feature>

        <Feature
          flip
          eyebrow="Compare"
          title="“Which one?” — answered by what's actually different."
          picture={
            <Stage>
              <div className="flex w-full max-w-[440px] flex-col gap-3">
                <Card className="max-w-none">
                  <div className="flex flex-col gap-3 p-[18px]">
                    <Asked>Summit Shell or Ridge Jacket — which for day hikes?</Asked>
                    <Answered>
                      Both are waterproof, so that won&apos;t decide it. The Ridge Jacket ($145) has
                      a hood. The Summit Shell ($129) packs into its own pocket. Want the hood? The
                      Ridge. Want it small in your bag? The Summit.
                    </Answered>
                  </div>
                </Card>
                <Caption>The differences come from your own product descriptions.</Caption>
              </div>
            </Stage>
          }
        >
          <FeatureText>
            Two jackets that are both waterproof aren&apos;t different because they&apos;re
            waterproof. NEURA-SELL says what actually differs, from your own descriptions — and lets
            the shopper choose.
          </FeatureText>
        </Feature>

        <Feature
          eyebrow="Basket suggestions"
          title="The socks that go with the boots. At the moment it matters."
          picture={
            <Stage>
              <Card className="flex flex-col gap-3.5 p-5">
                <div className="flex items-center gap-3 border-b border-[#efefef] pb-3.5">
                  <span className="size-[52px] rounded-[10px] bg-[#e9e8e4]" />
                  <span className="flex flex-col gap-0.5">
                    <span className="text-[15px] font-semibold">Trail Boots</span>
                    <span className="text-[13px] text-quiet">In your basket</span>
                  </span>
                </div>
                <span className="text-[15px] font-semibold">Goes well with your Trail Boots</span>
                <div className="grid grid-cols-2 gap-2.5">
                  {["Wool Hiking Socks", "Boot Proofing Wax"].map((name) => (
                    <span
                      key={name}
                      className="flex flex-col gap-1 rounded-xl border border-[#ececec] p-2.5"
                    >
                      <span className="h-14 rounded-lg bg-[#e9e8e4]" />
                      <span className="text-[13px] font-semibold">{name}</span>
                    </span>
                  ))}
                </div>
              </Card>
            </Stage>
          }
        >
          <FeatureText>
            On the basket page, shoppers see what goes well with what they&apos;ve picked — from
            your catalogue. Let NEURA choose, or pick the pairings yourself for any product.{" "}
            <strong className="font-semibold text-ink">Your choice always wins.</strong>
          </FeatureText>
        </Feature>

        <Feature
          flip
          eyebrow="Sold out"
          tag="Optional · you switch it on"
          title="Know what to restock — because shoppers already told you."
          picture={
            <Stage>
              <Card>
                <div className="border-b border-[#efefef] px-[18px] py-3.5 text-sm font-semibold">
                  Wanted while sold out · last 7 days
                </div>
                {[
                  { name: "Wool Jumper", seen: "Opened 6 times, in 4 visits", back: false },
                  { name: "Rain Hat", seen: "Opened twice, in 2 visits", back: true },
                ].map((row, i) => (
                  <div
                    key={row.name}
                    className={`flex items-center gap-3 px-[18px] py-3.5 ${i === 0 ? "border-b border-[#f4f4f4]" : ""}`}
                  >
                    <span className="flex flex-1 flex-col gap-0.5">
                      <span className="text-[15px] font-semibold">{row.name}</span>
                      <span className="text-[13px] text-quiet">{row.seen}</span>
                    </span>
                    {row.back ? (
                      <span className="flex h-7 items-center rounded-full border border-accent px-3 text-[13px] font-medium text-accent">
                        Back in stock
                      </span>
                    ) : (
                      <span className="flex h-7 items-center rounded-full bg-ink px-3 text-[13px] font-medium text-white">
                        Still sold out
                      </span>
                    )}
                  </div>
                ))}
              </Card>
            </Stage>
          }
        >
          <FeatureText>
            See which products shoppers opened while you had none, and whether they&apos;re back in
            stock now. Counts of visits — never who the shopper was, and nobody is ever contacted.
          </FeatureText>
        </Feature>

        <Feature
          eyebrow="Found by AI shopping assistants"
          tag="Off until you switch it on"
          title="Shoppers are starting to ask AI. Make sure it can read your shop."
          picture={
            <Stage dark>
              <div className="flex w-full max-w-[420px] flex-col gap-3">
                <Caption dark>What an AI shopping assistant reads</Caption>
                <div className="rounded-2xl border border-[#333333] bg-[#1a1a1a] p-[18px] font-mono text-[13px] leading-[1.8] text-[#e5e5e5]">
                  <span className="block">Summit Shell</span>
                  <span className="block text-[#a3a3a3]">price: $129</span>
                  <span className="block text-[#a3a3a3]">
                    availability: <span className="text-white">in stock</span>
                  </span>
                  <span className="block text-[#a3a3a3]">
                    as of: the last time your shop was read
                  </span>
                </div>
                <Caption dark>Whether it&apos;s available — never how many you have.</Caption>
              </div>
            </Stage>
          }
        >
          <FeatureText>
            A product feed and a connection other AI assistants can use to search your catalogue.
            Every price says when it was read, and stock is shown as available or not — never as a
            number.
          </FeatureText>
        </Feature>
      </Features>

      <Band
        title="Helpful. Never pushy."
        lede="Shoppers trust a shop that doesn't play tricks. So NEURA-SELL doesn't."
        items={[
          { title: "No fake urgency", body: "Never “only 2 left!” or “12 people are looking”." },
          {
            title: "No made-up claims",
            body: "Never “customers also bought” — it only says what it can back up.",
          },
          {
            title: "Same for everyone",
            body: "Every shopper sees the same suggestions and the same prices.",
          },
          {
            title: "Only what you sell",
            body: "Every product it names comes from your catalogue.",
          },
        ]}
      />

      <Questions
        items={[
          {
            q: "Will it suggest products I don't sell?",
            a: "No. Every product it names comes from your own catalogue.",
          },
          {
            q: "Can I choose the basket suggestions myself?",
            a: "Yes, for any product, in your dashboard. Your choice always wins, for every shopper.",
          },
          {
            q: "Does it track my shoppers?",
            a: "Only if you switch product views on for the Sold out list — and even then, never who they are.",
          },
          {
            q: "Does it work with NEURA-CARE?",
            a: "Yes — one chat box. Questions about orders and policies go to NEURA-CARE; “what should I buy?” goes to NEURA-SELL.",
          },
        ]}
      />

      <CallToAction
        title="See it pick from your own catalogue."
        lede="We connect your shop with you, and you try it in practice mode first."
      />
    </>
  );
}
