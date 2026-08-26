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
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_BASE}/:path*` }];
  },
};

export default nextConfig;
