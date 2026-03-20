# Roadmap: runpod-flash-nemotron

## Overview

Three phases take this from nothing to a complete OSS developer tool: first build the working deployment scripts (the core product), then add integration guides for each target coding tool, then write the README that makes the whole thing accessible to a first-time user. Each phase is independently executable and delivers a complete, verifiable capability.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [ ] **Phase 1: Core Deployment Script** - nemotron.py + download_model.py that successfully deploy Nemotron-3-Super on RunPod A100 80GB
- [ ] **Phase 2: Integration Guides** - Tested config snippets for Claude Code, OpenCode, and Mistral Vibe
- [ ] **Phase 3: README & Documentation** - Complete quickstart README with cost breakdown and known limitations

## Phase Details

### Phase 1: Core Deployment Script
**Goal**: Working deployment that serves Nemotron via OpenAI-compatible endpoint on RunPod A100 80GB
**Depends on**: Nothing (first phase)
**Requirements**: DEPL-01, DEPL-02, DEPL-03, DEPL-04, DEPL-05, DEPL-06, DEPL-07
**Success Criteria** (what must be TRUE):
  1. Developer can run `flash deploy` with `nemotron.py` and get a live RunPod endpoint URL
  2. Developer can pre-populate the network volume with `download_model.py` before first deploy (prevents cold-start timeout loop)
  3. llama-server starts with correct flags (`-ngl 99 --override-tensor "exps=CPU" -c 8192 -fa --no-mmap -np 1 --cont-batching`) and responds to `/v1/chat/completions` requests on port 8080
  4. `execution_timeout=1800` and `idle_timeout` tuning are configured and documented inline
**Research**: Unlikely (stack fully researched; all RunPod Flash SDK params, llama-server flags, and HuggingFace download patterns confirmed at HIGH confidence)
**Plans**: TBD

Plans:
- [ ] 01-01: Write nemotron.py (Endpoint, GpuGroup.AMPERE_80, NetworkVolume, FlashBoot, llama-server CMD)
- [ ] 01-02: Write download_model.py (snapshot_download with HF_TOKEN, UD-Q4_K_XL pattern)

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
- [ ] 02-01: Write integration config snippets for Claude Code, OpenCode, and Mistral Vibe

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
- [ ] 03-01: Write README.md with quickstart, integration links, cost breakdown, and known limitations
- [ ] 03-02: Add MIT LICENSE file

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Core Deployment Script | 0/2 | Not started | - |
| 2. Integration Guides | 0/1 | Not started | - |
| 3. README & Documentation | 0/2 | Not started | - |
