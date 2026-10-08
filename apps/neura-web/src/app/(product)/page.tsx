import type { Metadata } from "next";
import Link from "next/link";
import { Check } from "lucide-react";
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
 * NEURA-CARE — canvas board 28, approved by the owner 2026-09-30.
 *
 * `/` is this page because no overview page was designed; the mockup's logo
 * links here too. The orders sentence is kept as the owner approved it,
 * knowing FEATURES.md's L1 (2026-09-30).
 */
export const metadata: Metadata = {
  title: "NEURA-CARE",
  description:
    "NEURA-CARE answers your shoppers' questions about orders, products and your policies — from your own shop — and hands over to your team when it can't help.",
};

function OrderChat() {
  return (
    <div className="flex flex-col gap-4 rounded-[28px] bg-hush px-4 py-8 lg:min-h-[580px] lg:items-center lg:justify-center">
      <Card className="max-w-[480px] rounded-[20px]">
        <ChatHead />
        <div className="flex flex-col gap-3.5 px-[18px] pt-5 pb-5">
          <Asked>Hi — where&apos;s my order? It hasn&apos;t arrived yet.</Asked>
          <div className="flex flex-col gap-2 self-start">
            <span className="max-w-[330px] rounded-[16px_16px_16px_4px] bg-hush px-3.5 py-[11px] text-[15px] leading-[1.5]">
              It was shipped on Monday and is on its way with the carrier. I can pass you to the
              team if you&apos;d like a hand with it.
            </span>
            <span className="flex items-center gap-1.5 text-xs font-medium text-body">
              <Check className="size-[13px] text-accent" strokeWidth={2.2} aria-hidden />
              Looked up your order · checked it&apos;s yours
            </span>
          </div>
          <div className="mt-1 rounded-xl border border-line px-3.5 py-3 text-sm text-quiet">
            Type a message…
          </div>
        </div>
      </Card>
      <div className="flex w-full max-w-[480px] flex-col gap-1 rounded-2xl bg-white px-5 py-4">
        <span className="text-xs font-semibold text-accent">Answered from</span>
        <span className="text-[15px] font-semibold">Your shop&apos;s own order record</span>
        <span className="text-[13px] text-quiet">
          Not a guess, and not another shop&apos;s data.
        </span>
      </div>
    </div>
  );
}

function Tick({ children }: { children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-2.5 text-[15px]">
      <span className="flex size-5 items-center justify-center rounded-full bg-accent text-white">
        <Check className="size-[13px]" strokeWidth={3} aria-hidden />
      </span>
      {children}
    </span>
  );
}

export default function CarePage() {
  return (
    <>
      <Hero
        pill="NEURA-CARE · Customer care"
        title="Customer questions, answered from your own shop."
        lede="NEURA-CARE lives in a chat box on your store. It looks up the order, reads the product page, checks your returns policy — and then answers. When it can't help, it says so and hands over to your team."
        ticks={["Read only", "Answers checked before they're sent", "Practice mode first"]}
        picture={<OrderChat />}
      />

      <HowItWorks
        lede="Three steps, every time a shopper asks something."
        steps={[
          {
            title: "A shopper asks",
            body: "In the chat box on your shop, in their own words — about an order, a product or your policies.",
          },
          {
            title: "It reads your shop",
            body: "The shopper's own order, the product page, your returns and shipping pages. Only reading — it can't change a thing.",
          },
          {
            title: "It answers — or hands over",
            body: "The answer is checked against what it read before it's sent. If it can't help, your team takes over.",
          },
        ]}
      />

      <Features label="What NEURA-CARE does">
        <Feature
          eyebrow="Orders"
          title="“Where's my order?” — answered in seconds, not in your inbox."
          picture={
            <Stage>
              <Card className="flex flex-col gap-3.5 p-5">
                <span className="text-[13px] font-semibold text-quiet">Order lookup</span>
                <div className="flex flex-col gap-3">
                  <Tick>Order found in your shop</Tick>
                  <Tick>It belongs to this shopper</Tick>
                  <Tick>Status: shipped</Tick>
                </div>
                <Caption>
                  Not theirs? It shares nothing, and hands the question to your team.
                </Caption>
              </Card>
            </Stage>
          }
        >
          <FeatureText>
            It looks the order up in your shop and tells the shopper where it is. Before it says a
            word, it checks the order belongs to the person asking — nobody reads someone
            else&apos;s order.
          </FeatureText>
        </Feature>

        <Feature
          flip
          eyebrow="Products"
          title="Knows your products as well as your product pages do."
          picture={
            <Stage>
              <Card className="flex flex-col gap-3 p-5">
                <Asked>Is the Summit jacket waterproof?</Asked>
                <Answered>
                  Yes — its product page says it&apos;s fully waterproof, with taped seams.
                </Answered>
                <span className="flex h-7 items-center gap-1.5 self-start rounded-full border border-line bg-white px-3 text-xs font-medium text-body">
                  <span className="size-1.5 rounded-full bg-accent" />
                  From: Summit jacket, product page
                </span>
              </Card>
            </Stage>
          }
        >
          <FeatureText>
            Sizes, materials, what&apos;s in the box — answered from your own product pages, and it
            knows which page it read. No generic web answers about somebody else&apos;s jacket.
          </FeatureText>
        </Feature>

        <Feature
          eyebrow="Returns and shipping"
          title="Your policies, in your words — every time."
          picture={
            <Stage>
              <Card className="flex flex-col gap-3 p-5">
                <span className="text-[13px] font-semibold text-quiet">Your returns policy</span>
                <span className="text-base leading-[1.55] text-[#262626]">
                  <mark className="rounded bg-accent-soft px-[3px] py-px text-inherit">
                    Unworn items can be returned
                  </mark>{" "}
                  with their tags on. Sale items are final.
                </span>
                <Caption>The highlighted words are what the reply was built on.</Caption>
              </Card>
            </Stage>
          }
        >
          <FeatureText>
            &ldquo;Can I return this?&rdquo; &ldquo;Do you ship abroad?&rdquo; It answers from your
            own returns, shipping and warranty pages, so the answer is the one you wrote — not a
            friendlier one it made up.
          </FeatureText>
        </Feature>

        <Feature
          flip
          eyebrow="Knows when to stop"
          title="When it can't help, it says so. It never bluffs."
          picture={
            <Stage>
              <Card className="flex flex-col gap-3 p-5">
                <Asked>Can you change the address on my order?</Asked>
                <Answered>
                  That&apos;s one for a person. I&apos;ve passed it to the team, with your question.
                </Answered>
                <span className="flex h-7 items-center self-start rounded-full bg-accent px-3 text-xs font-semibold text-white">
                  Handed to your team
                </span>
              </Card>
            </Stage>
          }
        >
          <FeatureText>
            Changing an order, a refund, anything that needs a person — it hands the conversation to
            your team instead of promising something it can&apos;t do.
          </FeatureText>
        </Feature>

        <Feature
          eyebrow="Practice mode"
          title="Read every answer before a single shopper does."
          picture={
            <Stage>
              <Card className="flex flex-col gap-3.5 p-5">
                <span className="flex h-6 items-center self-start rounded-full border border-dashed border-[#a3a3a3] px-2.5 text-xs font-medium text-body">
                  Held — not sent
                </span>
                <span className="text-[15px] leading-[1.55]">
                  &ldquo;Unworn items can be returned with their tags on. Would you like me to pass
                  you to the team to start one?&rdquo;
                </span>
                <div className="grid grid-cols-3 gap-2">
                  <span className="flex h-10 items-center justify-center rounded-[10px] bg-ink text-sm font-medium text-white">
                    Good
                  </span>
                  <span className="flex h-10 items-center justify-center rounded-[10px] border border-[#d4d4d4] text-sm font-medium">
                    Not good
                  </span>
                  <span className="flex h-10 items-center justify-center rounded-[10px] border border-[#d4d4d4] text-sm font-medium">
                    Harmful
                  </span>
                </div>
              </Card>
            </Stage>
          }
        >
          <FeatureText>
            Start in practice mode: your assistant writes its replies, you grade them in your
            dashboard, and shoppers see nothing until you decide it&apos;s ready. Going live is your
            call.
          </FeatureText>
        </Feature>
      </Features>

      <Band
        title="Read only. By design, not by a setting."
        lede="There is simply no button inside NEURA-CARE that changes your shop — so there's nothing for anyone to talk it into."
        items={[
          {
            title: "Can't change your shop",
            body: "No orders, prices or stock. It reads; your team acts.",
          },
          {
            title: "Private details stay hidden",
            body: "Emails, phone numbers, addresses and card numbers are hidden from the AI before it reads a message.",
          },
          {
            title: "Never messages your shoppers",
            body: "It only answers when asked, in the chat box. No emails, no texts.",
          },
        ]}
      />

      <section
        aria-labelledby="any"
        className="flex flex-col gap-4 px-5 pt-14 lg:max-w-[980px] lg:px-16 lg:pt-[104px]"
      >
        <h2
          id="any"
          className="m-0 text-[30px] leading-[1.1] font-bold tracking-[-0.025em] lg:text-[44px]"
        >
          Works with your shop — whatever it&apos;s built on.
        </h2>
        <p className="m-0 text-[17px] leading-[1.6] text-body lg:text-[19px]">
          Your shop connects through a small add-on that follows our published specification. Any
          platform can speak it, including a shop your developer built from scratch. No waiting for
          us to support you.{" "}
          <Link href="/docs/" className="font-medium text-ink">
            Read the docs →
          </Link>
        </p>
      </section>

      <Questions
        items={[
          {
            q: "Will it make things up?",
            a: "It answers from what it reads in your shop, and each answer is checked against that before it's sent. When it can't find the answer, it hands the question to your team rather than guess.",
          },
          {
            q: "Can I see what it told my customers?",
            a: "Yes. Every conversation is in your dashboard, including the ones it handed to your team.",
          },
          {
            q: "Does it need my shop's admin password?",
            a: "No. It uses its own key, which only opens read-only addresses in your shop.",
          },
          {
            q: "Does it work with NEURA-SELL?",
            a: "Yes — one chat box. Each question goes to the assistant that answers that kind of question.",
          },
        ]}
      />

      <CallToAction
        title="Try it on your own shop — in practice mode."
        lede="We connect your shop with you. Your shoppers see nothing until you say so."
      />
    </>
  );
}
