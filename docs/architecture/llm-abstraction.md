# LLM Abstraction — Ollama in Development, Cloud in Production

> **Status:** Draft for review · **Last updated:** 2026-07-25

We develop against local Ollama models because the LLM budget is zero. Production runs on a cloud API for quality. The same code must serve both, and — critically — **we must be able to measure what changes when we swap**.

This document also serves the [data-sovereignty product tier](../business/blueprint-v2.md#43-data-sovereignty--turning-a-constraint-into-the-moat): the local path is not throwaway dev scaffolding, it is a shipping deployment mode.

---

## 1. Principles

1. **Application code names a *role*, never a model.** `llm.for(Role.ROUTER)` — never `"llama3.2:3b"` and never `"gpt-4o"`. Model identifiers exist in exactly one place: configuration.
2. **One code path.** Ollama exposes an OpenAI-compatible `/v1` endpoint. We drive every provider through that surface, so there is no `if provider == "ollama"` anywhere in the codebase.
3. **Capabilities are declared, not assumed.** Providers differ in native tool calling, JSON-schema enforcement, and context length. The runtime asks; it does not guess.
4. **Every swap is measured.** No model or provider changes without an eval run. See [evaluation-strategy.md](evaluation-strategy.md).
5. **Cost and tokens are first-class.** Every call is metered against a per-tenant budget with a circuit breaker.

---

## 2. Model Roles

Roles decouple *what a call needs* from *which model serves it*. This is what makes dev→prod a config change.

| Role | Used for | Needs | Volume |
|:--|:--|:--|:--|
| `ROUTER` | Intent classification, short structured decisions | Fast, cheap, strict JSON | Highest |
| `REASONER` | Answer generation, tool selection, multi-step reasoning | Quality, reliable tool calling | High |
| `GUARD` | Injection detection, groundedness verification | Fast, precise, low false-positive | High |
| `EMBEDDER` | Vector embeddings for RAG | Consistent dimensions, batchable | Very high |
| `SUMMARIZER` | Conversation compaction, escalation handoff notes | Long context, cheap | Low |

### 2.1 Role maps

**Development — local Ollama** (all of these are already pulled on this machine):

```yaml
llm:
  default_provider: ollama
  providers:
    ollama:
      base_url: http://localhost:11434/v1
      api_key: ollama            # required by the OpenAI client, ignored by Ollama
  roles:
    router:      { provider: ollama, model: "llama3.2:3b",           temperature: 0.0 }
    reasoner:    { provider: ollama, model: "qwen3.5:9b",            temperature: 0.3 }
    guard:       { provider: ollama, model: "llama3.1:8b",           temperature: 0.0 }  # ADR-0018
    embedder:    { provider: ollama, model: "nomic-embed-text",      dimensions: 768  }
    summarizer:  { provider: ollama, model: "llama3.1:8b",           temperature: 0.3 }
```

**Production — cloud.** Same shape, different values; models are chosen at the time by eval results and current pricing, not fixed here:

```yaml
llm:
  default_provider: cloud
  roles:
    router:      { provider: cloud, model: "<small-fast-model>",  temperature: 0.0 }
    reasoner:    { provider: cloud, model: "<frontier-model>",    temperature: 0.3 }
    guard:       { provider: cloud, model: "<small-fast-model>",  temperature: 0.0 }
    embedder:    { provider: cloud, model: "<embedding-model>",   dimensions: 1536 }
    summarizer:  { provider: cloud, model: "<mid-model>",         temperature: 0.3 }
```

**Sovereign — customer-hosted Ollama.** Identical to development, pointed at the customer's inference host, usually with larger models where their hardware allows.

**Hybrid is legitimate and expected.** Roles are independent, so routing and embedding can stay local (high volume, cheap, privacy-sensitive) while only `REASONER` goes to a cloud API. This is likely the best production cost/quality point, and the role design makes it a config edit.

---

## 3. Interface

`packages/neura-llm`.

```python
class LLMProvider(Protocol):
    name: ClassVar[str]
    capabilities: ClassVar[frozenset[LLMCapability]]

    async def chat(self, req: ChatRequest) -> ChatResponse: ...
    async def chat_stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]: ...
    async def chat_structured[T: BaseModel](
        self, req: ChatRequest, schema: type[T]
    ) -> StructuredResponse[T]: ...
    async def embed(self, texts: list[str]) -> EmbeddingResult: ...
```

```python
class LLMCapability(StrEnum):
    NATIVE_TOOL_CALLING = "tools.native"  # OpenAI-style tool_calls
    JSON_SCHEMA_MODE = "json.schema"  # server-enforced schema
    JSON_MODE = "json.object"  # valid JSON, unconstrained shape
    STREAMING = "streaming"
    VISION = "vision"
    PARALLEL_TOOL_CALLS = "tools.parallel"
    LOGPROBS = "logprobs"
```

Every response carries usage and cost, always:

```python
class ChatResponse(BaseModel):
    content: str
    tool_calls: list[ToolCall]
    usage: Usage  # prompt/completion/total tokens
    cost_usd: Decimal  # 0 for local — still recorded, for margin modelling
    model: str
    provider: str
    latency_ms: int
    finish_reason: str
```

Local calls record `cost_usd = 0` but still record tokens and latency. Without that we cannot model what a workload *would* cost on cloud before switching — which is exactly the decision the role map exists to support.

---

## 4. Structured Output — the hard part with local models

**This is where a naive Ollama→cloud abstraction breaks.** An 8B local model is materially less reliable than a frontier model at emitting strictly-schema-valid JSON and at multi-step tool calling. If that is discovered during a production swap, the swap has already failed.

### 4.1 A capability-tiered strategy

`chat_structured()` picks the strongest mechanism the provider actually declares:

| Tier | Requires | Mechanism |
|:--|:--|:--|
| 1 | `JSON_SCHEMA_MODE` | Server-side constrained decoding — malformed output is impossible |
| 2 | `JSON_MODE` | Valid JSON guaranteed, shape validated by Pydantic |
| 3 | *(nothing)* | Schema in the prompt + extraction from the reply |

Ollama supports constrained decoding via its `format` parameter accepting a JSON Schema, so most local models reach **Tier 1**. That is the single most important fact for making the local path viable, and it is why local-first is workable at all.

### 4.2 The repair loop

Even at Tier 1, semantic mistakes happen — right shape, wrong enum value.

```
attempt 1 ─► validate ─► ✅ return
                │
                ✘ ─► attempt 2: original + the validation error, verbatim
                          │
                          ✘ ─► attempt 3: same, temperature 0
                                    │
                                    ✘ ─► StructuredOutputError
                                          → node handles it → escalate
```

Bounded at three attempts. Every repair is counted as a metric — a rising repair rate is the early warning that a model is unsuitable for a role, and it is far better to see it on a dashboard than in an incident.

### 4.3 Tool calling without native support

Some local models lack `NATIVE_TOOL_CALLING`. Rather than abandoning them, the runtime falls back to a structured "which tool and what arguments" decision, validated against the tool's JSON schema. Slower and weaker, so the eval suite reports tool-selection accuracy per model and the fallback is never silent.

---

## 5. The Embedding Dimension Trap

**Read this before writing any RAG code.**

`nomic-embed-text` produces **768** dimensions. Cloud embedding models produce **1536** or **3072**. Vectors from different models are **not comparable** — cosine similarity between them is meaningless. The failure mode is the dangerous kind: no exception, no error, just quietly worse retrieval that looks like "the agent got dumber".

Since our stated plan is to develop on Ollama and deploy on cloud, we will hit this. It is designed for, not discovered.

### 5.1 Namespaced collections

Every vector row is keyed by tenant **and** embedding model:

```sql
CREATE TABLE document_chunks (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL,
    embedding_model  TEXT NOT NULL,     -- 'nomic-embed-text' | 'cloud-embed-v3' | ...
    dimensions       INT  NOT NULL,
    embedding        VECTOR NOT NULL,
    content          TEXT NOT NULL,
    source_type      TEXT NOT NULL,     -- 'product' | 'policy' | 'faq'
    source_id        TEXT NOT NULL,
    metadata         JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON document_chunks (tenant_id, embedding_model, source_type);
```

**Every retrieval query filters on `(tenant_id, embedding_model)`.** The active model comes from config, so a mismatch returns zero rows — loudly wrong, which is recoverable — rather than nonsense, which is not.

### 5.2 Reindex procedure

Switching embedding models is a migration, and it is documented as one:

1. Add the new model to config as `embedder_next`, leaving `embedder` serving traffic.
2. Backfill: re-embed all chunks under the new model's namespace. Both namespaces now coexist.
3. Run retrieval evals against both. Compare recall@k on the golden set.
4. Promote `embedder_next` → `embedder`.
5. Keep the old namespace for one release, then drop it.

Zero downtime, measured, reversible.

---

## 6. Cost, Budgets and Circuit Breakers

Directly serves [blueprint-v2 §8](../business/blueprint-v2.md#8-pricing) — flat pricing with unbounded inference is an unbounded liability.

**Metered per call:** tenant, conversation, role, model, prompt/completion tokens, cost, latency. Written to `llm_usage` and to Langfuse.

**Enforced per tenant:**

```yaml
budgets:
  daily_cost_usd:        { soft: 8.00,  hard: 12.00 }
  monthly_cost_usd:      { soft: 200.0, hard: 300.0 }
  per_conversation_tokens: 40_000
  per_conversation_llm_calls: 25
```

**Degradation ladder — never a hard failure for the shopper:**

| Trigger | Behaviour |
|:--|:--|
| Soft limit | Alert the merchant. Downgrade `REASONER` to a cheaper model. Shorten retrieval. |
| Hard limit | Circuit open. Agent switches to **escalate-only** — it politely hands every conversation to a human. |
| Per-conversation cap | Summarize and escalate. Prevents a single adversarial conversation draining a tenant's month. |
| Provider outage | Fall back to the configured secondary provider; if none, escalate-only. |

The per-conversation cap matters more than it looks: without it, one user in a loop with a tool-calling agent can burn a tenant's entire budget in an afternoon.

---

## 7. Caching

| Layer | Key | TTL | Why |
|:--|:--|:--|:--|
| Embedding cache | `hash(text) + model` | 30d | Catalogue re-syncs mostly re-embed unchanged text |
| Exact-match response | `hash(prompt + tools + model)` | 1h | Identical questions arrive in bursts |
| Semantic response cache | Embedding similarity ≥ 0.97, per tenant | 1h | "where is my order" has a thousand phrasings |

**The semantic cache is deliberately restricted to answers containing no order- or customer-specific data.** Serving one shopper's order status to another would be a data breach, and a similarity threshold is not an access-control mechanism. Any response derived from a tool call carrying customer data is marked non-cacheable at the tool layer, not by heuristics on the text.

---

## 8. The Dev → Production Swap

The procedure, as a checklist. This is the moment the abstraction either pays for itself or does not.

1. **Baseline.** Run the full eval suite on the Ollama role map. Record every metric.
2. **Configure** the cloud role map. No code changes — if code changes are needed, that is a bug in this layer.
3. **Reindex embeddings** per §5.2 if the embedder changed. Do not skip; do not assume.
4. **Run evals on the cloud map.** Compare against baseline.
5. **Review the delta.** Expect quality up and cost up. Anything that got *worse* is a real finding — larger models are not uniformly better, especially on strict formatting and refusal behaviour.
6. **Shadow.** Run cloud config in shadow mode on live traffic; human-grade a sample.
7. **Roll out per tenant**, monitoring cost per resolution against §6 budgets.

### 8.1 Comparison report

`make eval-compare` produces this, and it is what makes the swap a decision rather than a leap of faith:

```
Role map: ollama-dev  →  cloud-prod

  intent accuracy         0.87  →  0.94   +0.07  ✔
  groundedness            0.79  →  0.91   +0.12  ✔
  tool selection acc.     0.72  →  0.96   +0.24  ✔   ← the big local-model gap
  structured repair rate  0.14  →  0.01   -0.13  ✔
  escalation precision    0.88  →  0.85   -0.03  ⚠   ← regression, investigate
  p95 latency (ms)        4100  →  1900   -2200  ✔
  cost / resolution       $0.00 →  $0.041  +      ─   feeds the pricing model
```

The numbers above are illustrative placeholders showing the report's shape, not measurements. Tool-selection accuracy is the metric most likely to show a large gap; escalation precision is the one most likely to regress unnoticed.

---

## 9. Local Model Notes

Practical constraints discovered on this machine. Recorded so they are designed around, not rediscovered.

| Constraint | Consequence |
|:--|:--|
| Ollama serves limited concurrent requests by default | Set `OLLAMA_NUM_PARALLEL`; assume dev throughput is low and do not build load tests against it |
| Model load/unload thrashing when many models are used | Keep the dev role map to 3 distinct models; `OLLAMA_KEEP_ALIVE` for the hot ones |
| 8–9B models are weak at multi-step tool chains | Prefer single-tool turns in graph design; the agent graph is explicit partly for this reason |
| Low-resource languages (incl. Sinhala) degrade badly at this size | Do not promise multilingual quality from the local tier — measure it first ([blueprint-v2 §11.4](../business/blueprint-v2.md)) |
| Context windows are smaller than cloud | Retrieval budget is a config value per role map, not a constant |
| No GPU on typical PaaS hosts (Railway, Fly, Render) | Production cloud inference is an API call; **sovereign** deployments require the customer's own GPU host |

**Models available locally today:** `llama3.2:3b`, `llama3.1:8b`, `qwen3:8b`, `qwen3.5:9b`, `qwen2.5-coder:7b`, `qwen2.5-coder:32b`, `deepseek-r1:14b`, `nomic-embed-text`.

**A model is not fit for a role until it has been measured in that role.** `llama3.2:3b` served `GUARD` for three milestones and, measured, called an invented delivery date and a contradicted order status "grounded" 10 times out of 10 each — while refusing pleasantries the prompt exempts. It is a capable classifier and was never a verifier. `make verify-probe` is the check, it is free, and [ADR-0018](adr/0018-guard-model-must-refuse.md) makes passing it the bar for the role.

---

## 10. Open Questions

1. **Cloud provider choice.** Deliberately unfixed. Decided by eval results, latency and price at the time of the swap — the whole point of this layer is that the decision is deferrable and reversible.
2. **Reasoning models.** `deepseek-r1:14b` is available locally. Whether visible reasoning helps the verify/guard nodes enough to justify its latency is an open experiment.
3. **Fine-tuning.** A small fine-tuned router could beat a large general model at intent classification, cheaply. Only worth exploring once real conversation data exists (and only with opt-in — [blueprint-v2 §7.5](../business/blueprint-v2.md)).
4. **Sovereign hardware floor.** What is the minimum spec at which quality is acceptable? Needs measurement before the tier can be sold. **One hard input as of 2026-08-13:** the floor includes an 8B verifier beside the 8B reasoner, because a 3B in the `GUARD` role cannot tell an invented delivery date from a real one ([ADR-0018](adr/0018-guard-model-must-refuse.md)).
