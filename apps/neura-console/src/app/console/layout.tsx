/**
 * The frame every console screen sits in. ADR-0026.
 *
 * **Deliberately empty since 2026-09-27.** It drew a header — wordmark and
 * *Sign out* — for every screen; a shop's screens now carry both in their side
 * menu (`[tenantId]/layout.tsx`), and a header here as well would print them
 * twice. The one screen outside a shop, the list of shops, draws its own.
 *
 * **No data is fetched here**, for the reason that has not changed: a layout in
 * Next renders once and is *not* re-rendered when a nested page navigates, so a
 * membership check placed here would be a check that runs on entry and then
 * stops running — the opposite of ADR-0026 §3's point that access is re-derived
 * per request. Every page below does its own `/me` and its own `acting_for`.
 */
import { TimeZoneCookie } from "@/components/time-zone-cookie";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh">
      {/* So a screen that groups or filters by day uses the reader's day. */}
      <TimeZoneCookie />
      {children}
    </div>
  );
}
