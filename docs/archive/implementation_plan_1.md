# FiveNeurals AI Agents Platform — Initial Implementation Plan

## 📋 Executive Summary

This plan transforms your blueprint into a production-ready, **integration-first** AI agent platform. The key shift from your original blueprint: we're designing **from the outside in** — starting with how developers will integrate your agents into their e-commerce systems, and then building the internals to serve that experience.

> [!IMPORTANT]
> This is a **Phase 0 + Phase 1** plan. It covers the foundational decisions and the first buildable milestone. We will create follow-up plans for each subsequent phase as we progress — one step at a time.

---

## 🔍 Analysis of Your Blueprint — What's Good & What Needs Upgrading

### ✅ Strengths of Your Blueprint
| Area | Assessment |
|:-----|:-----------|
| **Agent concepts** | All 5 agents are well-defined with clear value propositions |
| **Ecosystem vision** | Cross-agent intelligence (the "Avengers" model) is a genuine differentiator |
| **Integration methods** | REST API + SDK + Widget — correct 3-tier approach |
| **Phased roadmap** | Starting with 1 agent (NEURA-CARE) is the right call |
| **Tech stack** | FastAPI + LangGraph + PostgreSQL — solid choices |

### ⚠️ Areas That Need Industry-Standard Upgrades

| Area | Blueprint Says | Industry Best Practice (2026) | Impact |
|:-----|:---------------|:------------------------------|:-------|
| **Integration protocols** | REST API + WebSocket only | Add **MCP (Model Context Protocol)** + **A2A Protocol** support | Your agents can plug into the emerging AI ecosystem — other AI agents can call YOUR agents |
| **API design** | Basic REST endpoints | **OpenAPI 3.1 spec** + idempotency keys + machine-readable schemas + `llms.txt` | Makes integration bulletproof for both human developers AND AI agents |
| **Agent communication** | "Event bus + shared memory" (vague) | **Orchestrator-Worker pattern** via LangGraph with persistent checkpointing | Deterministic, debuggable, recoverable agent workflows |
| **SDK approach** | Hand-code JS + Python SDKs | **Auto-generate SDKs** from OpenAPI spec using tools like Fern or Speakeasy | Keeps SDKs always in sync with API, zero drift |
| **Multi-tenancy** | Not mentioned | **Tenant isolation from Day 1** — each client's data, config, and agent state fully separated | Critical for SaaS — you can't bolt this on later |
| **Observability** | "LangSmith + Sentry" | LangSmith + **OpenTelemetry** + structured logging with trace IDs | Full traceability from API call → agent decision → LLM call → response |
| **Project structure** | Not defined | **Python monorepo** with `uv` workspaces, shared packages, per-agent services | Scales cleanly as you add agents |
| **Security model** | NEURA-GUARD as an agent | Also need **infrastructure-level security**: API key scoping, rate limiting, RBAC, zero-trust inter-agent auth | The agent handles business-logic security; infrastructure security is separate |
| **Testing strategy** | Not mentioned | **Agent evaluation framework** — unit tests, integration tests, AND agent-specific evaluations (non-deterministic output testing) | AI agents need different testing strategies than traditional software |
| **CI/CD** | Not mentioned | Automated pipeline: lint → test → evaluate agents → deploy | Professional-grade development workflow |

---

## 🏗️ Phase 0: Project Foundation (Before Writing Any Agent Code)

> [!TIP]
> This is the most important phase. Getting the foundation right means everything else is easier. Rushing past this is the #1 reason AI agent projects fail.

### 0.1 — Project Structure (Monorepo with `uv` Workspaces)

```
neura-agents/
├── pyproject.toml                    # Root workspace config (uv)
├── uv.lock                           # Locked dependencies
├── .env.example                       # Environment variable template
├── .gitignore
├── AGENTS.md                          # Operating manual for developers
├── README.md
├── docker-compose.yml                 # Local dev environment
├── Makefile                           # Common commands (make dev, make test, etc.)
│
├── packages/                          # 📦 Shared internal libraries
│   ├── neura-common/                  # Shared utilities, logging, config
│   │   ├── pyproject.toml
│   │   └── src/neura_common/
│   │       ├── __init__.py
│   │       ├── config.py              # Environment & config management
│   │       ├── logging.py             # Structured logging with trace IDs
│   │       ├── auth.py                # API key validation, tenant resolution
│   │       ├── exceptions.py          # Standardized error types
│   │       └── telemetry.py           # OpenTelemetry setup
│   │
│   ├── neura-schemas/                 # Shared Pydantic models & contracts
│   │   ├── pyproject.toml
│   │   └── src/neura_schemas/
│   │       ├── __init__.py
│   │       ├── api/                   # API request/response models
│   │       │   ├── common.py          # Pagination, error responses
│   │       │   └── care.py            # NEURA-CARE specific schemas
│   │       ├── events/                # Inter-agent event schemas
│   │       │   └── base.py
│   │       └── domain/                # Core domain models
│   │           ├── tenant.py
│   │           ├── customer.py
│   │           └── conversation.py
│   │
│   └── neura-agent-core/             # Base agent framework
│       ├── pyproject.toml
│       └── src/neura_agent_core/
│           ├── __init__.py
│           ├── base_agent.py          # Abstract base for all agents
│           ├── memory.py              # Short-term + long-term memory interfaces
│           ├── tools.py               # Tool registration & execution
│           └── orchestrator.py        # LangGraph orchestration helpers
│
├── services/                          # 🚀 Deployable services
│   ├── api-gateway/                   # Main API entry point
│   │   ├── pyproject.toml
│   │   └── src/api_gateway/
│   │       ├── __init__.py
│   │       ├── main.py                # FastAPI app factory
│   │       ├── middleware/
│   │       │   ├── auth.py            # API key auth middleware
│   │       │   ├── rate_limit.py      # Rate limiting
│   │       │   ├── tenant.py          # Multi-tenant context
│   │       │   └── cors.py            # CORS configuration
│   │       ├── routes/
│   │       │   ├── v1/                # API version 1
│   │       │   │   ├── care.py        # /v1/care/* endpoints
│   │       │   │   ├── health.py      # Health check
│   │       │   │   └── webhooks.py    # Webhook management
│   │       │   └── openapi.py         # Custom OpenAPI schema
│   │       └── websocket/
│   │           └── chat.py            # WebSocket for real-time chat
│   │
│   ├── agent-care/                    # NEURA-CARE agent service
│   │   ├── pyproject.toml
│   │   └── src/agent_care/
│   │       ├── __init__.py
│   │       ├── agent.py               # Main agent definition (LangGraph)
│   │       ├── nodes/                 # LangGraph nodes
│   │       │   ├── router.py          # Intent classification
│   │       │   ├── responder.py       # Response generation
│   │       │   ├── escalation.py      # Human handoff logic
│   │       │   └── sentiment.py       # Emotion detection
│   │       ├── tools/                 # Agent tools
│   │       │   ├── knowledge_base.py  # RAG search
│   │       │   └── ticket_system.py   # Create/update tickets
│   │       ├── prompts/               # System prompts (version-controlled)
│   │       │   └── care_system.py
│   │       └── evaluations/           # Agent-specific test cases
│   │           └── test_scenarios.py
│   │
│   └── widget-server/                 # Embeddable widget CDN
│       ├── package.json
│       └── src/
│           ├── widget.js              # Embeddable chat widget
│           └── widget.css
│
├── sdks/                              # 📚 Client SDKs (auto-generated + manual)
│   ├── python/
│   │   └── fiveneurals/
│   └── javascript/
│       └── @fiveneurals/sdk/
│
├── infra/                             # 🔧 Infrastructure as Code
│   ├── docker/
│   │   ├── Dockerfile.api
│   │   └── Dockerfile.agent
│   └── deploy/
│       └── railway.toml
│
└── tests/                             # 🧪 Integration & E2E tests
    ├── integration/
    ├── e2e/
    └── fixtures/
```

### 0.2 — Core Technology Decisions

| Decision | Choice | Rationale |
|:---------|:-------|:----------|
| **Language** | Python 3.12+ | AI/ML ecosystem, FastAPI, LangGraph all Python-native |
| **Package manager** | `uv` | 10-100x faster than pip/poetry, native workspace support |
| **API framework** | FastAPI | Async-first, auto-generates OpenAPI spec, Pydantic integration |
| **Agent framework** | LangGraph | Production-grade stateful agent orchestration with checkpointing |
| **LLM providers** | OpenAI + Anthropic (multi-provider) | Avoid vendor lock-in; use best model for each task |
| **Database** | PostgreSQL (via Supabase) | Structured data, tenant isolation, you already have it |
| **Vector DB** | Qdrant (self-hosted via Docker) | Open-source, fast, great Python SDK |
| **Cache/Queue** | Redis | Session state, rate limiting, inter-service messaging |
| **Containerization** | Docker + Docker Compose | Consistent dev environments, easy deployment |
| **Deployment (initial)** | Railway | Simple, affordable, scales when needed |
| **Observability** | OpenTelemetry + LangSmith | Full-stack traces from HTTP → agent → LLM |
| **CI/CD** | GitHub Actions | Industry standard, free for public repos |

### 0.3 — API Design Principles (Integration-First)

Since your **primary goal is easy integration with existing e-commerce systems**, the API must be:

#### Developer Experience (DX) Priorities:
1. **5-Minute Integration** — A developer should go from signup to first API call in under 5 minutes
2. **Self-Documenting** — OpenAPI 3.1 spec auto-generated from code, interactive docs at `/docs`
3. **Predictable** — Consistent error shapes, pagination, rate limit headers
4. **Idempotent** — Every write operation supports idempotency keys (critical for agents calling your API)
5. **Versioned** — `/v1/` prefix from day one; never break existing integrations
6. **Webhooks** — Push events to client systems (order completed, fraud detected, etc.)

#### API Standard Patterns:
```
# Authentication
Authorization: Bearer fn_sk_xxxxx

# Standard Response Envelope
{
  "data": { ... },
  "meta": {
    "request_id": "req_abc123",
    "tenant_id": "tn_xyz789",
    "timestamp": "2026-07-09T12:00:00Z"
  }
}

# Standard Error Response
{
  "error": {
    "code": "INVALID_CUSTOMER_ID",
    "message": "Customer with ID 'cust_999' not found.",
    "details": { ... },
    "request_id": "req_abc123"
  }
}

# Idempotency (prevents duplicate actions)
Idempotency-Key: idk_unique_string_here
```

#### E-Commerce Integration Adapters:
```
neura-agents/
└── packages/
    └── neura-adapters/              # Pre-built connectors
        └── src/neura_adapters/
            ├── shopify/             # Shopify REST + GraphQL adapter
            ├── woocommerce/         # WooCommerce REST API adapter
            ├── magento/             # Magento adapter
            ├── custom/              # Generic adapter interface
            └── base.py              # Abstract adapter class
```

> [!IMPORTANT]
> **The Adapter Pattern** is how we make integration easy for existing e-commerce systems. Instead of forcing store owners to change their systems, we build adapters that speak each platform's native language. A Shopify store owner just provides their API credentials, and our adapter handles the translation.

### 0.4 — Protocol Support Strategy

| Protocol | Purpose | When to Implement |
|:---------|:--------|:------------------|
| **REST API** | Primary integration for human developers | Phase 1 (Day 1) |
| **WebSocket** | Real-time chat & streaming responses | Phase 1 |
| **Webhooks** | Push events to client systems | Phase 1 |
| **OpenAPI 3.1** | Machine-readable API documentation | Phase 1 (auto-generated by FastAPI) |
| **MCP Server** | Allow other AI agents to use your agents as tools | Phase 2 |
| **A2A Protocol** | Agent-to-agent collaboration across systems | Phase 3+ |
| **Embeddable Widget** | No-code integration for websites | Phase 2 |

---

## 🚀 Phase 1: First Buildable Milestone — NEURA-CARE MVP

### Goal
Build a **working customer support AI agent** that can:
1. Accept messages via REST API and WebSocket
2. Answer questions from an uploaded knowledge base (RAG)
3. Detect sentiment and adapt responses
4. Escalate to humans when needed
5. Work in a multi-tenant setup (multiple clients can use it)

### 1.1 — Development Environment Setup
- [ ] Initialize monorepo with `uv` workspaces
- [ ] Set up Docker Compose (PostgreSQL, Redis, Qdrant)
- [ ] Configure pre-commit hooks (Ruff linting, formatting)
- [ ] Set up `.env` management
- [ ] Create `Makefile` with standard commands

### 1.2 — Shared Packages
- [ ] `neura-common`: Config, logging, auth, exceptions, telemetry
- [ ] `neura-schemas`: Pydantic models for API contracts
- [ ] `neura-agent-core`: Base agent class, memory interfaces, tool registration

### 1.3 — API Gateway Service
- [ ] FastAPI app with proper middleware stack (auth → tenant → rate-limit → CORS)
- [ ] `/v1/care/chat` — Send a message, get a response
- [ ] `/v1/care/conversations` — List/manage conversations
- [ ] `/v1/care/knowledge-base` — Upload/manage documents
- [ ] `/v1/health` — Health check endpoint
- [ ] WebSocket endpoint for real-time chat
- [ ] Auto-generated OpenAPI spec with proper descriptions
- [ ] Webhook registration and delivery system

### 1.4 — NEURA-CARE Agent
- [ ] LangGraph-based agent with nodes: Router → Sentiment → Responder → Escalation
- [ ] RAG pipeline: Document upload → chunking → embedding → Qdrant storage → retrieval
- [ ] Conversation memory (short-term in Redis, long-term in PostgreSQL)
- [ ] Human escalation with full context handoff
- [ ] Multi-language support (leverage LLM capabilities)

### 1.5 — Multi-Tenancy
- [ ] Tenant creation and API key management
- [ ] Tenant-scoped data isolation (PostgreSQL Row-Level Security)
- [ ] Tenant-specific agent configuration (custom prompts, knowledge bases)
- [ ] Usage tracking per tenant (for future billing)

### 1.6 — Testing & Quality
- [ ] Unit tests for all shared packages
- [ ] Integration tests for API endpoints
- [ ] Agent evaluation suite (test scenarios with expected behavior ranges)
- [ ] CI pipeline (GitHub Actions): lint → test → evaluate → build

### 1.7 — Deployment
- [ ] Dockerize all services
- [ ] Deploy to Railway (initial)
- [ ] Set up LangSmith for agent observability
- [ ] Basic monitoring and alerting

---

## 🔮 What Comes After Phase 1 (Preview)

> [!NOTE]
> We'll create detailed plans for each of these when we get there. This is just to show the roadmap.

| Phase | Focus | Key Deliverables |
|:------|:------|:-----------------|
| **Phase 2** | Polish + Widget + MCP | Embeddable chat widget, MCP server (so other AI agents can call NEURA-CARE), client dashboard (Next.js), Shopify adapter |
| **Phase 3** | NEURA-SELL + Inter-Agent | Sales agent, event bus, shared memory, agent-to-agent communication |
| **Phase 4** | NEURA-MIND + Analytics | Business intelligence agent, dashboards, reporting |
| **Phase 5** | NEURA-GROW + NEURA-GUARD | Marketing + Security agents, full ecosystem |
| **Phase 6** | Scale & Enterprise | On-premise option, SOC 2, marketplace, fine-tuned models |

---

## 🧭 Beyond Technical — Things to Think About for Project Success

### Business & Strategy
| Area | Recommendation |
|:-----|:---------------|
| **Start with 1 customer** | Find one real e-commerce store to be your design partner — build for their needs first |
| **Free tier** | Offer a generous free tier (e.g., 1,000 messages/month) to get adoption |
| **Developer docs site** | Build a proper docs site (use Mintlify or GitBook) — this IS your product's first impression |
| **Open source core?** | Consider open-sourcing the agent framework — builds trust and community |
| **Competitive moat** | Your moat isn't the AI — it's the **cross-agent intelligence** (the ecosystem effect). Rush to multi-agent faster than competitors |

### Legal & Compliance
| Area | Action |
|:-----|:-------|
| **Terms of Service** | Draft ToS for your API (who owns the data, liability, SLA) |
| **Privacy Policy** | GDPR/CCPA compliant — you'll be processing customer data |
| **Data Processing Agreement (DPA)** | Required for enterprise clients |
| **AI transparency** | Disclose when responses are AI-generated (required by EU AI Act) |

### Team & Operations
| Area | Recommendation |
|:-----|:---------------|
| **Documentation culture** | Every feature gets docs + examples before it ships |
| **Changelog** | Maintain a public changelog for your API |
| **Status page** | Set up a status page from day 1 (even if it's just UptimeRobot) |
| **Community** | Start a Discord for developer community early |

---

## 🎯 Immediate Next Step (What We Do Right Now)

Once you approve this plan, here's exactly what happens next:

### Step 1: Initialize the Project Foundation
1. Set up the monorepo structure in your `neura-agents/` directory
2. Configure `uv` workspaces with all packages
3. Set up Docker Compose for local development (PostgreSQL + Redis + Qdrant)
4. Create the `neura-common` shared package (config, logging, auth)
5. Create the `neura-schemas` package (initial API models)
6. Get a basic FastAPI server running with health check

**Estimated time: 1-2 work sessions**

After that, I'll guide you through each subsequent step — building the RAG pipeline, creating the agent, adding multi-tenancy, etc. — one piece at a time with explanations along the way.

---

## User Review Required

> [!IMPORTANT]
> **Please review these key decisions before we proceed:**
> 1. **Start with NEURA-CARE** — Is this still your preferred first agent, or would you rather start with a different one?
> 2. **Python monorepo with `uv`** — Are you comfortable with Python as the primary language? Do you have Python 3.12+ installed?
> 3. **Supabase for PostgreSQL** — You mentioned having Supabase. Should we use it, or set up a local PostgreSQL via Docker?
> 4. **Deployment on Railway** — Is Railway acceptable for initial deployment, or do you prefer another platform?
> 5. **LLM Provider** — Do you have API keys for OpenAI and/or Anthropic? Which would you like to start with?

## Open Questions

> [!WARNING]
> **These don't block us from starting, but we should discuss them soon:**
> 1. **Do you have an existing e-commerce store** (or a partner store) we can use as a design partner for integration testing?
> 2. **Budget for LLM API costs** — The development phase will cost roughly $50-100/month in API calls. Is this okay?
> 3. **GitHub repository** — Is the `neura-agents` directory already a git repo? Should we set one up?
> 4. **Team size** — Is it just you building this, or do you have collaborators? This affects how we structure permissions, code review, etc.
