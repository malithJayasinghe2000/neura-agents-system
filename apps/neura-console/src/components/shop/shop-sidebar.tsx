"use client";

/**
 * One shop's side menu — the frame every screen of a shop sits in.
 *
 * Replaced the row of tabs (2026-09-27, the owner's approved mockup): seven
 * screens had outgrown a tab strip, and a shop owner needs the shop's **name**
 * and a way to another shop in the same place every time. The screens are split
 * the way an owner uses them — the everyday ones first, *Setup* below.
 *
 * **Nothing here is authorisation.** The review count is read by the layout
 * from the same membership-checked API every page uses, and each page still
 * asks the API for itself (ADR-0026 §3). This component only draws links.
 *
 * A client component for three reasons: it has to know which screen is open
 * (`usePathname`), on a phone it folds into one menu button, and it re-reads the
 * Review count as the owner moves around. The layout's count is read **once** —
 * a layout does not re-render when a nested page navigates, or when a reply is
 * opened (`?turn=`) — so the menu said *Review 5* while the page said *To review
 * 6* (G40 in docs/CONNECTING_A_NEW_SHOP_LOG.md). A failed re-read keeps the last
 * number rather than dropping the badge.
 */
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  CalendarDays,
  Link as LinkIcon,
  ChevronsUpDown,
  CircleQuestionMark,
  ClipboardCheck,
  FileQuestionMark,
  House,
  Menu,
  Eye,
  MessageSquare,
  Plug,
  ShoppingBag,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { ShoppingBagPlus } from "@/components/shopping-bag-plus";
import { SignOutButton } from "@/components/sign-out-button";
import { WAITING_CHANGED, readHome, readScorecard } from "@/lib/api";
import { cn } from "@/lib/utils";

type Item = {
  href: string;
  label: string;
  icon: LucideIcon;
  waiting?: number;
  /** Amber, not black: a person waits, not a reply (ADR-0062, the approved mockup). */
  urgent?: boolean;
  shown: boolean;
};

/** Which screens the person's role may open, by name (`lib/roles.ts`). */
type Opens = Record<
  | "home"
  | "conversations"
  | "review"
  | "suggestions"
  | "soldOut"
  | "connection"
  | "connect"
  | "contact"
  | "mode"
  | "usage"
  | "people"
  | "handovers"
  | "gaps"
  | "wanted"
  | "calendar"
  | "links",
  boolean
>;

export function ShopSidebar({
  tenantId,
  shopName,
  waiting,
  answering,
  sell,
  grow,
  role,
  opens,
}: {
  tenantId: string;
  shopName: string;
  /** Whether the shop has NEURA-SELL. Without it, its two screens are not listed. */
  sell: boolean;
  /** Whether the shop has NEURA-GROW. Without it, its four pages are not listed. */
  grow: boolean;
  /** Replies waiting in Review. `null` when it could not be read — then no badge, not a 0. */
  waiting: number | null;
  /** Handed-over shoppers waiting for an answer (ADR-0062). `null`: not this role's, or unread. */
  answering: number | null;
  /** *Owner*, *Support* or *Developer*, for *You're the …* (ADR-0058). Empty: unknown. */
  role: string;
  /** What the role may open. A screen it may not open is not listed (the API still refuses it). */
  opens: Opens;
}) {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(waiting);
  const [fromServer, setFromServer] = useState(waiting);
  const base = `/console/${encodeURIComponent(tenantId)}`;

  const [answer, setAnswer] = useState(answering);
  const [answerFromServer, setAnswerFromServer] = useState(answering);

  // A fresh number from the server (`router.refresh()` after grading) wins —
  // adjusted while rendering, React's pattern for state that follows a prop.
  if (waiting !== fromServer) {
    setFromServer(waiting);
    setCount(waiting);
  }
  if (answering !== answerFromServer) {
    setAnswerFromServer(answering);
    setAnswer(answering);
  }

  // And on every move — another screen, or another reply opened in Review.
  // Not for a role without Review: the count would be a refusal.
  useEffect(() => {
    if (!opens.review) return;
    let current = true;
    readScorecard(tenantId)
      .then((card) => {
        if (current) setCount(card.ungraded);
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [tenantId, pathname, search, opens.review]);

  // The shoppers waiting for an answer, re-read the same way: *Mark as answered*
  // on one chat must not leave the menu saying the old number.
  // And at once when a chat on this page is marked answered.
  useEffect(() => {
    if (!opens.handovers) return;
    let current = true;
    const reread = () => {
      readHome(tenantId)
        .then((home) => {
          if (current) setAnswer(home.waiting);
        })
        .catch(() => {});
    };
    reread();
    window.addEventListener(WAITING_CHANGED, reread);
    return () => {
      current = false;
      window.removeEventListener(WAITING_CHANGED, reread);
    };
  }, [tenantId, pathname, search, opens.handovers]);

  const everyday: Item[] = [
    { href: base, label: "Home", icon: House, shown: true },
    {
      href: `${base}/review`,
      label: "Review",
      icon: ClipboardCheck,
      waiting: count ?? 0,
      shown: opens.review,
    },
    {
      href: `${base}/conversations`,
      label: "Conversations",
      icon: MessageSquare,
      waiting: answer ?? 0,
      urgent: true,
      shown: opens.conversations,
    },
    {
      href: `${base}/suggestions`,
      label: "Suggestions",
      icon: ShoppingBag,
      shown: sell && opens.suggestions,
    },
    // Two tabs since ADR-0071 (Sold out, Rarely added to cart), named for what both are made of (G118, R81).
    {
      href: `${base}/sold-out`,
      label: "Product views",
      icon: Eye,
      shown: sell && opens.soldOut,
    },
    {
      href: `${base}/gaps`,
      label: "Missing from your pages",
      icon: FileQuestionMark,
      shown: grow && opens.gaps,
    },
    {
      href: `${base}/wanted`,
      label: "Shoppers asked for",
      icon: ShoppingBagPlus,
      shown: grow && opens.wanted,
    },
    // ADR-0072, board 75: the Owner's and Support's (R86).
    {
      href: `${base}/calendar`,
      label: "Marketing calendar",
      icon: CalendarDays,
      shown: grow && opens.calendar,
    },
    // ADR-0074, board 81: links that count clicks, the Owner's and Support's (R115).
    {
      href: `${base}/links`,
      label: "Links",
      icon: LinkIcon,
      shown: grow && opens.links,
    },
  ].filter((item) => item.shown);
  const setup: Item[] = [
    { href: `${base}/shops`, label: "Shop connection", icon: Plug, shown: opens.connection },
    { href: `${base}/usage`, label: "Usage and cost", icon: BarChart3, shown: opens.usage },
    // Who can open the shop: the Owner's alone (ADR-0058 §4).
    { href: `${base}/people`, label: "People", icon: Users, shown: opens.people },
    { href: `${base}/help`, label: "Help", icon: CircleQuestionMark, shown: true },
  ].filter((item) => item.shown);

  // Home is the shop's own address, so it is current only on exactly that
  // address — otherwise it would be lit on every screen beneath it.
  const isCurrent = (href: string) =>
    href === base ? pathname === base : pathname === href || pathname.startsWith(`${href}/`);
  const close = () => setOpen(false);

  return (
    <>
      <div className="sticky top-0 z-20 flex h-14 items-center gap-1 border-b bg-background px-2 md:hidden">
        <button
          type="button"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="shop-menu"
          onClick={() => setOpen((was) => !was)}
          className="grid size-11 place-items-center rounded-lg outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <span className="relative">
            {open ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
            {/* Someone waits for an answer: the phone's alert, where the
                menu's count is folded away (ADR-0062, the approved mockup). */}
            {!open && answer ? (
              <span
                data-waiting-dot
                className="absolute -top-1 -right-1.5 size-2.5 rounded-full border-2 border-background bg-amber-500"
              />
            ) : null}
          </span>
          {!open && answer ? (
            <span className="sr-only">
              , {answer === 1 ? "1 shopper waits" : `${answer} shoppers wait`} for an answer
            </span>
          ) : null}
        </button>
        <span className="truncate font-semibold">{shopName}</span>
      </div>

      <aside
        id="shop-menu"
        className={cn(
          "border-b bg-sidebar md:sticky md:top-0 md:flex md:h-dvh md:w-64 md:shrink-0 md:flex-col md:border-r md:border-b-0",
          open ? "flex flex-col" : "hidden",
        )}
      >
        <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-5">
          <Brand className="hidden px-2 md:flex" />

          <Link
            href="/console"
            onClick={close}
            className="flex items-center gap-2.5 rounded-lg border bg-background px-3 py-2.5 outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">{shopName}</span>
              <span className="block text-xs text-muted-foreground" data-your-role>
                {role ? `You're the ${role} · Switch shop` : "Switch shop"}
              </span>
            </span>
            <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          </Link>

          <nav aria-label="Screens" className="flex flex-col gap-0.5">
            {everyday.map((item) => (
              <NavLink key={item.href} item={item} current={isCurrent(item.href)} onPick={close} />
            ))}
            <p className="px-3 pt-4 pb-1.5 text-xs font-medium text-muted-foreground">Setup</p>
            {setup.map((item) => (
              <NavLink key={item.href} item={item} current={isCurrent(item.href)} onPick={close} />
            ))}
          </nav>

          <SignOutButton className="mt-auto h-10 justify-start px-3 text-sm font-normal text-muted-foreground" />
        </div>
      </aside>
    </>
  );
}

function NavLink({ item, current, onPick }: { item: Item; current: boolean; onPick: () => void }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onPick}
      aria-current={current ? "page" : undefined}
      className={cn(
        "flex h-10 items-center gap-2.5 rounded-lg px-3 text-sm outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
        current
          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
          : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
      )}
    >
      <Icon className="size-4.5 shrink-0" aria-hidden />
      <span className="flex-1">{item.label}</span>
      {item.waiting ? (
        <>
          <span
            aria-hidden
            data-waiting-count={item.urgent ? "" : undefined}
            className={cn(
              "grid h-5 min-w-5 place-items-center rounded-full px-1.5 text-xs font-semibold tabular-nums",
              item.urgent ? "bg-amber-400 text-amber-950" : "bg-foreground text-background",
            )}
          >
            {item.waiting}
          </span>
          <span className="sr-only">
            , {item.waiting} {item.urgent ? "waiting for an answer" : "waiting"}
          </span>
        </>
      ) : null}
    </Link>
  );
}
