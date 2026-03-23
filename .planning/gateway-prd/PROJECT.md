# llm-api-gateway

## What This Is

A lightweight FastAPI microservice that sits in front of a self-hosted llama-server endpoint
(initially targeting runpod-flash-nemotron) and adds token metering, API key management, rate
limiting, and usage tracking. It exposes an OpenAI-compatible API to clients so existing tools
work without modification. Designed for single-developer, zero-ops deployment on RunPod or any
container host.

## Core Value

Turns a raw, unauthenticated llama-server endpoint into a production-ready API with per-key
billing controls, without requiring any external infrastructure beyond a persistent volume for
SQLite.

## Requirements

### Validated

(empty — new project)

### Active

- [ ] OpenAI-compatible proxy — clients (Claude Code, OpenCode, Mistral Vibe) must send requests
  to the gateway in standard OpenAI format and receive standard OpenAI responses; the gateway
  forwards to a configurable `BACKEND_URL` without requiring client-side changes
- [ ] Token metering from usage fields — extract `prompt_tokens`, `completion_tokens`,
  `total_tokens` from every response; non-streaming reads from the response body; streaming
  requires the gateway to inject `stream_options: {"include_usage": true}` before forwarding and
  capture the final SSE chunk (which carries `"choices": []` plus populated `usage`)
- [ ] SQLite WAL storage for usage logs — all requests logged to `usage_log` table on a SQLite
  database stored at a path configurable via `DB_PATH` env var; WAL mode enables concurrent reads
  without blocking writes; database file persists on a RunPod network volume across cold starts
- [ ] API key validation — incoming `Authorization: Bearer <key>` headers validated against
  SHA-256 hashes stored in the `api_keys` table; plaintext keys are never persisted; inactive
  keys (`active = 0`) are rejected with HTTP 401 before the request reaches the backend
- [ ] Per-key monthly budget enforcement — before forwarding any request, compute the current
  calendar-month spend for the key from `usage_log`; if it meets or exceeds `monthly_budget_usd`,
  reject with HTTP 429 and a descriptive error body; budget `NULL` = unlimited
- [ ] Configurable pricing — input and output token costs set via `COST_INPUT_PER_M` and
  `COST_OUTPUT_PER_M` environment variables (USD per million tokens); `cost_usd` computed at log
  time as `(prompt_tokens * COST_INPUT_PER_M + completion_tokens * COST_OUTPUT_PER_M) / 1_000_000`
- [ ] `/v1/usage` endpoint — authenticated (requires valid API key); returns JSON with per-key
  aggregates for the current calendar month: `total_requests`, `prompt_tokens`,
  `completion_tokens`, `total_tokens`, `cost_usd`; optionally accepts `?month=YYYY-MM` query
  param for historical months
- [ ] `/admin/keys` endpoint — protected by a separate `ADMIN_KEY` env var; supports `GET` (list
  all keys with label, active status, budget), `POST` (create key — returns plaintext key once,
  stores hash), `PATCH /{key_hash}` (update label, active, budget), `DELETE /{key_hash}`
  (deactivate, not hard-delete, to preserve usage history)
- [ ] SSE streaming pass-through — streaming responses forwarded to the client as a live byte
  stream using `StreamingResponse`; the gateway intercepts only the final usage chunk before
  forwarding all chunks; client latency impact must be negligible (no buffering of streaming
  content)
- [ ] Deployable on RunPod Flash as a serverless endpoint — project ships with a `Dockerfile` and
  a `handler.py` compatible with RunPod's serverless worker interface; network volume mount path
  for SQLite is documented; cold start overhead from gateway layer must be under 500ms

### Out of Scope

- Payment collection (Stripe Meters, invoicing) — deferred to v2; v1 only tracks spend, does not
  initiate charges
- Web dashboard UI — CLI and raw API endpoints are sufficient for single-developer use
- Multi-region / multi-backend routing — gateway targets a single `BACKEND_URL`; load balancing
  across multiple llama-server instances deferred until demand justifies it
- Webhook notifications on budget exhaustion — clients receive a 429 at request time; push
  notifications require a job scheduler
- Invoice generation — raw usage data in SQLite is sufficient for manual reconciliation in v1
- Per-endpoint or per-model pricing tiers — single pricing config applies to all traffic
- Request/response body logging — usage metadata only; prompt and completion content are never
  written to storage (privacy and storage size constraints)

## Context

### Relationship to runpod-flash-nemotron

runpod-flash-nemotron is a single-file RunPod Flash deployment of Nemotron-3-Super-120B via
llama-server. It exposes a raw, unauthenticated OpenAI-compatible endpoint. The project is
intentionally minimal and OSS-friendly — adding billing logic there would compromise that goal.

This gateway is a separate microservice and a separate repository. The topology is:

```
client (Claude Code / OpenCode / Mistral Vibe)
    │
    ▼
llm-api-gateway           ← this project
    │   SQLite (network volume)
    ▼
runpod-flash-nemotron     (or any OpenAI-compatible endpoint)
    │
    ▼
Nemotron-3-Super-120B     (llama-server inference)
```

The gateway is backend-agnostic: `BACKEND_URL` can point at any OpenAI-compatible endpoint.
runpod-flash-nemotron is the initial and primary target.

### Token Usage Format

llama-server (post PR #15444) supports two usage collection modes:

**Non-streaming:** `usage` block present in response JSON body at top level, always populated.

**Streaming:** Final SSE chunk has `"choices": []` (empty) and a populated `usage` object. Only
appears when the request includes `"stream_options": {"include_usage": true}`. The gateway injects
this field automatically — clients do not need to set it.

**runpod-flash-nemotron already injects `stream_options` as of v0.2.0** — so the backend is
ready to provide usage data to the gateway.

### Why SQLite

LiteLLM and OpenMeter require PostgreSQL + Redis at minimum. For a single-developer deployment on
RunPod with a network volume, SQLite in WAL mode provides sufficient write throughput (thousands
of inserts per second), zero operational overhead, and a single file that can be inspected
directly with any SQLite client. The schema is append-only for `usage_log`, which is the workload
WAL mode handles best.

### Deployment Model

Runs as a RunPod Flash serverless endpoint alongside the backend. Can also run as a plain Docker
container on any host that can reach the backend URL. The RunPod network volume provides
persistence for the SQLite database across cold starts.

## Constraints

- No external service dependencies at runtime — no Redis, no Postgres, no message queues
- Python only — same language stack as runpod-flash-nemotron for operational consistency
- SQLite file must be on a persistent volume — ephemeral container storage loses all history on
  cold start
- Keys are one-way hashed — no key recovery path; lost keys must be deactivated and reissued
- Gateway must not buffer streaming response bodies — pass-through must remain a true pass-through;
  only the final usage chunk requires inspection
- Admin endpoints must fail closed — if `ADMIN_KEY` is unset at startup, admin routes return 503
- No plaintext key storage — `POST /admin/keys` returns the key exactly once and immediately
  discards it

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| SQLite over PostgreSQL | Zero ops, single file, fits single-dev RunPod deployment; WAL handles append-heavy usage log workload; Postgres+Redis is over-engineered for this scale | SQLite WAL, path via `DB_PATH` env var, persisted on RunPod network volume |
| FastAPI over Flask | Async-native for SSE streaming; same stack as runpod-flash-nemotron; `StreamingResponse` support first-class | FastAPI + `httpx.AsyncClient` for backend requests |
| SHA-256 key hashing | Keys never stored plaintext; SHA-256 is stdlib (`hashlib`), no bcrypt/argon2 needed for high-entropy random keys | `hashlib.sha256(key.encode()).hexdigest()` stored; plaintext returned once at creation |
| Separate repo from runpod-flash-nemotron | Backend is minimal/OSS-friendly; billing logic would couple infrastructure to model-serving and deter contributors | Two independent repos; gateway configured via `BACKEND_URL` env var |
| Gateway injects `stream_options` automatically | Clients (Claude Code, OpenCode) do not set `include_usage` by default; missing it silently breaks metering | Gateway merges `{"stream_options": {"include_usage": true}}` into payload before forwarding when `"stream": true` |
| Calendar-month budget window | Simpler to explain ("resets on the 1st"), simpler to query, consistent with SaaS billing | Budget check: `WHERE strftime('%Y-%m', ts) = strftime('%Y-%m', 'now')` |
| Hard 429 on budget exceeded | Silent over-budget requests create reconciliation problems; hard reject forces the caller to notice | HTTP 429 `{"error": {"type": "budget_exceeded", "message": "Monthly budget exhausted"}}` |
| `ADMIN_KEY` as separate env var | Mixing admin and client key namespaces creates privilege escalation risk | `ADMIN_KEY` env var required; unset = admin routes return 503 |

## Database Schema

```sql
CREATE TABLE usage_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    api_key           TEXT    NOT NULL,   -- SHA-256 hash of the bearer token
    model             TEXT    NOT NULL,
    prompt_tokens     INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens      INTEGER NOT NULL,
    cost_usd          REAL    NOT NULL,
    stream            INTEGER NOT NULL,   -- 0 = non-streaming, 1 = streaming
    request_id        TEXT                -- forwarded from backend response id
);

CREATE TABLE api_keys (
    key_hash           TEXT    PRIMARY KEY,
    label              TEXT,
    active             INTEGER DEFAULT 1,
    monthly_budget_usd REAL                -- NULL = unlimited
);

CREATE INDEX idx_usage_apikey_ts ON usage_log(api_key, ts);

CREATE VIEW key_spend AS
SELECT api_key,
       SUM(prompt_tokens)     AS total_prompt_tokens,
       SUM(completion_tokens) AS total_completion_tokens,
       SUM(cost_usd)          AS total_cost_usd,
       COUNT(*)               AS request_count
FROM usage_log
GROUP BY api_key;
```

## Research Status

### Ready to implement

**Token usage format** — llama-server PR #15444 confirmed. Non-streaming: `usage` always in
response body. Streaming: final chunk `choices:[] + usage` when `stream_options.include_usage=true`.
runpod-flash-nemotron already injects this as of v0.2.0.

**Billing pattern** — surveyed OpenRouter, Anthropic, OpenAI. Per-key hard monthly budget with
429 enforcement is the correct v1 primitive. OpenRouter's per-key credit limits are the closest
model.

**OSS landscape evaluated, none adopted:**

| Project | Problem |
|---------|---------|
| LiteLLM | Postgres + Redis required |
| OpenMeter | Kafka + ClickHouse, SaaS scale |
| Lago | Ruby/Rails, AGPLv3, invoicing focus |
| Portkey | TypeScript, billing is enterprise-only |
| Helicone | Observability only, no billing enforcement |

**Schema finalized** — see Database Schema section above.

**Stack decided** — Python 3.11+, FastAPI, httpx, sqlite3 (stdlib), hashlib (stdlib), env vars
for pricing.

### Open questions for implementation

1. **Streaming chunk inspection without buffering** — final usage chunk must be detected and
   logged without holding up preceding chunks. Proposed: scan SSE lines for `"choices":[]` +
   non-null `usage`, log, yield chunk unchanged. Needs unit test confirming no latency impact.

2. **Concurrent budget race condition** — two simultaneous requests from the same key could both
   pass the budget check and together exceed the limit. Acceptable for v1 (single-developer
   scale). Document explicitly.

3. **RunPod Flash lifespan events** — confirm whether FastAPI `lifespan` startup events fire
   reliably on RunPod Flash cold start for SQLite WAL pragma setup. If not, move pragma to a
   per-request connection factory.

---
*PRD created: 2026-03-23*
*Research status: complete — ready to start implementation planning*
