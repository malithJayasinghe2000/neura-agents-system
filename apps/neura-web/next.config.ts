import type { NextConfig } from "next";

/**
 * The public website: static files and nothing else. ADR-0051.
 *
 * `output: "export"` is the decision in one line. There is no server, so there
 * is no session, no API call and nothing a visitor can reach but HTML, CSS and
 * the OpenAPI file. A page that needed a server would fail the build here,
 * which is where it should fail.
 */
const nextConfig: NextConfig = {
  output: "export",
  // One file per folder (`/docs/owners/index.html`), which any static host serves.
  trailingSlash: true,
  // `next dev` would otherwise write its own AGENTS.md and CLAUDE.md here;
  // those names are the repository's own (see apps/neura-console/next.config.ts).
  agentRules: false,
};

export default nextConfig;
