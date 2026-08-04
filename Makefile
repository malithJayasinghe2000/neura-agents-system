.DEFAULT_GOAL := help
SHELL := /bin/bash

# uv installs to ~/.local/bin, which may not be on a non-interactive PATH.
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: help install dev up down logs api lint format typecheck arch test test-unit \
        test-integration eval eval-fast eval-guard-off eval-one eval-agents eval-compare check migrate revision clean reset \
        spec conformance conformance-self-test sync-check sync-watch rag-check rag-ask agent-check \
        care-check care-ask llm-check judge-check \
        tenant-new tenant-show tenant-usage key-new key-revoke webhook-drain \
        api-check verify-probe

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

test-unit:  ## Unit tests (no external services)
	uv run pytest tests/unit -m "not integration"

test-integration:  ## Integration tests (requires: make up)
	uv run pytest tests/integration -m integration

test: test-unit  ## Alias for the fast test suite

spec:  ## Regenerate the published OpenAPI document from the canonical models
	uv run python scripts/generate_spec.py

conformance:  ## Check a store: make conformance URL=https://shop/neura/v1 TOKEN=xxx
	uv run neura-conformance --url $(URL) --token $(TOKEN)

conformance-self-test:  ## Verify the conformance tool itself against a built-in store
	uv run neura-conformance --self-test

sync-check:  ## Run the sync engine against a REAL shop: make sync-check URL=... TOKEN=...
	uv run python scripts/sync_smoke_test.py --url $(URL) --token $(TOKEN)

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
verify-probe:  ## A8: is `verify` stable under a meaning-free change? [MODEL=… CLOUD=1 N=10]
	uv run python scripts/verify_probe.py -n $(or $(N),10) \
	  $(if $(CLOUD),--role-map cloud-prod,) $(if $(MODEL),--model $(MODEL),)

care-check:  ## Hold real conversations with CARE against a REAL shop: make care-check URL=... TOKEN=...
	uv run python scripts/care_smoke_test.py --url $(URL) --token $(TOKEN)

# CUSTOMER, not AS. `AS` is a BUILT-IN make variable — the assembler, defaulting
# to `as` — so `$(if $(AS),...)` is always true and every run would silently
# authenticate as a customer called "as". It cost an afternoon: the anonymous
# security case appeared to fail because the shopper was never anonymous.
care-ask:  ## Ask CARE one question and watch every step: make care-ask Q="..." URL=... TOKEN=... [CUSTOMER=385]
	uv run python scripts/care_ask.py --url $(URL) --token $(TOKEN) \
	  $(if $(CUSTOMER),--as-customer $(CUSTOMER),) -- "$(Q)"

llm-check:  ## Verify the LLM layer against REAL models (needs Ollama running)
	uv run python scripts/llm_smoke_test.py

judge-check:  ## Verify the eval judge is reachable AND catches a hallucination
	uv run neura-eval --check-judge

eval:  ## Run the agent against its golden datasets (needs Ollama; EVAL_JUDGE_* for trustworthy scores)
	uv run neura-eval

eval-fast:  ## Datasets + harness only — no agent, no judge, no models, no cost. Part of `make check`.
	uv run neura-eval --no-judge --no-agent

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
eval-guard-off:  ## The suite with the guard disabled — proves the defence is structural
	NEURA_GUARD_ENABLED=false uv run neura-eval --no-judge

eval-one:  ## One dataset against the real agent: make eval-one D=injection
	uv run neura-eval --dataset $(D)

eval-agents:  ## Which installed agents can be evaluated
	uv run neura-eval --list-agents

eval-compare:  ## Same suite on two role maps: make eval-compare A=ollama-dev B=cloud-prod
	uv run neura-eval --role-map $(A)
	uv run neura-eval --role-map $(B)

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
