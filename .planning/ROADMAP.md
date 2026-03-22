# Roadmap: runpod-flash-nemotron

## Overview

Three phases take this from nothing to a complete OSS developer tool: first build the working deployment scripts (the core product), then add integration guides for each target coding tool, then write the README that makes the whole thing accessible to a first-time user. Each phase is independently executable and delivers a complete, verifiable capability.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: Core Deployment Script** - nemotron.py seeds a shared volume and deploys Nemotron-3-Super on RunPod A100 80GB
- [ ] **Phase 2: Integration Guides** - Tested config snippets for Claude Code, OpenCode, and Mistral Vibe
- [ ] **Phase 3: README & Documentation** - Complete quickstart README with cost breakdown and known limitations

## Phase Details

### Phase 1: Core Deployment Script
**Goal**: Working deployment that serves Nemotron via OpenAI-compatible endpoint on RunPod A100 80GB
**Depends on**: Nothing (first phase)
**Requirements**: DEPL-01, DEPL-02, DEPL-03, DEPL-04, DEPL-05, DEPL-06, DEPL-07
**Success Criteria** (what must be TRUE):
  1. Developer can run `flash deploy` with `nemotron.py` and get a live RunPod endpoint URL
  2. Developer can run a one-time remote seed job with `python nemotron.py seed` before first deploy to populate the network volume (prevents cold-start timeout loop)
  3. llama-server starts with correct flags (`-ngl 99 --override-tensor "exps=CPU" -c 32768 -fa --no-mmap -np 1 --cont-batching`) and responds to `/v1/chat/completions` requests on port 8080
  4. `execution_timeout=1800` and `idle_timeout` tuning are configured and documented inline
**Research**: Unlikely (stack fully researched; all RunPod Flash SDK params, llama-server flags, and HuggingFace download patterns confirmed at HIGH confidence)
**Plans**: In progress - README draft exists but needs reconciliation to current code

Plans:
- [x] 01-01: Write nemotron.py (Endpoint, GpuGroup.AMPERE_80, NetworkVolume, FlashBoot, llama-server CMD)
- [x] 01-02: Write download_model.py (snapshot_download with HF_TOKEN, UD-Q4_K_XL pattern)

### Phase 2: Integration Guides
**Goal**: Developers can connect Claude Code, OpenCode, and Mistral Vibe to their RunPod endpoint with copy-paste config
**Depends on**: Phase 1
**Requirements**: INTG-01, INTG-02, INTG-03
**Success Criteria** (what must be TRUE):
  1. Developer can configure Claude Code to use the RunPod endpoint via `~/.claude/settings.json` or environment variables with a copy-paste snippet
  2. Developer can configure OpenCode to use the RunPod endpoint via `~/.config/opencode/config.json` with a copy-paste snippet
  3. Developer can configure Mistral Vibe to use the RunPod endpoint via environment variable override with a copy-paste snippet
**Research**: Unlikely (config formats for all three tools are documented and stable; OpenCode schema to verify against current repo during execution)
**Plans**: TBD

Plans:
- [x] 02-01: Write integration config snippets for Claude Code, OpenCode, and Mistral Vibe

### Phase 3: README & Documentation
**Goal**: Complete README enabling a first-time user to deploy and integrate in under 5 minutes with no prior RunPod experience
**Depends on**: Phase 2
**Requirements**: DOCS-01, DOCS-02, DOCS-03, DOCS-04, DOCS-05, DOCS-06
**Success Criteria** (what must be TRUE):
  1. Developer can follow the quickstart from zero to working endpoint with explicit prerequisites, HF_TOKEN setup, and cold-start warning
  2. Developer understands cost implications (scale-to-zero vs always-on trade-offs, $20/month math at ~10.5 GPU-hours)
  3. Developer knows recommended sampling params (temp 1.0, top-p 0.95), EU-RO-1 datacenter restriction, and context window limits (`-c` flag options)
  4. Repository includes MIT LICENSE file
**Research**: Unlikely (writing task; no external APIs or integration patterns needed)
**Plans**: TBD

Plans:
- [ ] 03-01: Reconcile README.md to current implementation and deployment flow
- [ ] 03-02: Add MIT LICENSE file

### Phase 4: Streaming Support
**Goal**: Enable SSE streaming through the Flash LB so clients receive tokens as they are generated, eliminating the perceived wait for long responses
**Depends on**: Phase 3
**Requirements**: STRM-01, STRM-02, STRM-03
**Success Criteria** (what must be TRUE):
  1. Flash LB SSE pass-through is confirmed working (or workaround identified)
  2. `stream: true` requests to `/v1/chat/completions` return `text/event-stream` SSE chunks
  3. Open WebUI, Claude Code, and OpenCode receive streamed tokens correctly
**Research**: Required — Flash LB SSE support is unconfirmed; need to test whether chunked transfer encoding passes through or is buffered
**Plans**: TBD

Plans:
- [ ] 04-01: Investigate Flash LB SSE support and implement StreamingResponse proxy

### Phase 5: Model Caching
**Goal**: Replace the network volume model storage with RunPod's native cached models feature to eliminate the 8–10 min cold start and the $7/month fixed volume cost
**Depends on**: Phase 3
**Requirements**: CACHE-01, CACHE-02, CACHE-03, CACHE-04
**Success Criteria** (what must be TRUE):
  1. Cached model host is used on cold start — model loads in seconds, not 8–10 min
  2. Worker resolves the cached model path dynamically at runtime (hash-based snapshot dir)
  3. Network volume is no longer required for model storage (seed flow and volume can be removed or repurposed for binary cache only)
  4. Selective quant download confirmed — only `UD-Q4_K_XL` files cached, not full repo
**Research**: Required — verify whether RunPod cached models supports selective quant patterns for GGUF repos with multiple quantizations; confirm cached path resolution approach
**Plans**: TBD

Plans:
- [x] 05-01: Binary caching on network volume — seed builds llama-server, inference workers restore from volume (cached model approach abandoned; RunPod has no selective quant filtering)

### Phase 6: Warmup Performance
**Goal**: Measure and minimize idle-to-ready time so the endpoint is usable without a standing worker
**Depends on**: Phase 5
**Requirements**: PERF-01, PERF-02, PERF-03
**Success Criteria** (what must be TRUE):
  1. Cold start time (idle → model ready) is measured and documented with warm binary on volume
  2. Network volume read throughput is benchmarked (`dd` from volume) to confirm it's not the bottleneck
  3. `--mlock` evaluated — pins model pages in RAM after first load so subsequent cold starts on the same host skip re-paging
**Research**: Not required — diagnostic work, results will inform whether further optimization is needed
**Plans**: TBD

Plans:
- [x] 06-01: Benchmark cold start, measure volume throughput, evaluate --mlock

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 5 → 6 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Core Deployment Script | 2/2 | Complete | 2026-03-20 |
| 2. Integration Guides | 1/1 | Complete | 2026-03-20 |
| 3. README & Documentation | 2/2 | Complete | 2026-03-22 |
| 4. Streaming Support | 0/1 | Planned | - |
| 5. Model Caching | 1/1 | Complete | 2026-03-22 |
| 6. Warmup Performance | 1/1 | Complete | 2026-03-22 |
