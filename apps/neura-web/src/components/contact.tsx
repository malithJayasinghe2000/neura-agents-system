import { CONTACT_LABEL } from "@/lib/site";

/**
 * The one place the contact address is written. "Talk to us" and "Sign in" lead
 * here until their addresses are decided (lib/site.ts).
 */
/** `anchor` marks the one line "#contact" links to: the footer's. An id may appear once per page. */
export function ContactLine({ anchor }: { anchor?: boolean }) {
  return (
    <p id={anchor ? "contact" : undefined} className="m-0 text-sm text-body">
      Talk to FiveNeurals: <span className="font-medium text-ink">{CONTACT_LABEL}</span>
    </p>
  );
}
