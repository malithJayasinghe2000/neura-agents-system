.DEFAULT_GOAL := help
SHELL := /bin/bash

# uv installs to ~/.local/bin, which may not be on a non-interactive PATH.
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: help install dev up down logs api lint format typecheck arch test test-unit \
        test-integration test-widget widget-check widget-check-live widget-demo tenant-drop eval eval-fast eval-guard-off eval-one eval-agents eval-compare check migrate revision clean reset \
        spec conformance conformance-self-test sync-check sync-watch job-check job-drop rag-check rag-ask agent-check \
        care-check care-ask sell-ask chat-ask llm-check judge-check \
        tenant-new tenant-show tenant-usage key-new key-revoke webhook-drain \
        api-check verify-probe router-probe console console-check

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────────────────────────

install:  ## Install all workspace dependencies
	uv sync
	uv run pre-commit install

# ── Development ──────────────────────────────────────────────────────────────

up:  ## Start Postgres + Redis
	docker compose up -d
	@echo "waiting for healthy containers..."
	@until [ "$$(docker inspect -f '{{.State.Health.Status}}' neura-postgres 2>/dev/null)" = "healthy" ] \
	    && [ "$$(docker inspect -f '{{.State.Health.Status}}' neura-redis 2>/dev/null)" = "healthy" ]; do \
	    sleep 1; \
	done
	@echo "✔ datastores ready"

down:  ## Stop containers (data preserved)
	docker compose down

logs:  ## Tail container logs
	docker compose logs -f

api:  ## Run the API only (assumes datastores are up)
	uv run neura-api

dev: up api  ## Start datastores, then the API with reload

# The console needs the API on 8010, because `next.config.ts` rewrites /api/* to
# it — and NOT the 8000 in .env, where an unrelated application has been found
# listening before (open question E6). Two terminals, stated rather than implied:
# a single target that backgrounded both would hide whichever one failed.
console:  ## How to run the merchant console (prints the two commands)
	@echo ""
	@echo "  Two terminals:"
	@echo "    1)  NEURA_API_PORT=8010 uv run neura-api"
	@echo "    2)  cd apps/neura-console && npm run dev"
	@echo ""
	@echo "  Then http://localhost:3000 — and to get in:"
	@echo "    make tenant-new NAME=\"My Shop\" AGENTS=care        (prints tn_...)"
	@echo "    make user-new EMAIL=you@shop.com TENANT=tn_...     (once)"
	@echo "    make user-link EMAIL=you@shop.com                  (a sign-in URL)"
	@echo ""
	@echo "  To prove it works: make console-check EMAIL=you@shop.com"
	@echo ""

# ── Quality ──────────────────────────────────────────────────────────────────

lint:  ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format:  ## Apply formatting and safe fixes
	uv run ruff format .
	uv run ruff check --fix .

typecheck:  ## mypy strict on packages/, apps/, agents/, evals/
	uv run mypy packages apps agents evals

arch:  ## Architecture guardrails — layering + platform independence
	uv run lint-imports
	uv run python scripts/check_platform_independence.py
# Captured replay evidence is exempt from the platform-name scan (ADR-0035)
# because it is merchant data. This is what it is held to instead, and the two
# run together because they are one decision.
	uv run python scripts/check_graded_evidence.py

test-unit:  ## Unit tests (no external services)
	uv run pytest tests/unit -m "not integration"

test-integration:  ## Integration tests (requires: make up)
	uv run pytest tests/integration -m integration

test-widget:  ## The widget's pure logic (Node's built-in runner — no npm, no install)
	node --test "tests/widget/*.test.js"

# The console's half of the deterministic bar in docs/console.md §6. A browser
# and not curl, because __Host- and HttpOnly are enforced by the browser and by
# nothing else — a cookie Chrome refuses is a sign-in that silently does nothing.
#
# Covers all five screens, for the same class of reason: "show the evidence", "a
# withheld turn says so", "never a stored credential" and "no invented numbers"
# are all claims about what a rendered PAGE contains, and no assertion on a JSON
# body can make them. It seeds its own conversations, shadow turns, store and
# usage row — a check with nothing to look at proves nothing — and removes
# exactly the rows it created, by id.
console-check:  ## Drive ALL FIVE console screens in REAL headless Chrome: make console-check EMAIL=...
	uv run python scripts/console_check.py "$(EMAIL)"

widget-check:  ## Drive the REAL widget in REAL headless Chrome. No models, no cost.
	uv run python scripts/widget_check.py

# The same file against a running API and a real shop. Needs `make api` up.
#   make widget-check-live SHOP=http://bagisto.test/neura/v1 TOKEN=... [SHADOW=1]
# One turn, not an eval. SHADOW=1 provisions the tenant in shadow mode, which is
# the only way to see what a shopper is shown when the reply is withheld.
widget-check-live:
	uv run python scripts/widget_check.py --live --url $(or $(URL),http://localhost:8000) \
	  --shop-url $(SHOP) --shop-token $(TOKEN) $(if $(SHADOW),--shadow,)

# Set a tenant up and hand you a URL to open in your OWN browser. A headless
# pass proves the widget works; it does not show anybody what it looks like.
#   make widget-demo SHOP=http://bagisto.test/neura/v1 TOKEN=... [SHADOW=1]
#
# AGENTS is comma-separated. `AGENTS=care,sell` provisions a tenant running
# both, with a key holding both agents' scopes, and prints a URL that pins
# neither — so the server chooses per message ([ADR-0031]). Without it the
# tenant runs `care` alone and the URL pins it, which is what a single-agent
# embed does anyway.
widget-demo:  ## Provision a tenant + widget key and print a URL: make widget-demo SHOP=... TOKEN=... [AGENTS=care,sell]
	uv run python scripts/widget_check.py --live --setup-only \
	  --url $(or $(URL),http://localhost:8000) \
	  --shop-url $(SHOP) --shop-token $(TOKEN) $(if $(SHADOW),--shadow,) \
	  $(if $(AGENTS),--agent $(AGENTS),)

tenant-drop:  ## Remove a tenant made by `make widget-demo`: make tenant-drop TENANT=tn_...
	uv run python scripts/widget_check.py --drop $(TENANT)

test: test-unit test-widget  ## Alias for the fast test suite

spec:  ## Regenerate the published OpenAPI document from the canonical models
	uv run python scripts/generate_spec.py

conformance:  ## Check a store: make conformance URL=https://shop/neura/v1 TOKEN=xxx
	uv run neura-conformance --url $(URL) --token $(TOKEN)

conformance-self-test:  ## Verify the conformance tool itself against a built-in store
	uv run neura-conformance --self-test

sync-check:  ## Sync a REAL shop into PostgreSQL: make sync-check URL=... TOKEN=... [RESET=1]
	uv run python scripts/sync_smoke_test.py --url $(URL) --token $(TOKEN) \
	  $(if $(TENANT),--tenant-id $(TENANT),) $(if $(RESET),--reset,)

job-check:  ## Schedule a REAL sync for a tenant the worker was never told about: make job-check URL=... TOKEN=... [KEEP=1]
	uv run python scripts/job_check.py --url $(URL) --token $(TOKEN) $(if $(KEEP),--keep,)

job-drop:  ## Remove a tenant left by `make job-check KEEP=1`: make job-drop TENANT=tn_...
	uv run python scripts/job_check.py --drop $(TENANT)

sync-watch:  ## Sync, then edit the shop and re-run to see exactly what changed
	uv run python scripts/sync_watch.py --url $(URL) --token $(TOKEN)

rag-check:  ## Index a REAL shop with REAL embeddings: make rag-check URL=... TOKEN=... [KEEP=1] [TENANT=...]
	uv run python scripts/rag_smoke_test.py --url $(URL) --token $(TOKEN) \
	  $(if $(TENANT),--tenant-id $(TENANT),) $(if $(KEEP),--keep,)

rag-ask:  ## Search what is indexed: make rag-ask Q="do you sell my data?" [SHOW=1] [TENANT=...]
	uv run python scripts/rag_ask.py $(if $(SHOW),--show,) \
	  $(if $(TENANT),--tenant-id $(TENANT),) -- "$(Q)"

agent-check:  ## Run the agent runtime end to end against REAL models + Postgres
	uv run python scripts/agent_smoke_test.py

api-check:  ## Hold a conversation over HTTP and a socket, against a REAL shop
	uv run python scripts/api_smoke_test.py --url $(URL) --token $(TOKEN) \
	  $(if $(PLATFORM),--platform $(PLATFORM),)

# Open question A8. The strings live in the script, under version control, because
# the 2026-07-29 probe's inputs were never recorded and the 2026-08-02 re-run had to
# reconstruct them — which is why its negative result could not be interpreted.
verify-probe:  ## Can this model hold the GUARD role? Four arms, two controls. [AGENT=care|sell MODEL=… CLOUD=1 N=10]
	uv run python scripts/verify_probe.py -n $(or $(N),10) \
	  --agent $(or $(AGENT),care) \
	  $(if $(CLOUD),--role-map cloud-prod,) $(if $(MODEL),--model $(MODEL),)

# Open question A11. The cloud ROUTER is a reasoning model with no thinking
# budget, on the latency path of every turn — measured at ~7 minutes per call.
router-probe:  ## A11: can this model hold the ROUTER role? [MODEL=… ROLE_MAP=…]
	uv run python scripts/router_probe.py \
	  $(if $(ROLE_MAP),--role-map $(ROLE_MAP),) $(if $(MODEL),--model $(MODEL),)

care-check:  ## Hold real conversations with CARE against a REAL shop: make care-check URL=... TOKEN=...
	uv run python scripts/care_smoke_test.py --url $(URL) --token $(TOKEN)

# CUSTOMER, not AS. `AS` is a BUILT-IN make variable — the assembler, defaulting
# to `as` — so `$(if $(AS),...)` is always true and every run would silently
# authenticate as a customer called "as". It cost an afternoon: the anonymous
# security case appeared to fail because the shopper was never anonymous.
# Deliberately unlike `care-ask` and `sell-ask`, which drive one agent's graph
# in-process. This goes over HTTP to the running API with a **public widget
# key**, so it exercises what a browser exercises: the origin lock, the
# entitlement check, the scope check, and the dispatcher's choice ([ADR-0031]).
chat-ask:  ## Ask the dispatched endpoint, as a browser would: make chat-ask KEY=fn_pk_... Q="..."
	uv run python scripts/chat_ask.py --key $(KEY) \
	  $(if $(BASE),--base $(BASE),) $(if $(CONV),--conversation $(CONV),) \
	  $(if $(CUSTOMER),--as-customer $(CUSTOMER),) $(if $(ORIGIN),--origin $(ORIGIN),) -- "$(Q)"

# ── A graded turn becomes an eval case ───────────────────────────────────────
# [ADR-0032]. The loop the console promised and nothing implemented. `promote`
# writes a `graded.yaml` case with `synthetic: false`, which is the one flag
# that makes a run VALIDATION rather than a harness self-test.
#
# It is a command and not a console button because [ADR-0032] §9 puts the case
# in the repository, so that changing an assertion takes a diff and a name — and
# a console served from a host with no working tree cannot do that.
#
#   make promote-list TENANT=tn_...
#   make promote TENANT=tn_... TURN=msg_... FACTS="30 days|full refund"
#
# FACTS are pipe-separated spans of the APPROVED DRAFT. Each is checked against
# the draft verbatim and refused if absent (§11) — a fact typed from memory is
# an expectation nobody verified.
promote-list:  ## Graded turns and whether each is promotable: make promote-list TENANT=tn_...
	uv run python scripts/promote_turn.py --tenant $(TENANT)

promote:  ## Promote one graded turn: make promote TENANT=tn_... TURN=msg_... FACTS="a|b"
	uv run python scripts/promote_turn.py --tenant $(TENANT) --turn $(TURN) \
	  $(if $(FACTS),--facts "$(FACTS)",) $(if $(DRY),--dry-run,)

care-ask:  ## Ask CARE one question and watch every step: make care-ask Q="..." URL=... TOKEN=... [CUSTOMER=385]
	uv run python scripts/care_ask.py --url $(URL) --token $(TOKEN) \
	  $(if $(CUSTOMER),--as-customer $(CUSTOMER),) $(if $(ORIGIN),--origin $(ORIGIN),) -- "$(Q)"

# SELL's half of `care-ask`, and the reason it exists is specific: until it was
# written, every measurement of SELL ran against four invented fixture products.
# A recommender graded only on fixtures is graded on somebody's imagination.
sell-ask:  ## Ask SELL one question and watch every step: make sell-ask Q="..." URL=... TOKEN=...
	uv run python scripts/sell_ask.py --url $(URL) --token $(TOKEN) \
	  $(if $(CUSTOMER),--as-customer $(CUSTOMER),) $(if $(ORIGIN),--origin $(ORIGIN),) -- "$(Q)"

llm-check:  ## Verify the LLM layer against REAL models (needs Ollama running)
	uv run python scripts/llm_smoke_test.py

judge-check:  ## Verify the eval judge is reachable AND catches a hallucination
	uv run neura-eval --check-judge

# Two agents are installed, so the harness refuses to guess which one — and it
# is right to. AGENT=… picks one; the default is CARE, which is the agent the
# gates in AGENTS.md were measured against.
AGENT ?= care

# The metric(s) this run must PRODUCE and must meet the gate for — [ADR-0036].
#
# `injection_resistance` and nothing else, and the shortness of the list is the
# decision rather than an oversight. AGENTS.md already calls it *"a release
# blocker, not a target"*; every other gate stays REPORTED, because
# `tool_selection_accuracy` and `escalation_precision` fail today for documented
# reasons (A7/A14, and guard-off fails precision BY DESIGN), and a command that
# is permanently red is a command whose red stops meaning anything — the same rot
# as one that is falsely green.
#
# The dispatch suite requires a different metric, since it cannot produce this
# one:  make eval AGENT=dispatch REQUIRE=expensive_misroute_rate
REQUIRE ?= injection_resistance
_require = $(foreach metric,$(REQUIRE),--require $(metric))

# `--out` is not optional here, and that is the point of open question E7. A
# suite run costs twenty minutes of local inference and used to leave nothing
# behind but terminal scrollback — so the second look at a failure cost another
# twenty minutes, twice, on 2026-08-02 and 2026-08-26.
#
# `--fail-on-unmeasured` exits 3 when any case never reached a result. Added
# 2026-09-06: this command exited 0 having measured nothing at all (E9).
eval:  ## Run an agent against its golden datasets: make eval [AGENT=sell OUT=path.json]
	uv run neura-eval --agent $(AGENT) $(_require) --fail-on-unmeasured --out $(if $(OUT),$(OUT),)

# Every installed agent, not just one. Datasets parsing is a property of the
# repository rather than of whichever agent happens to be the default, and a
# `make check` that validated only CARE's cases would go green on a SELL YAML
# nobody could load.
eval-fast:  ## Every agent's datasets + the harness — no agent run, no models, no cost. In `make check`.
	@for agent in $$(uv run python -c "from importlib.metadata import entry_points; print(' '.join(sorted(e.name for e in entry_points(group='neura.eval_targets'))))"); do \
		echo "── $$agent ──"; \
		uv run neura-eval --agent $$agent --no-judge --no-agent || exit 1; \
	done

# The run that keeps "injection resistance 1.00" meaning what it means.
#
# The guard node ends a turn early, which makes `unauthorised_tool_calls`
# trivially zero — so a guard that blocks would MANUFACTURE the project's one
# release-blocking gate. This run switches every rule off and measures the
# structural defence on its own: no WRITE tool to invoke, every call authorised
# in code, an unowned order reference escalating.
#
# **Injection resistance must be 1.00 here.** If it is not, the thing that broke
# is the policy engine, and no rule in the guard is the fix (ADR-0011).
#
# That sentence was enforced by a human reading a table until 2026-09-06, when
# this command printed "47 of 47 cases could not reach the model provider",
# omitted injection resistance from the metrics table entirely, and exited 0
# (E9, Finding 27). `--require` now fails the run when the number is ABSENT, not
# only when it is low — a gate cannot be met by a number that does not exist.
eval-guard-off:  ## The suite with the guard disabled — proves the defence is structural
	NEURA_GUARD_ENABLED=false uv run neura-eval --agent $(AGENT) --no-judge \
		$(_require) --fail-on-unmeasured --out

# No `--require`: which metrics a single dataset can produce depends on which
# dataset it is, and `product_qa.yaml` has no adversarial case in it. Requiring
# injection resistance here would fail a legitimate run for asking the wrong
# question of it. `--fail-on-unmeasured` still applies — a dataset run that
# reached no model is no more a result than a whole suite that did not.
eval-one:  ## One dataset against the real agent: make eval-one D=injection [AGENT=sell OUT=path.json]
	uv run neura-eval --agent $(AGENT) --dataset $(D) --fail-on-unmeasured --out $(if $(OUT),$(OUT),)

eval-agents:  ## Which installed agents can be evaluated
	uv run neura-eval --list-agents

eval-compare:  ## Same suite on two role maps: make eval-compare A=ollama-dev B=cloud-prod
	uv run neura-eval --agent $(AGENT) --role-map $(A)
	uv run neura-eval --agent $(AGENT) --role-map $(B)

check: lint typecheck arch test eval-fast  ## Everything CI runs. Run before every push.

# ── Database ─────────────────────────────────────────────────────────────────

migrate:  ## Apply migrations
	uv run alembic upgrade head

# ── Tenancy (1.13) ───────────────────────────────────────────────────────────
#
# The operator tool until the merchant console exists. Everything here runs as
# the ordinary application role, so it is subject to the same Row-Level Security
# a request is — creating a tenant works only because the insert is scoped to
# the id being created.

# The merchant console's accounts (ADR-0026). There is no sign-up page on
# purpose — an open form on the sign-in screen would let anyone create an
# account for any address. These are also why no login credential is seeded in a
# migration, where it would live in version control.
user-new:  ## Console account: make user-new EMAIL=owner@shop.com NAME="Jane" [TENANT=tn_...]
	uv run python scripts/console_admin.py create --email "$(EMAIL)" \
	  --name "$(NAME)" --tenant "$(TENANT)"

user-show:  ## An account and the merchants it may act for: make user-show EMAIL=...
	uv run python scripts/console_admin.py show --email "$(EMAIL)"

user-revoke:  ## Withdraw access: make user-revoke EMAIL=... TENANT=tn_...
	uv run python scripts/console_admin.py revoke --email "$(EMAIL)" --tenant "$(TENANT)"

# Prints a working sign-in link. Use it when mail is not arriving and you need to
# know whether the fault is delivery or the login flow.
user-link:  ## Print a sign-in link instead of mailing it: make user-link EMAIL=...
	uv run python scripts/console_admin.py link --email "$(EMAIL)"

tenant-new:  ## Create a tenant: make tenant-new NAME="Acme Store" AGENTS=care
	uv run python scripts/tenant_admin.py create-tenant --name "$(NAME)" --agents "$(AGENTS)"

tenant-show:  ## Tenant, keys and usage: make tenant-show TENANT=tn_...
	uv run python scripts/tenant_admin.py show --tenant-id $(TENANT)

tenant-usage:  ## Today's metered usage: make tenant-usage TENANT=tn_...
	uv run python scripts/tenant_admin.py usage --tenant-id $(TENANT)

# The repair for open question P7: the drainer finds work through a Redis index,
# because no transaction can query deliveries across tenants under RLS. If that
# index is lost, the rows are safe and the schedule is not — this unsticks them.
webhook-drain:  ## Send queued webhooks now: make webhook-drain TENANT=tn_...
	uv run python scripts/tenant_admin.py drain-webhooks --tenant-id $(TENANT)

# Printed once. Only the hash is stored, so there is no command to show it again.
key-new:  ## Issue a key: make key-new TENANT=tn_... SCOPES=care:chat:write [NAME=server]
	uv run python scripts/tenant_admin.py issue-key --tenant-id $(TENANT) \
	  --scopes "$(SCOPES)" --name "$(NAME)" \
	  $(if $(PUBLIC),--public --origins "$(ORIGINS)",) \
	  $(if $(EXPIRES),--expires-days $(EXPIRES),)

key-revoke:  ## Revoke a key: make key-revoke TENANT=tn_... KEY=key_...
	uv run python scripts/tenant_admin.py revoke-key --tenant-id $(TENANT) --key-id $(KEY)

revision:  ## New migration: make revision M="add tenants"
	uv run alembic revision --autogenerate -m "$(M)"

# ── Housekeeping ─────────────────────────────────────────────────────────────

clean:  ## Remove caches and build artefacts
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache \
	  -o -name .ruff_cache -o -name '*.egg-info' \) -prune -exec rm -rf {} + 2>/dev/null || true

reset:  ## DESTRUCTIVE — drop all local data volumes and re-create
	docker compose down -v
	$(MAKE) up
