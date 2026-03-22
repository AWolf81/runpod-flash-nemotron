# Feature Research

**Domain:** RunPod Flash LLM deployment hardening (v0.2.0)
**Researched:** 2026-03-22
**Confidence:** HIGH (parallel slots math), MEDIUM (E2E checklist — no RunPod Flash-specific docs found), HIGH (streaming)

---

## Context: What This Project Is

Single-file RunPod Flash deployment of Nemotron-3-Super-120B (UD-Q4_K_XL GGUF, ~79 GB weights) via
`llama-server` on RTX Pro 6000 Blackwell (96 GB VRAM). The worker proxy in `nemotron.py` handles
server lifecycle, streaming pass-through, and health signalling. v0.2.0 goal: harden the deployment
so a new user can go from `git clone` to working inference with no gotchas.

---

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| `/health` returns `{"status":"ready"}` before first request | Every production API has a readiness check; tooling polls it | LOW | Already implemented; `llama-server /health` → 200 `{"status":"ok"}` means ready, 503 means loading |
| `/v1/models` returns model list | OpenAI clients call this first to verify connectivity | LOW | Already implemented |
| Non-streaming `POST /v1/chat/completions` returns valid JSON | Baseline functionality; tools like Claude Code hit this path | LOW | Works; proxy pattern in place |
| SSE streaming (`"stream": true`) delivers tokens incrementally | Claude Code, Mistral Vibe, and all modern AI coding tools default to streaming | MEDIUM | Implemented via `StreamingResponse` pass-through; needs live E2E test |
| Stream terminates with `data: [DONE]` | OpenAI spec; SDKs (openai-python, etc.) break if missing | LOW | llama-server emits this natively; proxy passes bytes through unchanged |
| Cold start documented with timing | Users need to know why first request takes 3–10 min | LOW | Needs documented flow: cold → warmup → ready |
| Documented deploy → seed → infer flow | New users have no idea what "seed" means | LOW | Missing in current README; must ship in v0.2.0 |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Hybrid Mamba KV cache efficiency | Nemotron 3 Super's sparse attention means KV cache is ~10–30x smaller per token than a pure transformer of comparable size; parallel slots are much cheaper here than on e.g. Llama-3-70B | LOW (already baked into model arch) | ~6,144 bytes/token for attention layers only (6 heads × 2 KV × head_dim 128 × 2 bytes); Mamba recurrent state is fixed-size ~200 MB, not context-scaled |
| Slot priming on warmup | First request on NemotronH hybrid architecture triggers KV cache init (llama.cpp PR #13194); pre-sending a 1-token request at `/health` absorbs this penalty | LOW | Already implemented via `_slot_primed` flag |
| `POST /warmup` + keepalive pattern | Separates "start llama-server" from "wait for llama-server" so callers can poll without blocking | LOW | Already implemented |
| Volume-cached llama-server binary | Binary built once during `seed`, reused by all workers — no compile on cold start | LOW | Already implemented |
| `--override-tensor "exps=CPU"` MoE expert offload | Allows model to fit on single GPU by keeping MoE expert weights in system RAM | MEDIUM | Documented in ARCHITECTURE.md; not yet surfaced in README quickstart |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| High `--parallel` (8–16 slots) | "More concurrent users" | At 96 GB VRAM with 79 GB model weights, headroom for KV cache is ~15–17 GB. Even with Nemotron's efficient hybrid KV, at 32k ctx per slot this fills fast. Benchmarking shows diminishing returns past 4 slots even on unconstrained hardware; CPU sampling becomes the bottleneck. | Set `--parallel 2` with reduced `--ctx-size`; document as the investigated outcome |
| Unified large context (128k+) + parallel | Best of both | `--ctx-size` is shared across all slots. 2 slots × 32k = 64k total cache; 2 slots × 64k = 128k total cache. KV VRAM scales linearly. At 96 GB, model uses ~79 GB → ~15 GB headroom → sets hard ceiling. | Choose: large context OR parallel slots, not both |
| FlashBoot snapshot cold starts | Sub-second cold start | Flash LB force-kills workers at ~5 min, preventing snapshot write. `flashboot=False` is correct. | Document why it's disabled; use Network Volume binary cache instead |
| vLLM FP8 path for throughput | Better tokens/sec | Requires multi-H100 ($6+/hr), incompatible with the "pay for GPU seconds" budget model | GGUF via llama-server is the right path for this use case |
| Web chat UI | Demo-ability | Scope creep; users have Claude Code, OpenCode, and Mistral Vibe | Link to existing frontends |
| Auto-scale to many workers | Handle traffic spikes | Workers are stateful (llama-server process + loaded model); each new worker pays full cold start cost; no shared KV state across workers | `workers=(0,2)` is sufficient; document the trade-off |

---

## Deep Dive: Parallel Inference Slots

### How `--parallel N` Works in llama-server

- `--parallel N` allocates N independent sequence slots in a unified KV cache.
- `--ctx-size C` sets the **total** KV cache across all slots (not per-slot).
- Each slot gets up to `C / N` tokens in the worst case; the cache is flexible
  (one slot can use more if others use less), but total cannot exceed C.
- Formula for sizing: `--ctx-size = target_ctx_per_slot × N`
- Continuous batching (`--cont-batching`, on by default) lets slots share prefill
  batches with generation, improving GPU utilization.

### VRAM Budget for Nemotron-3-Super-120B on RTX Pro 6000 Blackwell (96 GB)

```
Model weights (UD-Q4_K_XL):       ~79 GB
Compute buffers / overhead:         ~3–4 GB
Available for KV cache:            ~13–14 GB
```

**Nemotron 3 Super KV cache per token** (hybrid Mamba-2 + sparse attention):
- Model has ~6 attention layers (of 88 total); Mamba layers use fixed recurrent state, not token-scaled KV.
- Per-token KV bytes ≈ `n_attention_layers × 2 (K+V) × n_kv_heads × head_dim × bytes_per_elem`
- Using 2 KV heads, head_dim=128, f16 (2 bytes): `6 × 2 × 2 × 128 × 2 = 6,144 bytes/token ≈ 6 KB/token`
- Compare: a dense 70B transformer = ~100–200 KB/token.

**KV cache at `--ctx-size 32768`, `--parallel 1`:**
- `32,768 × 6,144 bytes ≈ 0.19 GB` — negligible.

**KV cache at `--ctx-size 32768`, `--parallel 2`:**
- `65,536 × 6,144 bytes ≈ 0.38 GB` — still well within 13 GB headroom.

**KV cache at `--ctx-size 65536`, `--parallel 2`:**
- `131,072 × 6,144 bytes ≈ 0.76 GB` — still safe.

**Conclusion:** Because Nemotron 3 Super's hybrid architecture has very few attention layers,
parallel slots 2 are viable at current context sizes with substantial headroom remaining.
`--parallel 2` with `--ctx-size 32768` is a safe starting point; `--parallel 4` with
reduced ctx should also be feasible. This makes the "parallel slots" investigation likely
to conclude with **"viable, document the trade-off"** rather than "not feasible".

**Caveat:** The fixed Mamba recurrent state (~200 MB per process) does not scale with
parallel slots — it is loaded once. Only attention KV scales.

### KV Cache Quantization Option

If headroom becomes tight: `--cache-type-k q8_0 --cache-type-v q8_0` halves KV memory
at slight quality cost. Not needed at `--parallel 2` for this model, but worth documenting.

---

## Deep Dive: SSE Streaming

### What Correct Streaming Looks Like

llama-server implements the OpenAI SSE streaming protocol natively:

1. Client sends `POST /v1/chat/completions` with `"stream": true`.
2. Server responds with `Content-Type: text/event-stream`.
3. Each token arrives as: `data: {"id":"...","choices":[{"delta":{"content":"token"},...}]}\n\n`
4. Stream ends with: `data: [DONE]\n\n`
5. Connection closes.

The `nemotron.py` proxy uses `httpx` streaming + FastAPI `StreamingResponse` to pass bytes
through unchanged. The proxy does **not** re-encode or buffer — `aiter_bytes()` yields raw
SSE frames directly to the client. This is the correct approach.

### How to Test Streaming (curl)

```bash
# Basic SSE stream test — requires -N (--no-buffer) to see tokens as they arrive
curl -N https://<runpod-endpoint-url>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RUNPOD_API_KEY>" \
  -d '{
    "model": "nemotron",
    "messages": [{"role":"user","content":"Count from 1 to 5 slowly."}],
    "stream": true,
    "max_tokens": 50
  }'
```

**What to verify:**
- Tokens appear one by one, not all at once (confirms streaming, not buffering)
- Each line starts with `data: {`
- Final line is `data: [DONE]`
- `Content-Type: text/event-stream` in response headers

### How to Test with OpenAI Python Client

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://<runpod-endpoint-url>/v1",
    api_key="<RUNPOD_API_KEY>",
)

stream = client.chat.completions.create(
    model="nemotron",
    messages=[{"role": "user", "content": "Count from 1 to 5."}],
    stream=True,
    max_tokens=50,
)
for chunk in stream:
    delta = chunk.choices[0].delta.content
    if delta:
        print(delta, end="", flush=True)
print()
```

### Known SSE Edge Cases in llama-server

- Error messages from llama-server may not always be RFC 8895-compliant SSE
  (Issue #16104 in llama.cpp). The proxy wraps errors as `data: <error_body>\n\n`
  which is non-standard but parseable.
- Some SDKs warn on `data: [DONE]` because it is not valid JSON; this is expected
  and harmless — the spec defines `[DONE]` as a literal string sentinel, not JSON.
- If llama-server returns 503 during stream setup (still loading), the proxy yields
  the error body and closes. Callers should poll `/health` until `status=ready` first.

---

## Deep Dive: E2E Verification

### What "E2E Verified" Means for a RunPod Flash Deployment

E2E verification for this project = a new user can execute the following sequence on a
fresh volume (no cached binary, no cached model) and reach working inference:

**Flow to verify:**
```
1. git clone + pip install runpod-flash
2. HF_TOKEN=hf_... python nemotron.py seed     ← downloads model + builds binary to volume
3. flash deploy                                 ← deploys inference endpoint
4. curl GET /health → {"status":"cold"}         ← worker started, llama-server not yet running
5. curl POST /warmup → {"status":"warming_up"}  ← llama-server launched
6. poll GET /health every 30s → {"status":"warming_up",...} then {"status":"ready"}
7. curl POST /v1/chat/completions (non-stream)  ← first inference (tests slot priming path)
8. curl POST /v1/chat/completions (stream=true) ← SSE streaming
9. curl GET /v1/models → {"data":[{"id":"nemotron",...}]}
```

**What passes = verified:**
- Steps 1–3 complete without error on a clean machine
- Step 6 reaches `ready` within ~10 min of first warmup call (model load time)
- Step 7 returns valid JSON with `choices[0].message.content` non-empty
- Step 8 delivers incremental SSE tokens, ends with `[DONE]`
- Step 9 returns the model list

### Cold Start Timing Expectations

| Phase | Expected Time | Notes |
|-------|--------------|-------|
| `seed` (first run, clean volume) | 30–90 min | 84 GB model download; binary build ~5 min |
| `seed` (subsequent runs) | ~10 sec | Both binary and model already cached |
| Worker cold start (post-deploy) | 30–60 sec | Container init + Python import; llama-server not yet started |
| `POST /warmup` → `status=ready` | 5–10 min | Loading 79 GB GGUF into 96 GB VRAM |
| First inference (post-ready) | ~5–10 sec extra | Slot priming (hybrid KV cache init, absorbed at `/health`) |
| Subsequent inferences | ~1–3 sec TTFT | Normal operation |

**RunPod FlashBoot note:** `flashboot=False` in `nemotron.py` because Flash LB kills workers
before snapshot can be written (~5 min limit). Cold start timing above reflects full container
init, not snapshot-based boot.

### Minimum E2E Test Checklist (for new user documentation)

- [ ] `pip install runpod-flash` succeeds
- [ ] `python nemotron.py seed` completes with `binary: cached/rebuilt` + `model: downloaded`
- [ ] `flash deploy` succeeds and returns endpoint URL
- [ ] `GET /health` on fresh worker returns `{"status":"cold"}` or `{"status":"warming_up"}`
- [ ] `POST /warmup` returns `{"status":"warming_up",...}`
- [ ] `GET /health` eventually returns `{"status":"ready"}` (within 10 min)
- [ ] `POST /v1/chat/completions` (non-stream) returns JSON with non-empty content
- [ ] `POST /v1/chat/completions` (stream=true) delivers SSE tokens + `[DONE]`
- [ ] `GET /v1/models` returns `{"data":[{"id":"nemotron",...}]}`

---

## MVP Definition for v0.2.0

### Must Ship

- [ ] **E2E verification docs** — written test sequence (above checklist) added to README so new users
  know exactly what to run and what success looks like. Removes "not fully verified" disclaimer.

- [ ] **Parallel slots investigation + outcome** — test `--parallel 2` with `--ctx-size 32768`
  (VRAM math shows this is safe); document result as either "ships with `--parallel 2`" or
  "not recommended, here's why". The KV cache math strongly suggests 2 is viable.

- [ ] **Streaming E2E test + docs** — run the curl streaming test above against live endpoint;
  test Claude Code and Mistral Vibe against streaming endpoint; document results in README.

- [ ] **Cold start flow doc** — single-page or README section explaining the warmup lifecycle
  (`cold` → `warming_up` → `ready`) with expected timings.

### Should Ship

- [ ] **`POST /admin/debug` callout** — document this endpoint as the first thing to run if
  something is broken (shows binary/model/env state).

- [ ] **Context window vs parallel trade-off table** — one table showing `--parallel N` +
  `--ctx-size C` combinations with VRAM cost and recommendation.

### Defer

- [ ] KV cache quantization (`--cache-type-k q8_0`) — not needed at `--parallel 2` for this model.
- [ ] `--parallel 4` — possible, but requires reducing ctx-size below user expectations; document
  as future option.
- [ ] Multi-region deployment — RunPod Flash still primarily EU-RO-1 for Flash serverless.

---

## Sources

| Source | Confidence | Used For |
|--------|------------|----------|
| [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | HIGH | `--parallel`, `--ctx-size`, `--cache-type-k/v` flags |
| [Parallelization/Batching Discussion #4130](https://github.com/ggml-org/llama.cpp/discussions/4130) | HIGH | How unified KV cache works across slots; ctx-size is total not per-slot |
| [Optimal parallel params Discussion #18308](https://github.com/ggml-org/llama.cpp/discussions/18308) | MEDIUM | Diminishing returns past 4 slots; CPU sampling bottleneck |
| [KV cache Mamba vs Transformer (The Kaitchup)](https://kaitchup.substack.com/p/the-kv-cache-of-small-moes-qwen3) | HIGH | Hybrid MoE KV cache per-token math; Mamba fixed state ~200 MB |
| [VRAM Requirements 2026 Guide](https://localllm.in/blog/llamacpp-vram-requirements-for-local-llms) | MEDIUM | Per-slot KV cache scaling; Q4_K_M + Q8_0 KV quantization |
| [How to Calculate VRAM (Advanced)](https://twm.me/posts/how-to-calculate-vram-requirement-local-llm-advanced/) | HIGH | KV cache formula: `layers × 2 × bytes × head_dim × kv_heads` |
| [Simon Willison: How Streaming LLM APIs Work](https://til.simonwillison.net/llms/streaming-llm-apis) | HIGH | SSE protocol, `data: [DONE]` termination, curl `-N` flag |
| [llama-stack Issue #4744: SDK streaming `[DONE]` handling](https://github.com/llamastack/llama-stack/issues/4744) | HIGH | `[DONE]` is not JSON; SDKs warn but it is correct per spec |
| [llama-server SSE RFC8895 Issue #16104](https://github.com/ggml-org/llama.cpp/issues/16104) | MEDIUM | Error SSE messages may not be spec-compliant |
| [RunPod FlashBoot blog](https://www.runpod.io/blog/introducing-flashboot-serverless-cold-start) | HIGH | FlashBoot requires request volume to warm; snapshot mechanism |
| [Nemotron 3 Super HF model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16) | HIGH | Architecture: hybrid Mamba-2 + sparse attention; 2 KV heads; head_dim 128 |
| [nemotron-3-super-120b NIM model card](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard) | MEDIUM | GQA: 32 query heads, 2 KV heads, head_dim 128 |
| [RunPod deploy llama.cpp guide](https://www.runpod.io/articles/guides/deploy-llama-cpp-cloud-gpu-hosting-headaches) | LOW | General deployment patterns; E2E verification = monitor nvidia-smi + first prompt |

---

*Feature research for: runpod-flash-nemotron v0.2.0 hardening*
*Researched: 2026-03-22*
