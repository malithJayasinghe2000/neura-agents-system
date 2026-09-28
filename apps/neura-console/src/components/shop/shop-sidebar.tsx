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
 * A client component for two reasons only: it has to know which screen is open
 * (`usePathname`), and on a phone it folds into one menu button.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  BarChart3,
  ChevronsUpDown,
  CircleQuestionMark,
  ClipboardCheck,
  House,
  Menu,
  MessageSquare,
  PackageX,
  Plug,
  ShoppingBag,
  X,
  type LucideIcon,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { SignOutButton } from "@/components/sign-out-button";
import { cn } from "@/lib/utils";

type Item = { href: string; label: string; icon: LucideIcon; waiting?: number };

export function ShopSidebar({
  tenantId,
  shopName,
  waiting,
}: {
  tenantId: string;
  shopName: string;
  /** Replies waiting in Review. `null` when it could not be read — then no badge, not a 0. */
  waiting: number | null;
}) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const base = `/console/${encodeURIComponent(tenantId)}`;

  const everyday: Item[] = [
    { href: base, label: "Home", icon: House },
    { href: `${base}/review`, label: "Review", icon: ClipboardCheck, waiting: waiting ?? 0 },
    { href: `${base}/conversations`, label: "Conversations", icon: MessageSquare },
    { href: `${base}/suggestions`, label: "Suggestions", icon: ShoppingBag },
    { href: `${base}/sold-out`, label: "Sold out", icon: PackageX },
  ];
  const setup: Item[] = [
    { href: `${base}/shops`, label: "Shop connection", icon: Plug },
    { href: `${base}/usage`, label: "Usage and cost", icon: BarChart3 },
    { href: `${base}/help`, label: "Help", icon: CircleQuestionMark },
  ];

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
          {open ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
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
              <span className="block text-xs text-muted-foreground">Switch shop</span>
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
            className="grid h-5 min-w-5 place-items-center rounded-full bg-foreground px-1.5 text-xs font-semibold text-background tabular-nums"
          >
            {item.waiting}
          </span>
          <span className="sr-only">, {item.waiting} waiting</span>
        </>
      ) : null}
    </Link>
  );
}
