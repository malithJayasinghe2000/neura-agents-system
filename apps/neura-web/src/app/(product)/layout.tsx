import Link from "next/link";
import { Brand } from "@/components/brand";
import { ContactLine } from "@/components/contact";
import { Nav } from "@/components/nav";
import { CONTACT_HREF, SIGN_IN_HREF } from "@/lib/site";

const ITEMS = [
  { href: "/", label: "NEURA-CARE" },
  { href: "/sell/", label: "NEURA-SELL" },
  { href: "/docs/", label: "Docs" },
];

export default function ProductLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="relative flex h-[60px] shrink-0 items-center gap-9 border-b border-[#ececec] px-4 md:h-[72px] md:px-16">
        <Brand href="/" />
        <Nav items={ITEMS} label="Products" />
        <a href={SIGN_IN_HREF} className="hidden text-[15px] font-medium no-underline md:inline">
          Sign in
        </a>
        <a
          href={CONTACT_HREF}
          className="hidden h-[42px] items-center rounded-[10px] bg-ink px-[18px] text-[15px] font-medium text-white no-underline hover:bg-[#262626] md:flex"
        >
          Talk to us
        </a>
      </header>
      <main className="flex flex-1 flex-col">{children}</main>
      <footer className="flex flex-col gap-3 border-t border-[#ececec] px-5 py-6 md:flex-row md:items-center md:gap-7 md:px-16">
        <span className="text-sm text-quiet">FiveNeurals</span>
        <Link href="/" className="text-sm text-body">
          NEURA-CARE
        </Link>
        <Link href="/sell/" className="text-sm text-body">
          NEURA-SELL
        </Link>
        <Link href="/docs/" className="text-sm text-body">
          Docs
        </Link>
        <span className="md:ml-auto">
          <ContactLine anchor />
        </span>
      </footer>
    </div>
  );
}
