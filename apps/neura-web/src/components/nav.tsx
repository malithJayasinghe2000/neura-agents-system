"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";

export type NavItem = { href: string; label: string };

/** Trailing slashes are on (next.config.ts), so compare without them. */
function isCurrent(pathname: string, href: string): boolean {
  const strip = (p: string) => (p.length > 1 ? p.replace(/\/$/, "") : p);
  return strip(pathname) === strip(href);
}

/** The header's links: inline from `md`, one menu button below it. */
export function Nav({ items, label }: { items: NavItem[]; label: string }) {
  const pathname = usePathname();
  const links = (className: string) =>
    items.map((item) => {
      const current = isCurrent(pathname, item.href);
      return (
        <Link
          key={item.href + item.label}
          href={item.href}
          aria-current={current ? "page" : undefined}
          className={`${className} ${current ? "bg-[#f0f0f0] font-medium text-ink" : "text-body hover:bg-[#f0f0f0]"}`}
        >
          {item.label}
        </Link>
      );
    });

  return (
    <>
      <nav aria-label={label} className="hidden flex-1 gap-1 md:flex">
        {links("flex h-10 items-center rounded-lg px-3.5 text-[15px] no-underline")}
      </nav>
      {/* A <details> menu works with no script at all, and is keyboard-reachable by default. */}
      <details className="group ml-auto md:hidden">
        <summary
          aria-label="Open menu"
          className="flex size-11 items-center justify-center rounded-[10px]"
        >
          <Menu className="size-[22px]" strokeWidth={1.75} aria-hidden />
        </summary>
        <nav
          aria-label={label}
          className="absolute inset-x-0 top-[60px] z-20 flex flex-col gap-1 border-b border-line bg-white p-3 shadow-sm"
        >
          {links("flex h-11 items-center rounded-lg px-3 text-base no-underline")}
        </nav>
      </details>
    </>
  );
}
