import Link from "next/link";

/** The mark and the name. Placeholders like every colour here: branding is not decided. */
export function Brand({ href, suffix }: { href: string; suffix?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2.5 text-ink no-underline">
      <span className="flex size-8 items-center justify-center rounded-lg bg-ink text-[13px] font-semibold text-white">
        5N
      </span>
      <span className="text-[17px] font-semibold">FiveNeurals</span>
      {suffix ? <span className="text-[15px] text-quiet">{suffix}</span> : null}
    </Link>
  );
}
