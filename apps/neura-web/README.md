# neura-web — the public website

NEURA's product pages and docs, as static files. [ADR-0051](../../docs/architecture/adr/0051-the-public-website-is-its-own-app-and-says-only-what-the-code-does.md).

| Page                  | Path                | Canvas board       |
| :-------------------- | :------------------ | :----------------- |
| NEURA-CARE            | `/`                 | 28 (30 on a phone) |
| NEURA-SELL            | `/sell/`            | 29                 |
| Docs home             | `/docs/`            | 24 (27)            |
| Guide for shop owners | `/docs/owners/`     | 26                 |
| Guide for developers  | `/docs/developers/` | 25                 |

```bash
npm install
npm run dev          # http://localhost:3100
make web-check       # from the repository root: build, then check every page in real Chrome
```

- **Say only what is built.** Every sentence must match [`docs/FEATURES.md`](../../docs/FEATURES.md).
- **Made-up examples only** — never the test shop's data. `make web-check` fails on the test shop's product names.
- **Undecided values live in `src/lib/site.ts`** and show as `[PLACEHOLDERS]`; `make web-check` lists them. Do not deploy while any remain.
- No secret, no API call, no cookie, no analytics, no request to another site.
