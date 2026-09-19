# Connecting A Shop To NEURA

How the two systems are wired together, in the order they must be done.

**This is not a Bagisto installation guide.** It assumes the shop already runs and the
[Neura Bridge](https://github.com/malithJayasinghe2000/neura-commerce) package is installed in it.
It covers only the joining-up: what talks to what, which credential goes where, and how to tell at
each step whether it worked.

> **Written 2026-09-19 from the code that provisions a working tenant** (`scripts/widget_check.py`,
> which did exactly this against the real shop that day). **What has NOT been done is a run-through
> on a second machine by a second person** — that is the next real test of this page, and anywhere it
> is wrong or incomplete is worth telling the author about.

---

## 1. The thing everyone gets wrong: there are TWO tokens

They point in **opposite directions**, and confusing them is the commonest way to get stuck.

```
      ┌─────────────────┐                          ┌──────────────────┐
      │   The shop      │   ◀── reads products ──  │      NEURA       │
      │   (Bagisto +    │        orders, policies  │   (this repo)    │
      │    the bridge)  │                          │                  │
      └─────────────────┘                          └──────────────────┘
              ▲                                             ▲
              │                                             │
      NEURA_API_TOKEN                                 fn_pk_… widget key
      lives in the SHOP's .env                        lives in the SHOP's .env too,
      NEURA presents it to read the shop              the shopper's BROWSER presents it
                                                      to talk to NEURA
```

| token | who checks it | where it is stored | what it is for |
|:--|:--|:--|:--|
| **`NEURA_API_TOKEN`** | the **shop** | the shop's `.env` | NEURA proves it may read the catalogue, orders and policies |
| **`fn_pk_…`** | **NEURA** | the shop's `.env` *and* the page source | the shopper's browser proves the chat box may ask questions |

**The second one is public by design.** It is printed in the page source of every storefront page,
and that is safe because it is locked to an origin and carries only the scopes a shopper needs. **The
first one is a real secret** and must never reach a browser.

---

## 2. Before you start, check the shop actually speaks the specification

Do this **first**. If it fails, nothing later can work, and the error you would get instead is much
harder to read.

```bash
make conformance URL=http://bagisto.test/neura/v1 TOKEN="$SHOP_TOKEN"
```

Where `$SHOP_TOKEN` is the value of `NEURA_API_TOKEN` in the shop's `.env`.

It names anything wrong and how to fix it. `/health` is served **without** a token, so you can check
the bridge is mounted before any credential exists:

```bash
curl http://bagisto.test/neura/v1/health
```

> **`/health` returns 200 while everything else 500s?** The shop's `DB_PORT` does not match the port
> MySQL actually listens on. `/health` never touches the database, which is exactly why it stays
> green. Check with `lsof -nP -iTCP -sTCP:LISTEN | grep mysql`, fix the shop's `.env`, then
> `php artisan config:clear`. This cost a day on 2026-09-13.

---

## 3. Create a tenant in NEURA

A **tenant** is one merchant. Everything below hangs off it.

```bash
make tenant-new NAME="My Test Shop" AGENTS=care,sell
```

It prints a `tn_…` id. **Keep it** — every command after this needs it.

`AGENTS` is an entitlement, not a hint: an agent absent from this list returns **403** on its route,
which reads like a bug and is not one.

---

## 4. Connect the shop to the tenant

This writes the row that says *"this tenant's shop lives at this URL, and here is the credential for
reading it"*.

```bash
make sync-check URL=http://bagisto.test/neura/v1 TOKEN="$SHOP_TOKEN" TENANT=tn_…
```

**Without this row, every chat request returns 404 `NO_STORE_CONNECTED`** — a tenant, a key and an
agent are not enough to answer *"where is my order?"*.

> **The merchant console has no connect form, and that is deliberate**
> ([console.md §3.4](console.md)). Screen 4 *shows* the connection; it does not create it. Use this
> command or the API.

---

## 5. Index the shop's text (optional, and know what you lose)

```bash
make rag-check URL=http://bagisto.test/neura/v1 TOKEN="$SHOP_TOKEN" TENANT=tn_… KEEP=1
```

`KEEP=1` matters — without it the script removes what it just indexed.

**Skip this and the agents still work.** They read the shop live through tools; what they lose is
search over indexed policy text.

> **On `cloud-prod` this step cannot run at all.** `CLOUD_MODEL_EMBEDDER` is normally unset, so the
> `EMBEDDER` role is unconfigured and retrieval is switched off — the API logs
> `retrieval_unavailable_no_embedder` and carries on. Turning it on means setting that variable **and
> re-indexing**, because embeddings from different models are not comparable
> ([llm-abstraction §5.2](architecture/llm-abstraction.md)).

---

## 6. Issue the widget key

This is the **public** key the shopper's browser will hold.

```bash
make key-new TENANT=tn_… \
  SCOPES="care:chat:write,care:conversations:read,care:order:read,care:catalogue:read,care:policies:read,care:escalate,sell:chat:write,sell:conversations:read,sell:catalogue:read,sell:escalate" \
  NAME=widget PUBLIC=1 ORIGINS=http://bagisto.test
```

**The token is printed ONCE and never again** — only its hash is stored. Lose it and you issue a new
one and revoke the old.

> **`ORIGINS` is not optional for a public key.** A `fn_pk_` key with an empty origin allowlist
> permits **nothing**, and the symptom is the merchant's own storefront being refused. It must be the
> origin the shopper's browser sees — scheme and host, no trailing slash.

---

## 7. Point the shop at NEURA

Four values in the **shop's** `.env`:

```dotenv
NEURA_API_TOKEN=<the shop's own token — step 2>

NEURA_WIDGET_ENABLED=true
NEURA_WIDGET_HOST=http://localhost:8000
NEURA_WIDGET_KEY=fn_pk_…          # from step 6
```

Then:

```bash
php artisan config:clear
```

**Laravel caches config.** Without that command the file is edited and nothing changes — which looks
exactly like a value that did not work.

`NEURA_WIDGET_HOST` is where **NEURA** runs, not the shop. With `enabled` false — the default —
nothing is emitted into the page at all, which is what you want anywhere there is no NEURA to talk
to.

The bridge mounts the widget into the shop layout's `body.after` render event, so **no core view is
edited** and removing the package removes the widget.

---

## 8. Check it end to end

Start NEURA:

```bash
make api
```

Then drive the real widget, in a real browser, against the real shop:

```bash
make widget-check-live URL=http://localhost:8000 \
  SHOP=http://bagisto.test/neura/v1 TOKEN="$SHOP_TOKEN"
```

It provisions its own throwaway tenant, asks one question in real headless Chrome, and removes the
rows it made. **This is the check that found [Finding 49](TESTING_LOG.md)** — a shopper being shown a
Python exception in the chat box on every turn, which no other test caught because none of them went
through the browser.

Then open the storefront yourself and use the chat box. That is the only test that counts.

---

## Troubleshooting

| symptom | cause |
|:--|:--|
| `/health` 200, everything else 500 | the shop's `DB_PORT` ≠ the port MySQL listens on. `/health` does not touch the database |
| chat returns **404 `NO_STORE_CONNECTED`** | step 4 was not done. A tenant, a key and an agent are not enough |
| chat returns **403** | the agent is not in the tenant's `AGENTS` list. An entitlement, not a bug |
| the widget is refused from the merchant's own site | a public key with an empty `ORIGINS` permits nothing. Re-issue with `PUBLIC=1 ORIGINS=…` |
| the widget never appears in the page | `NEURA_WIDGET_ENABLED` is false, or `php artisan config:clear` was not run |
| editing the shop's `.env` changed nothing | Laravel cached it. `php artisan config:clear` |
| editing `widget.js` changed nothing | the API serves it — restart NEURA |
| the key is lost | there is no command to show it again. Only the hash is stored. Issue a new one, revoke the old |
| a shopper sees `Role map … role 'embedder'` | fixed 2026-09-19 ([Finding 49](TESTING_LOG.md)). If it reappears, retrieval is being built where it should degrade |

---

## What this page does not cover

- **Installing Bagisto itself** — PHP, Composer, MySQL, Herd, migrations, `NeuraDemoDataSeeder`.
- **Webhooks.** Optional. Without them the shop is polled instead, which works, but leaves order
  status as stale as the last sync. See the bridge's own `README.md`.
- **Going live.** [INTEGRATION_GUIDE.md §9](INTEGRATION_GUIDE.md) — it is a process, not a switch.
- **Any shop that is not this one.** The bridge is one implementation of a published specification;
  a different shop implements the same nine endpoints. That is the whole design
  ([INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md)), and **no part of NEURA knows what platform is on
  the other end**.
