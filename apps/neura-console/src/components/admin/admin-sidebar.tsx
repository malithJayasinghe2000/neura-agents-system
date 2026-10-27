"use client";

/**
 * The FiveNeurals admin's side menu (ADR-0061, board 46; R24: a side menu from
 * the start, because the admin area will grow).
 *
 * The shop menu's look, with two marks that it is not a shop: the black
 * **Admin** badge beside the name, and *FiveNeurals admin, You're an admin ·
 * Your shops* where a shop's menu has its switcher. **Nothing here is
 * authorisation**: every admin page asks the API, which checks the admin list on
 * every request. On a phone it folds into one menu button, as a shop's does.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { BarChart3, ChevronsUpDown, Menu, Store, X, type LucideIcon } from "lucide-react";
import { Brand } from "@/components/brand";
import { SignOutButton } from "@/components/sign-out-button";
import { cn } from "@/lib/utils";

type Item = { href: string; label: string; icon: LucideIcon; waiting?: number };

export function AdminBadge({ className = "" }: { className?: string }) {
  return (
    <span
      className={cn(
        "rounded-full bg-foreground px-2 py-0.5 text-xs font-semibold tracking-wide text-background",
        className,
      )}
    >
      Admin
    </span>
  );
}

export function AdminSidebar({ waiting }: { waiting: number | null }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const items: Item[] = [
    { href: "/admin", label: "Shops", icon: Store, waiting: waiting ?? 0 },
    { href: "/admin/usage", label: "AI use and cost", icon: BarChart3 },
  ];
  // *Shops* is lit on a shop's own page too: it is where that page comes from.
  const isCurrent = (href: string) =>
    href === "/admin"
      ? pathname === "/admin" || pathname.startsWith("/admin/shops")
      : pathname === href || pathname.startsWith(`${href}/`);
  const close = () => setOpen(false);

  return (
    <>
      <div className="sticky top-0 z-20 flex h-14 items-center gap-1 border-b bg-background px-2 md:hidden">
        <button
          type="button"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="admin-menu"
          onClick={() => setOpen((was) => !was)}
          className="grid size-11 place-items-center rounded-lg outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {open ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
        </button>
        <span className="flex-1 truncate font-semibold">FiveNeurals admin</span>
        <AdminBadge className="mr-2" />
      </div>

      <aside
        id="admin-menu"
        className={cn(
          "border-b bg-sidebar md:sticky md:top-0 md:flex md:h-dvh md:w-64 md:shrink-0 md:flex-col md:border-r md:border-b-0",
          open ? "flex flex-col" : "hidden",
        )}
      >
        <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-5">
          <div className="hidden items-center gap-2.5 px-2 md:flex">
            <Brand />
            <AdminBadge />
          </div>

          <Link
            href="/console"
            onClick={close}
            className="flex items-center gap-2.5 rounded-lg border bg-background px-3 py-2.5 outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50"
            data-admin-card
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">FiveNeurals admin</span>
              <span className="block text-xs text-muted-foreground">
                You&apos;re an admin · Your shops
              </span>
            </span>
            <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          </Link>

          <nav aria-label="Admin" className="flex flex-col gap-0.5">
            {items.map((item) => (
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
            className="grid h-5 min-w-5 place-items-center rounded-full bg-amber-500 px-1.5 text-xs font-semibold text-white tabular-nums"
          >
            {item.waiting}
          </span>
          <span className="sr-only">, {item.waiting} waiting for approval</span>
        </>
      ) : null}
    </Link>
  );
}
