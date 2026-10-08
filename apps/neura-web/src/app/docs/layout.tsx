import Link from "next/link";
import { Brand } from "@/components/brand";
import { ContactLine } from "@/components/contact";
import { Nav } from "@/components/nav";
import { OPENAPI_HREF, SIGN_IN_HREF } from "@/lib/site";

const ITEMS = [
  { href: "/docs/owners/", label: "For shop owners" },
  { href: "/docs/developers/", label: "For developers" },
  { href: "/docs/owners/#trouble", label: "If something doesn't work" },
];

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="relative flex h-[60px] shrink-0 items-center gap-8 border-b border-line px-4 md:h-[68px] md:px-14">
        <Brand href="/docs/" suffix="Guide" />
        <Nav items={ITEMS} label="Guides" />
        <a
          href={SIGN_IN_HREF}
          className="hidden h-10 items-center rounded-[10px] border border-[#d4d4d4] px-4 text-sm font-medium no-underline md:flex"
        >
          Sign in to your dashboard
        </a>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="flex flex-col gap-3 border-t border-line px-5 py-6 text-sm md:flex-row md:items-center md:gap-6 md:px-14">
        <Link href="/" className="text-quiet no-underline">
          FiveNeurals
        </Link>
        <a href={OPENAPI_HREF} className="text-body">
          Specification
        </a>
        <Link href="/docs/developers/" className="text-body">
          For developers
        </Link>
        <Link href="/docs/owners/" className="text-body">
          For shop owners
        </Link>
        <span className="md:ml-auto">
          <ContactLine anchor />
        </span>
      </footer>
    </div>
  );
}
