.DEFAULT_GOAL := help
SHELL := /bin/bash

# uv installs to ~/.local/bin, which may not be on a non-interactive PATH.
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: help install dev up down logs api lint format typecheck arch test test-unit \
        test-integration eval check migrate revision clean reset

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

typecheck:  ## mypy strict on packages/, agents/, apps/
	uv run mypy packages apps agents

arch:  ## Architecture guardrails — layering + platform independence
	uv run lint-imports
	uv run python scripts/check_platform_independence.py

test-unit:  ## Unit tests (no external services)
	uv run pytest tests/unit -m "not integration"

test-integration:  ## Integration tests (requires: make up)
	uv run pytest tests/integration -m integration

test: test-unit  ## Alias for the fast test suite

eval:  ## Agent evaluation suite
	@echo "Not implemented — Phase 1 milestone 1.4. See docs/architecture/evaluation-strategy.md"
	@exit 1

check: lint typecheck arch test  ## Everything CI runs. Run before every push.

# ── Database ─────────────────────────────────────────────────────────────────

migrate:  ## Apply migrations
	uv run alembic upgrade head

revision:  ## New migration: make revision M="add tenants"
	uv run alembic revision --autogenerate -m "$(M)"

# ── Housekeeping ─────────────────────────────────────────────────────────────

clean:  ## Remove caches and build artefacts
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache \
	  -o -name .ruff_cache -o -name '*.egg-info' \) -prune -exec rm -rf {} + 2>/dev/null || true

reset:  ## DESTRUCTIVE — drop all local data volumes and re-create
	docker compose down -v
	$(MAKE) up
