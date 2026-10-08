/**
 * The reader's time zone, as the server sees it.
 *
 * A server's clock is usually UTC, and "today" in Colombo is not "today" in UTC
 * for five and a half hours of every day — so a list grouped by day, or a date
 * filter, worked out on the server in UTC would put last night's replies under
 * the wrong date. The browser knows the zone; `TimeZoneCookie` writes it into a
 * cookie once, and this reads it back.
 *
 * **It is a preference, not a credential.** Nothing is granted by it, it is not
 * `HttpOnly` because the browser writes it, and the API validates the zone name
 * again before using it. A missing or unreadable value means UTC.
 */
import { cookies } from "next/headers";

export const TIME_ZONE_COOKIE = "tz";

export async function readerTimeZone(): Promise<string> {
  const value = (await cookies()).get(TIME_ZONE_COOKIE)?.value;
  if (!value) return "UTC";
  try {
    new Intl.DateTimeFormat("en", { timeZone: value });
    return value;
  } catch {
    return "UTC";
  }
}
