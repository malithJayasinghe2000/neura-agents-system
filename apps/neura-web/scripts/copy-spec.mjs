// The OpenAPI file developers download is `docs/spec/openapi.json`, copied at
// build time rather than committed twice — two copies drift, and a developer
// building a bridge from a stale one builds the wrong thing.
//
// Only the OpenAPI file. The written specification beside it names commerce
// platforms, and the public site may not (AGENTS.md Rule 1; ADR-0051 §3).
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "..", "..", "..", "docs", "spec", "openapi.json");
const target = join(here, "..", "public", "spec", "openapi.json");

mkdirSync(dirname(target), { recursive: true });
copyFileSync(source, target);
