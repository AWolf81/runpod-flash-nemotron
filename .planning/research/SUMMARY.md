# Project Research Summary

**Project:** runpod-flash-nemotron
**Domain:** RunPod Flash serverless LLM deployment hardening
**Researched:** 2026-03-22
**Milestone:** v0.2.0 Hardening
**Confidence:** HIGH

---

## Executive Summary

v0.2.0 is a hardening milestone, not a feature milestone. The system works — it just hasn't been
fully verified from a clean state, and it has rough edges (cleanup needed, parallel slots
uninvestigated, streaming untested end-to-end with real clients). The research confirms all four
target areas are tractable: none require architectural changes.

The biggest finding is about parallel slots: Nemotron-3-Super's hybrid Mamba/attention architecture
means the KV cache is ~10–30× smaller than a comparable dense transformer. With only 48 attention
layers (of 88 total) and 2 KV heads, the KV budget at `--parallel 2 --ctx-size 32768` is ~0.38 GB
— negligible against the 14.5 GB of VRAM headroom. `--parallel 2` is almost certainly viable and
the investigation should focus on empirical measurement and documentation, not feasibility.

The critical pitfall is that slot priming currently covers only slot 0. With `--parallel 2`, slot 1
will be unprimed and the second concurrent request may time out. This needs to be fixed as part of
the parallel slots work. The other pitfalls (curl -N, ctx-size pool semantics, fresh-volume vs
warm-worker distinction) are documentation and test methodology issues rather than code bugs.

---

## Key Findings

### Recommended Stack

Testing stack for v0.2.0: `pytest` + `pytest-asyncio` (asyncio_mode=auto) + `httpx-sse>=0.4.3` +
`openai>=1.30` + `python-dotenv`. For VRAM monitoring: `gpustat --watch 1` or `nvidia-smi`.
Do NOT use `sseclient` (wrong transport), `respx`/`pytest-httpx` (mocking defeats E2E purpose),
or `torch.memory_allocated()` (reports wrong process's VRAM).

**Core technologies:**
- `pytest-asyncio`: Async test support — required for httpx streaming tests
- `httpx-sse`: Spec-correct SSE parsing — `aconnect_sse()` / `aiter_sse()` handles edge cases
- `openai`: Same client Claude Code uses — realistic E2E tests
- `gpustat` / `nvidia-smi`: Only tools that report actual GPU driver VRAM

### Expected Features

The v0.2.0 table stakes: documented E2E flow, verified streaming, investigated parallel slots,
cleaned codebase. All four are required to remove the "not fully verified" README disclaimer.

**Must have (table stakes for v0.2.0):**
- E2E verification checklist (9-step: seed → deploy → cold → warmup → ready → non-stream → stream → models) — new users need this
- Streaming verified with real clients (Claude Code + Mistral Vibe) — currently unverified
- Parallel slots investigated (math says `--parallel 2` is viable; needs empirical confirmation)
- Codebase cleanup (`download_model.py` removal, `get_cached_model_path()` removal)

**Should have:**
- Context window vs parallel trade-off table in README
- `--parallel 2` slot priming fix (prime all N slots, not just slot 0)

**Defer:**
- `--parallel 4` investigation — reduces ctx-size below user expectations; not worth the tradeoff
- KV cache quantization — not needed; 14.5 GB headroom is ample at `--parallel 2`

### Architecture Approach

The architecture is already correct for v0.2.0. FastAPI StreamingResponse + httpx.aiter_bytes()
is the right SSE pass-through pattern. The `_slot_primed` flag is the right approach for
NemotronH KV cache init — it just needs to prime all N slots when `--parallel N > 1`.

**Major components:**
1. RunPod Flash LB — HTTP proxy, passes SSE through (`X-Accel-Buffering: no` is critical)
2. FastAPI worker — `StreamingResponse` + `httpx.AsyncClient` streaming proxy
3. llama-server — `--parallel N --ctx-size C` where C = N × target_ctx_per_slot
4. `_slot_primed` flag — must send N warmup requests for N parallel slots

### Critical Pitfalls

1. **Slot 0 only priming** — current `_slot_primed` sends one warmup request; `--parallel 2` means slot 1 unprimed → second concurrent request times out. Fix: send N concurrent warmup requests.
2. **--ctx-size is a pool** — `--parallel 2 --ctx-size 32768` gives each slot 16K context. Set `--ctx-size = N × target_ctx`. Document this trade-off explicitly.
3. **Fresh volume vs warm worker** — testing a warm worker restart masks cold start bugs. True E2E requires a clean volume.
4. **curl -N omitted** — streaming tests without `--no-buffer` make streaming look broken. Always use `curl -N`.
5. **RunPod 600s LB timeout** — hard platform limit; affects only very long non-streaming requests. Document in README.

---

## Implications for Roadmap

### Phase 1: E2E Verification
**Rationale:** Most blocking — keeps the "not fully verified" disclaimer in README. New users can't trust the repo until this is done.
**Delivers:** Verified 9-step cold-start-to-inference flow; README disclaimer removed; cold start timing documented.
**Addresses:** E2E verification, cold start documentation
**Avoids:** Pitfall 3 (warm worker masking cold start bugs) — must test on fresh/clean volume

### Phase 2: Parallel Slots Investigation + Fix
**Rationale:** Math says `--parallel 2` is viable (0.38 GB KV vs 14.5 GB headroom). Needs empirical measurement and slot priming fix.
**Delivers:** `--parallel 2` either ships (with fix) or is ruled out with documented reason; trade-off table in README.
**Implements:** Slot priming for N slots (fix `_slot_primed` to send N warmup requests)
**Avoids:** Pitfall 1 (NemotronH SSM state multiplication), Pitfall 2 (ctx-size pool semantics), Pitfall 3 (slot 0 only primed)

### Phase 3: Streaming E2E Verification + Docs
**Rationale:** Streaming works per code review but is untested with real clients (Claude Code + Mistral Vibe).
**Delivers:** Streaming verified end-to-end; curl examples with `-N` in README; integration snippets updated.
**Uses:** `httpx-sse`, `openai` SDK for tests; `curl -N` examples in docs
**Avoids:** Pitfall 4 (curl -N omitted), Pitfall 7 (proxy buffering under parallel load)

### Phase 4: Codebase Cleanup
**Rationale:** Remove dead code that confuses new users. `download_model.py` is superseded by `python nemotron.py seed`. `get_cached_model_path()` is dormant.
**Delivers:** Clean, minimal codebase; no stale files; stale comments fixed.
**Avoids:** New user confusion; future maintenance of dead code

### Phase Ordering Rationale

- E2E first because it's the blocker for removing the disclaimer — most impactful for "stranger can use this"
- Parallel slots second because it requires E2E to be working (you need a clean inference path to test concurrency)
- Streaming third because it depends on E2E and potentially parallel slots being stable
- Cleanup last — safe to do anytime, but better after code changes settle

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (Parallel Slots):** May need llama.cpp issue research on NemotronH SSM state per slot; empirical measurement required

Phases with standard patterns (skip research-phase):
- **Phase 1 (E2E):** Standard smoke test methodology
- **Phase 3 (Streaming):** Standard SSE testing patterns; already documented in FEATURES.md
- **Phase 4 (Cleanup):** Straightforward file removal; no research needed

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|-----------|-------|
| Stack | HIGH | pytest-asyncio + httpx-sse + openai SDK are well-documented standard choices |
| Features | HIGH | KV cache math verified from model config.json; streaming protocol from llama.cpp docs |
| Architecture | HIGH | Parallel slot memory math from actual Nemotron-3-Super config (48 attn layers, 2 KV heads); confirmed by llama.cpp discussions |
| Pitfalls | HIGH (llama.cpp), MEDIUM (RunPod-specific) | llama.cpp issues verified; RunPod 600s timeout and SDK routing bug from community reports |

**Overall confidence:** HIGH

### Gaps to Address

- **NemotronH SSM recurrent state per parallel slot:** Math says ~200MB/slot is not a problem, but empirical VRAM measurement during Phase 2 should confirm this. The architecture agent notes llama.cpp issue #19552 / PR #19559 for NemotronH SSM slot allocation.
- **RunPod 600s LB timeout:** Community reports, not official docs. Treat as informational; document defensively.
- **Fresh volume E2E:** The actual cold start timing from a truly fresh volume (no cached binary) has not been timed recently. Seed phase may be faster now with binary caching. Measure during Phase 1.

---

## Sources

### Primary (HIGH confidence)
- llama.cpp server README — `--parallel`, `--ctx-size`, `--cont-batching` flags
- llama.cpp discussion #4130 — unified KV cache across slots; ctx-size is total pool
- Nemotron-3-Super HuggingFace model card — 48 attention layers, 2 KV heads, head_dim 128
- httpx-sse PyPI — `aconnect_sse`, `aiter_sse` API
- FastAPI StreamingResponse docs — SSE implementation

### Secondary (MEDIUM confidence)
- llama.cpp discussion #18308 — diminishing returns past 4 parallel slots
- llama.cpp issue #19552 / PR #19559 — NemotronH SSM slot allocation
- RunPod community — 600s LB timeout, SDK routing bug in 1.7.11–1.7.12

### Tertiary (LOW confidence)
- RunPod Flash E2E verification patterns — no official docs found; derived from general serverless LLM deployment patterns

---
*Research completed: 2026-03-22*
*Ready for roadmap: yes*
