import type { Metadata } from "next";
import { CalendarDays, Link as LinkIcon } from "lucide-react";
import {
  Band,
  CallToAction,
  Caption,
  Card,
  Feature,
  FeatureText,
  Features,
  Hero,
  HowItWorks,
  Questions,
  Stage,
} from "@/components/marketing";

/**
 * NEURA-GROW: G132, the owner's word 2026-11-17 (no mockup: "you can build").
 *
 * **Written only from docs/FEATURES.md's NEURA-GROW lines and limits L6 to L8**
 * (ADR-0051): every sentence here is something the code does. The claims each
 * limit forbids are not made: not "finds every missing answer", not "tells you
 * what to sell", not "posts for you", not "schedules your campaigns", not "in
 * Sinhala and Tamil", not "visitors", not "sales from each post". **No counts
 * or results**: the pictures show no numbers that could be read as measured.
 */
export const metadata: Metadata = {
  title: "NEURA-GROW",
  description:
    "NEURA-GROW shows what shoppers asked that your pages don't say, plans a campaign or a greeting for your special dates, and gives you links that count their clicks.",
};

function Asked() {
  return (
    <div className="flex items-center justify-center rounded-[28px] bg-hush px-4 py-8 lg:min-h-[580px]">
      <Card className="max-w-[480px] rounded-[20px]">
        <div className="border-b border-[#efefef] px-5 py-4 text-[15px] font-semibold">
          Missing from your pages
        </div>
        <div className="flex flex-col gap-2 px-5 py-5">
          <span className="text-[13px] text-quiet">Shoppers asked</span>
          <span className="text-lg font-semibold">&ldquo;Does it contain caffeine?&rdquo;</span>
          <span className="text-[15px] leading-[1.55] text-body">
            Your page doesn&apos;t say. Add the answer to its description in your shop.
          </span>
          <span className="mt-1 text-[15px] font-semibold">Cinnamon Tea Bags</span>
          <div className="mt-2 flex flex-wrap gap-2">
            {["Open the page", "See the chats", "I added it"].map((label) => (
              <span
                key={label}
                className="flex h-8 items-center rounded-lg border border-line px-3 text-[13px] font-medium"
              >
                {label}
              </span>
            ))}
          </div>
        </div>
        <div className="border-t border-[#efefef] px-5 py-3.5">
          <Caption>Only you know the answer, so GROW never writes it.</Caption>
        </div>
      </Card>
    </div>
  );
}

export default function GrowPage() {
  return (
    <>
      <Hero
        pill="NEURA-GROW · Marketing"
        title="Learn from what shoppers ask. Plan for the days that matter."
        lede="NEURA-GROW reads your assistant's chats once a night and shows you what shoppers asked that your pages don't say, and what they asked for that you don't sell. It keeps your special dates, suggests a campaign or a greeting for each, and gives you links that count their clicks."
        ticks={["From your own shop's data", "You post it yourself", "Counts, never who"]}
        picture={<Asked />}
      />

      <HowItWorks
        lede="No chat and nothing for shoppers to see. It works in the background and shows you what it found."
        steps={[
          {
            title: "Shoppers ask your assistant",
            body: "“Does it contain caffeine?” “Do you have matcha?” Some questions your shop's pages can't answer.",
          },
          {
            title: "Once a night, GROW reads the new chats",
            body: "It notes each question your pages don't answer, and each thing you don't sell. A question shows when at least two shoppers asked it.",
          },
          {
            title: "You decide what to do",
            body: "Add the answer to your page, start selling what people want, or use it in your next campaign. GROW never changes your shop.",
          },
        ]}
      />

      <Features label="What NEURA-GROW does">
        <Feature
          eyebrow="Missing from your pages"
          title="The questions your product pages don't answer."
          picture={
            <Stage>
              <Card>
                <div className="border-b border-[#efefef] px-[18px] py-3.5 text-sm font-semibold">
                  Shoppers asked · last 30 days
                </div>
                {[
                  { q: "“Does it contain caffeine?”", where: "Cinnamon Tea Bags" },
                  { q: "“Can I pay cash on delivery?”", where: "About your shop" },
                ].map((row, i) => (
                  <div
                    key={row.q}
                    className={`flex flex-col gap-0.5 px-[18px] py-3.5 ${i === 0 ? "border-b border-[#f4f4f4]" : ""}`}
                  >
                    <span className="text-[15px] font-semibold">{row.q}</span>
                    <span className="text-[13px] text-quiet">{row.where}</span>
                  </div>
                ))}
              </Card>
            </Stage>
          }
        >
          <FeatureText>
            Shows what shoppers asked that your pages don&apos;t say, grouped by product. Each one
            says where the answer belongs, with a link to the product&apos;s page. Press{" "}
            <em>I added it</em> and it leaves the list until shoppers ask again.
          </FeatureText>
        </Feature>

        <Feature
          flip
          eyebrow="Shoppers asked for"
          title="What shoppers wanted that you don't sell."
          picture={
            <Stage>
              <Card>
                <div className="border-b border-[#efefef] px-[18px] py-3.5 text-sm font-semibold">
                  Shoppers asked for · last 30 days
                </div>
                {["Matcha powder", "Tea strainer"].map((name, i) => (
                  <div
                    key={name}
                    className={`flex items-center gap-3 px-[18px] py-3.5 ${i === 0 ? "border-b border-[#f4f4f4]" : ""}`}
                  >
                    <span className="flex-1 text-[15px] font-semibold">{name}</span>
                    <span className="flex h-7 items-center rounded-full border border-line px-3 text-[13px] font-medium">
                      See the chats
                    </span>
                  </div>
                ))}
              </Card>
            </Stage>
          }
        >
          <FeatureText>
            Shows what shoppers asked for that you don&apos;t sell, most asked first, so you can
            decide whether to start selling it. Only the owner sees this list.
          </FeatureText>
        </Feature>

        <Feature
          eyebrow="Marketing calendar"
          title="A plan for each special date. You choose what it's about."
          picture={
            <Stage tall>
              <div className="flex w-full max-w-[440px] flex-col gap-3">
                <Card className="max-w-none">
                  <div className="flex items-start gap-3 border-b border-[#efefef] px-[18px] py-4">
                    <CalendarDays
                      className="mt-0.5 size-5 shrink-0"
                      strokeWidth={1.75}
                      aria-hidden
                    />
                    <span className="flex flex-col gap-0.5">
                      <span className="text-[15px] font-semibold">
                        Vesak is in 28 days. Choose what its plan is about.
                      </span>
                      <span className="text-[13px] text-quiet">
                        A religious day: your assistant suggests a respectful greeting, not a sale.
                      </span>
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2 px-[18px] py-4">
                    <span className="flex h-8 items-center rounded-lg bg-ink px-3 text-[13px] font-medium text-white">
                      A greeting only
                    </span>
                    {["Choose other products", "Skip this date"].map((label) => (
                      <span
                        key={label}
                        className="flex h-8 items-center rounded-lg border border-line px-3 text-[13px] font-medium"
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                </Card>
                <Caption>
                  Nothing is written until you choose. Nothing is ever posted for you.
                </Caption>
              </div>
            </Stage>
          }
        >
          <FeatureText>
            Your shop&apos;s special dates: Sri Lanka&apos;s festivals and payday, the big shopping
            days, and your own. Four weeks before each one, your assistant suggests what its plan is
            about: products of yours that fit the day, or a greeting when none does. You choose, and
            it writes the plan from your shop&apos;s own data: the idea, when to post, and draft
            posts, an email and a banner, with{" "}
            <strong className="font-semibold text-ink">[your offer]</strong> for you to fill in. You
            edit it, copy it and post it yourself.
          </FeatureText>
        </Feature>

        <Feature
          flip
          eyebrow="Links"
          title="Links that count their clicks."
          picture={
            <Stage>
              <Card className="flex flex-col gap-3.5 p-5">
                <span className="text-[15px] font-semibold">This post&apos;s links</span>
                <div className="flex flex-wrap gap-2">
                  {["Copy Facebook link", "Copy Instagram link", "Copy WhatsApp link"].map(
                    (label) => (
                      <span
                        key={label}
                        className="flex h-8 items-center gap-1.5 rounded-lg border border-line px-3 text-[13px] font-medium"
                      >
                        <LinkIcon className="size-3.5" strokeWidth={1.75} aria-hidden />
                        {label}
                      </span>
                    ),
                  )}
                </div>
                <Caption>Each tap is counted and opens the product on your shop.</Caption>
              </Card>
            </Stage>
          }
        >
          <FeatureText>
            Links that count their clicks, so you see which post brought people to your shop. A
            ready link for each post of a plan, and one for any product, any day. No setup in your
            shop. We keep one number per link per day, and nothing about the person who tapped.
          </FeatureText>
        </Feature>
      </Features>

      <Band
        title="Your shop speaks for itself."
        lede="GROW helps you decide. It never acts in your name."
        items={[
          {
            title: "Nothing posted for you",
            body: "Every plan is a draft. You edit it, copy it and post it yourself.",
          },
          {
            title: "Never writes your facts",
            body: "It shows what shoppers asked. Only you write the answer.",
          },
          {
            title: "No made-up claims",
            body: "No price, no health claim, no “only a few left” in any draft.",
          },
          {
            title: "Counts, never who",
            body: "How many asked, how many tapped. Never who they were.",
          },
        ]}
      />

      <Questions
        items={[
          {
            q: "Does it post on my social media?",
            a: "No. It writes drafts. You copy them and post them yourself, when you choose.",
          },
          {
            q: "Does it count sales from each post?",
            a: "No. It counts clicks on its links. If you use a website analytics tool, the links carry campaign labels it can read.",
          },
          {
            q: "Which languages are the plans in?",
            a: "English, for now.",
          },
          {
            q: "Does it need chats to work?",
            a: "The two lists come from your assistant's chats. The calendar and the links work from the first day, with no chats.",
          },
        ]}
      />

      <CallToAction
        title="See what your shoppers are asking."
        lede="We connect your shop with you, and NEURA-GROW is switched on for it."
      />
    </>
  );
}
