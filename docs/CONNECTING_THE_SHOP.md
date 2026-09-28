# Connecting A Shop To NEURA

How a shop and NEURA are joined up, in the order it has to be done, and how to tell at each step
that it worked.

**For:** whoever connects a shop today — FiveNeurals (every account command below is ours) and the
shop's developer (the bridge, the chat box line, the shop's settings). The **shop owner** has their
own version of this page inside the console: **Help → Connecting your shop**. It has the same steps
in plain words, and each step's *"How you'll know"* is a tick on the console's **Shop connection**
checklist. Keep the two in step.

**This is not a shop installation guide.** It assumes the shop already runs and a NEURA bridge — an
implementation of the [published specification](spec/generic-commerce-interface-v1.md) — is installed
in it. Building one is [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md).

> **Rewritten 2026-09-28**, with the console's *Shop connection* redesign. The 2026-09-19 version
> predated the console: it had no owner account, no data agreement, no product views, no suggestions
> scope, and it pointed the chat box at port 8000, where another project listens on the development
> machine. **Not yet done:** a run-through by a second person on a second machine. Anywhere this page
> is wrong or incomplete is worth telling the author about.

---

## 1. Who does what

| who | does | today |
|:--|:--|:--|
| **The shop's developer** | installs the bridge, puts the chat box line on the shop's pages, switches product views on (optional) | in the shop |
| **FiveNeurals** | creates the account, connects the shop, copies the catalogue the first time, issues the keys, records a data agreement (optional) | `make` commands, below. **None of this is in the console yet**, and moving it there is not decided — see [console.md §3.4](console.md) (*stage 2*) |
| **The shop owner** | follows the checklist on *Shop connection*, presses **Sync now** after adding products or changing stock, grades replies in *Review* while practice mode is on, decides when to go live | the console |

---

## 2. The keys, and which way each one points

Confusing them is the commonest way to get stuck.

```
      ┌─────────────────┐                             ┌──────────────────┐
      │   The shop      │  ◀── NEURA reads products,  │      NEURA       │
      │   + its bridge  │      stock, orders, pages   │                  │
      │                 │      (shop token)           │                  │
      │                 │                             │                  │
      │  shop's server ─┼── product views (optional) ▶│                  │
      │                 │      (secret observe key)   │                  │
      │  shop's pages ──┼── the chat box ────────────▶│                  │
      │                 │      (public chat box key)  │                  │
      └─────────────────┘                             └──────────────────┘
```

| key | who checks it | where it lives | what it is for | secret? |
|:--|:--|:--|:--|:--|
| **shop token** | the **shop** | the shop's server | NEURA proves it may read the catalogue, orders and policy pages | **yes** — never in a browser, never shown by the console |
| **chat box key** `fn_pk_…` | **NEURA** | the shop's page source | a shopper's browser proves the chat box may ask questions | **no** — public by design, locked to the shop's address |
| **observe key** `fn_sk_…` with `observe:write` | **NEURA** | the shop's server | the shop sends product views (optional, for *Sold out*) | **yes** — a public key is refused even if it held the scope |

A key is printed **once**. Only its hash is stored, so a lost key is replaced (issue a new one, revoke
the old), never recovered.

---

## 3. The steps

Six steps, in order. Each ends with **How you'll know** — the tick on *Shop connection*.

Throughout: `$SHOP_URL` is where the bridge is mounted (for example `https://shop.example/neura/v1`),
`$SHOP_TOKEN` is the shop token, `tn_…` is the tenant id step 2 prints, and **NEURA's own address**
is where the API runs — **`http://localhost:8010` on the development machine**, never 8000.

### Step 1 — The bridge speaks the specification · *the shop's developer*

Do this first. If it fails nothing later can work, and the error you would get instead is harder to
read.

```bash
curl "$SHOP_URL/health"                                  # no token needed
make conformance URL="$SHOP_URL" TOKEN="$SHOP_TOKEN"     # names anything wrong
```

> **`/health` answers while everything else fails?** `/health` never touches the shop's database, so
> it stays green when the shop's database settings are wrong. Fix those, then clear the shop's cached
> settings. This cost a day on 2026-09-13.

**How you'll know:** conformance is clean. Later, in the console, *Your shop answers* ticks when the
owner presses **Check now** — a live question to the shop, asked only on that click.

### Step 2 — The account and the connection · *FiveNeurals*

```bash
make tenant-new NAME="Shop Name" AGENTS=care,sell        # prints tn_…
make user-new EMAIL=owner@shop.example NAME="Owner" TENANT=tn_…
make sync-check URL="$SHOP_URL" TOKEN="$SHOP_TOKEN" TENANT=tn_…
```

- `AGENTS` is an entitlement, not a hint: an assistant left out returns **403**, which reads like a
  bug and is not one. `care` is NEURA-CARE, `sell` is NEURA-SELL.
- **A new shop starts live, not in practice mode.** Practice mode is the tenant's
  `config.mode = shadow`; there is no `make` command for it yet (`TenantRepository.set_config`).
  `make tenant-show TENANT=tn_…` prints what is set.
- `make sync-check` stores the shop's address and token (encrypted) **and** copies the catalogue the
  first time. Without the stored connection every chat returns **404 `NO_STORE_CONNECTED`**.
- The owner signs in with a one-time link. Until an email provider is configured nothing is mailed:
  `make user-link EMAIL=owner@shop.example` prints the link to hand over.

**How you'll know:** *Your shop is connected* and *Your catalogue is copied* are ticked, with the time
it was read.

### Step 3 — Keeping the copy fresh · *the owner*

**Nothing syncs by itself yet** — a recurring sync is ADR-0022's deliberately undecided *cron-shaped
table*. After adding products or changing stock, the owner presses **Sync now** on *Shop connection*.
It queues a **full** read of the shop into our copy and **changes nothing in the shop**; pressing it
again while one is running is the same sync. (Full, because a shop's *changed since* filter follows a
product's own edits, and a sale that lowers stock is not one.)

Search by meaning is separate from the copy and **is not rebuilt by Sync now**: rebuilding it runs the
embedding model. `make rag-check URL="$SHOP_URL" TOKEN="$SHOP_TOKEN" TENANT=tn_… KEEP=1` indexes the
shop (`KEEP=1` matters — without it the script removes what it just indexed). Skip it and the
assistants still work; they read the shop live, and lose search by meaning.

**How you'll know:** the time on *Our copy of your catalogue* moves; the page says how many products
search by meaning covers (*"29 of 38"*).

### Step 4 — The chat box · *FiveNeurals issues the key, the developer adds the line*

```bash
make key-new TENANT=tn_… NAME=widget PUBLIC=1 ORIGINS=https://shop.example \
  SCOPES="care:chat:write,care:conversations:read,care:order:read,care:catalogue:read,care:policies:read,care:escalate,sell:chat:write,sell:conversations:read,sell:catalogue:read,sell:escalate,sell:suggest:read"
```

- **`ORIGINS` is not optional.** A public key with no allowed address permits nothing, and the
  symptom is the shop's own pages being refused. It is exactly the address a shopper's browser shows —
  scheme and host, no trailing slash, and `www.` is a different address.
- `sell:suggest:read` is what the paired suggestions on a basket page need (ADR-0040). Leave the
  `sell:` scopes out for a shop without NEURA-SELL.

The line itself is the one the API serves — `GET <NEURA's address>/v1/widget/snippet`, also shown on
the console's Help page:

```html
<!-- NEURA chat -->
<script src="<NEURA's address>/v1/widget/widget.js" async
        data-neura-key="fn_pk_…"></script>
```

The address in that line comes from the API's **`PUBLIC_BASE_URL`** setting. It defaults to
`http://localhost:8000`, which is wrong on the development machine: set `PUBLIC_BASE_URL` to the
address shoppers' browsers reach NEURA at (`http://localhost:8010` there).

**The reference bridge** takes the same three things as settings rather than a pasted line, and
mounts the chat box into the shop's layout itself, so no theme file is edited:

```dotenv
NEURA_WIDGET_ENABLED=true
NEURA_WIDGET_HOST=http://localhost:8010     # NEURA's address — not the shop's
NEURA_WIDGET_KEY=fn_pk_…
```

Then clear the shop's cached settings. A shop that caches its configuration shows no change until
then, which looks exactly like a value that did not work.

**How you'll know:** *The chat box is on your shop* ticks once a shopper — or you — uses it:
*"Used today from shop.example"*. The console shows when the key was last used and the address it
works from; never the key.

### Step 5 — Practice mode · *the owner*

While the tenant is in practice mode, every question is answered in the background and **no shopper
sees the reply** — they see an honest *"no automated answer"* message instead
([ADR-0020](architecture/adr/0020-a-withheld-turn-says-so.md)). The owner grades the held replies in
**Review**, then decides when to go live. Going live is a process, not a switch
([INTEGRATION_GUIDE.md §9](INTEGRATION_GUIDE.md)).

**How you'll know:** replies appear in Review.

### Step 6 — Optional: Sold out · *FiveNeurals, then the developer*

*Sold out* lists products shoppers opened while they could not be bought. It needs the shop's server
to send product views, and that needs a data-processing agreement first
([ADR-0042](architecture/adr/0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) §2,
[ADR-0044](architecture/adr/0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md)).

```bash
make tenant-dpa TENANT=tn_…                                         # the agreement, as a row
make key-new TENANT=tn_… NAME=observe SCOPES=observe:write          # a SECRET key; refused without the agreement
```

In the reference bridge, product views are **off by default** and off means nothing is sent:

```dotenv
NEURA_OBSERVE_ENABLED=true
NEURA_OBSERVE_URL=http://localhost:8010/v1/observe/events
NEURA_OBSERVE_KEY=fn_sk_…
```

Views go out on the shop's queue, so a queue worker must be running there.

**How you'll know:** *Data agreement on record* and *Your shop is sending product views* tick — the
second when any product view arrived in the last seven days. A yes or no, never a count. *Sold out*'s
own *Is it working?* shows the same two.

---

## 4. Check it end to end

```bash
make widget-check-live URL=http://localhost:8010 SHOP="$SHOP_URL" TOKEN="$SHOP_TOKEN"
```

It provisions its own throwaway tenant, asks one question in real headless Chrome, and removes what it
made. It is the check that found [Finding 49](TESTING_LOG.md) — a shopper shown a Python exception in
the chat box on every turn, which no other test caught because none went through a browser.

Then open *Shop connection* as the owner: every step ticked, **Check now** answering. And open the
shop and use the chat box yourself. That is the only test that counts.

---

## Troubleshooting

| what you see | why |
|:--|:--|
| *Your shop answers* fails | the shop is down, or the bridge is not at the address FiveNeurals stored. Check the address opens in a browser |
| `/health` answers, everything else fails | the shop's database settings are wrong; `/health` does not touch the database |
| chat returns **404 `NO_STORE_CONNECTED`** | step 2's connection was not stored. A tenant, a key and an assistant are not enough |
| chat returns **403** | the assistant is not in the tenant's `AGENTS`. An entitlement, not a bug |
| the chat box appears but is refused | the key is used from an address it was not made for (`www.` versus none, `http` versus `https`). Issue a new one with the right `ORIGINS` |
| the chat box never appears | the line is not on the page, or the shop is still using cached settings |
| the chat box loads from the wrong place | `PUBLIC_BASE_URL` (the pasted line) or `NEURA_WIDGET_HOST` (the reference bridge) points at the wrong address |
| a new product or a stock change is missing in the console | our copy is older than the change. **Sync now** on *Shop connection* |
| *Sold out* stays empty | no agreement recorded, or product views are off in the shop, or no queue worker is running there. *Is it working?* says which of the first two |
| editing `widget.js` changed nothing | the API serves it — restart NEURA |
| a key is lost | there is no command to show it again. Issue a new one, revoke the old |

---

## What this page does not cover

- **Installing a shop platform**, or building a bridge — [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md).
- **Change messages (webhooks).** A bridge can send them, and **NEURA does not listen to them yet**:
  nothing on our side verifies or acts on one. Until it does, the copy is as fresh as the last sync.
- **Doing any of FiveNeurals' steps from the console** — a connect form, keys made in the console,
  creating a shop and inviting its owner, recording the agreement there. Not decided
  ([console.md §3.4](console.md), stage 2).
- **Any particular platform.** No part of NEURA knows what platform is on the other end; a shop
  implements the same published endpoints. That is the whole design.
