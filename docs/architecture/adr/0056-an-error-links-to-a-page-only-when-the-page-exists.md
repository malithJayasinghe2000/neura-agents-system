# ADR-0056 · An Error Links To A Page Only When The Page Exists

**Status:** **Accepted** · owner decision, 2026-10-06: G62, *"A is ok"* (remove the link until error pages
exist), from three choices (remove it; point it at the guide's *If something doesn't work*; build a page per
error) ([CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, G62) · **Date:**
2026-10-06 · **Amends:** [api-design.md](../api-design.md), the error shape and *Copy-pasteable errors* ·
**Related:** [ADR-0051](0051-the-public-website-is-its-own-app-and-says-only-what-the-code-does.md) (the public website, whose address is
not decided)

> **In one sentence:** NEURA's errors carry no `docs_url` until real error pages exist; when they do, the link
> comes back with a test that every error code has its page.

## Context

Every error NEURA sent carried `"docs_url": "https://docs.fiveneurals.com/errors/<CODE>"`, and api-design.md
promised that *"every `docs_url` resolves to a page explaining the cause and the fix"*. That name has no address
at all (checked 2026-10-01, G62), the public website has no error pages, and its own address is not decided. So
a developer who followed the one link an error gave them, at the moment they were stuck, reached nothing.

## Decision

1. **`docs_url` is removed from every error**: NEURA's own errors (`NeuraError.to_dict`) and the API's handlers
   for a bad request (400), a route or method that does not exist, and an unexpected failure (500).
2. **Nothing else in the error shape changes.** `code` is still the contract clients branch on; `message`,
   `type`, `details` and `request_id` are as before. The message already says what is wrong.
3. **The link comes back only with the pages**: one page per error code on the public website, and, in the
   same change, a test that every code NEURA can send has a page that opens. A promise a test does not hold is
   how this one broke.

## Consequences

- No dead link. A developer reads the message and the code, and quotes `request_id` to us.
- No client reads `docs_url` today: there is no merchant yet (CLAUDE.md §5).
- Copy-pasteable errors stays a goal in api-design.md, marked postponed rather than deleted.

## Not decided here

- Where the error pages live, their address and their words (with the public website's address, ADR-0051).
