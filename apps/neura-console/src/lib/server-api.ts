/**
 * Reading the API from a server component. ADR-0026.
 *
 * **This is the other half of `lib/api.ts`, not a duplicate of it.** They talk
 * to the same endpoints over two entirely different paths, and each one is wrong
 * in the other's place:
 *
 * | | who runs it | address | the cookie |
 * |:--|:--|:--|:--|
 * | `lib/api.ts` | the browser | `/api/*`, same-origin | attached by the browser |
 * | this file | the Node server | the API's real host | forwarded by hand |
 *
 * A server component has no browser and therefore no origin to be cross, so it
 * calls the API directly. It also has no ambient cookie jar: `fetch` here sends
 * nothing unless told to, and **the failure is silent** — forget the header and
 * every visitor looks permanently signed out, with no error anywhere. That
 * mistake was made once already while building screen 1, which is why the
 * forwarding lives in one function now instead of in each page.
 *
 * The API key rule is unchanged and applies here too: there is no key in this
 * file. The cookie names a person and the server re-derives what they may do.
 */
import { cookies } from "next/headers";

/**
 * The API's real address. Only ever used from the server — putting this in a
 * client bundle would make the browser talk to another origin, which is the one
 * thing `next.config.ts` exists to prevent.
 */
const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8010";

/** The session cookie's name. `__Host-` is enforced by the browser (ADR-0026 §3). */
export const SESSION_COOKIE = "__Host-fn_session";

type Envelope<T> = { data: T; meta?: PageMeta; error?: { message?: string } };

/**
 * The pagination half of the envelope. Carried through rather than dropped:
 * a list page that cannot reach `next_cursor` shows a merchant the first twenty
 * turns and silently withholds the rest — which is sampling, arrived at by
 * accident, in the one screen whose design says not to sample.
 */
export type PageMeta = {
  next_cursor?: string | null;
  has_more?: boolean;
  /** How many match in all — for the words "26–50 of 55". Not every list sends it. */
  total?: number;
  /** How many matching rows come before this page. Counted, never used to fetch. */
  offset?: number;
  has_previous?: boolean;
  /** `null` with `has_previous` true: the page before is the first page. */
  previous_cursor?: string | null;
};

export type ServerResult<T> =
  { ok: true; data: T; meta: PageMeta } | { ok: false; status: number; message: string };

/**
 * Fetch one console endpoint as the signed-in person.
 *
 * Returns a result rather than throwing, because every caller here is a page
 * and a page has to render something. An unreachable API and a 404 are different
 * screens, and a `try`/`catch` around a throw tends to collapse them into one
 * apologetic blank.
 */
export async function fromApi<T>(path: string, prefix = "/v1/console"): Promise<ServerResult<T>> {
  const jar = await cookies();
  const session = jar.get(SESSION_COOKIE);
  if (!session) return { ok: false, status: 401, message: "Not signed in." };

  // `prefix` is `/v1/console` for every screen the API serves itself, and an
  // agent's own prefix for a screen an agent serves (ADR-0050's Suggestions).
  const response = await fetch(`${API_BASE}${prefix}${path}`, {
    headers: { Cookie: `${session.name}=${session.value}` },
    // Never cached. This is one person's view of one merchant's data, and a
    // cache key that missed either of those would serve it to the wrong reader.
    cache: "no-store",
  }).catch(() => null);

  if (!response) {
    return { ok: false, status: 503, message: "The API is not reachable." };
  }

  const body = (await response.json().catch(() => null)) as Envelope<T> | null;

  if (!response.ok || !body) {
    return {
      ok: false,
      status: response.status,
      message: body?.error?.message ?? `Request failed (${response.status})`,
    };
  }
  return { ok: true, data: body.data, meta: body.meta ?? {} };
}

/** Is anybody signed in at all? Cheap, and asked before anything else renders. */
export async function hasSession(): Promise<boolean> {
  const jar = await cookies();
  return jar.get(SESSION_COOKIE) !== undefined;
}
