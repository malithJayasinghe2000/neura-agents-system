import type { NextConfig } from "next";

/**
 * The console proxies the API through its own origin. ADR-0026.
 *
 * **This is a security decision, not a convenience.** The session is a cookie,
 * and a cookie is an *ambient* credential — the browser attaches it to requests
 * the page did not intend. `middleware/cors.py` is explicit that the API sets
 * `allow_credentials: false` precisely because its credential is a bearer token,
 * so "there are no ambient credentials for a hostile page to ride on", and that
 * CORS there is defence in depth rather than the access control.
 *
 * Letting the browser call the API cross-origin with `credentials: "include"`
 * would require flipping that flag — which would make **every** endpoint in the
 * API reachable with the merchant's ambient session from any page that asked.
 * That is CSRF, bought for the sake of a dev-time convenience.
 *
 * So the browser only ever talks to the console's own origin. Requests to
 * `/api/*` are rewritten server-side to the API, which makes the session cookie
 * first-party, requires no CORS at all, and is the same shape in development
 * and behind a single production hostname.
 */
const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8010";

const nextConfig: NextConfig = {
  /**
   * `next dev` otherwise writes its own `AGENTS.md` and `CLAUDE.md` into this
   * directory on every start.
   *
   * **Those two filenames are taken.** This repository's `AGENTS.md` is its
   * operating manual and `CLAUDE.md` is the entry point every fresh session is
   * told to read first; a second pair inside `apps/neura-console` means a
   * session working on the console loads Next's release notes where the project
   * expects its own rules. That is a collision, not a duplicate.
   *
   * The content they carry is still worth knowing and is not lost: **Next 16
   * has breaking changes from Next 15**, and the authoritative guides ship in
   * `apps/neura-console/node_modules/next/dist/docs/`. Read those before writing
   * against an API you remember rather than one you have checked.
   */
  agentRules: false,

  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_BASE}/:path*` }];
  },
};

export default nextConfig;
