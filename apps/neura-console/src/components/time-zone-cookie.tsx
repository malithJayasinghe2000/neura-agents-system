"use client";

/**
 * Writes the browser's time zone into a cookie the server can read — once, and
 * again only if it changes (a laptop that flew somewhere). See `lib/time-zone.ts`.
 *
 * The first page anybody ever opens is drawn in UTC, because the server has
 * not been told yet; this refreshes it once, and every page after is right.
 */
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export function TimeZoneCookie() {
  const router = useRouter();

  useEffect(() => {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!zone) return;
    const stored = document.cookie
      .split("; ")
      .find((entry) => entry.startsWith("tz="))
      ?.slice(3);
    if (stored === zone) return;
    document.cookie = `tz=${zone}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  }, [router]);

  return null;
}
