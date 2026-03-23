# Roadmap: runpod-flash-nemotron

## Milestones

- ✅ **v0.1.0 MVP** — Phases 1–6 (shipped 2026-03-22) — see [milestones/v0.1.0-ROADMAP.md](milestones/v0.1.0-ROADMAP.md)
- 🚧 **v0.2.0 Hardening** — Phases 7–10 (in progress)

## Phases

<details>
<summary>✅ v0.1.0 MVP (Phases 1–6) — SHIPPED 2026-03-22</summary>

- [x] Phase 1: Core Deployment Script (2/2 plans) — completed 2026-03-20
- [x] Phase 2: Integration Guides (1/1 plans) — completed 2026-03-20
- [x] Phase 3: README & Documentation (2/2 plans) — completed 2026-03-22
- [x] Phase 4: Streaming Support (1/1 plans) — completed 2026-03-22
- [x] Phase 5: Model Caching (1/1 active, 2 skipped) — completed 2026-03-22
- [x] Phase 6: Warmup Performance (1/1 plans) — completed 2026-03-22

Full details: [milestones/v0.1.0-ROADMAP.md](milestones/v0.1.0-ROADMAP.md)

</details>

### 🚧 v0.2.0 Hardening (In Progress)

**Milestone Goal:** Turn v0.1.0 from "works for me" into a repo a stranger can clone and use.

#### Phase 7: E2E Verification
**Goal**: Verified cold-start-to-inference flow; "not fully verified" disclaimer removed
**Depends on**: Phase 6 (v0.1.0 complete)
**Requirements**: E2E-01
**Success Criteria** (what must be TRUE):
  1. Clean cold start from a fresh volume completes without error
  2. 9-step seed → deploy → warmup → inference checklist documented and verified
  3. "Not fully verified" disclaimer removed from README
  4. Cold start timing measured and documented
**Research**: Unlikely (standard smoke test methodology)
**Plans**: TBD

Plans:
- [ ] 07-01: E2E verification checklist + live test execution

#### Phase 8: Parallel Requests
**Goal**: `--parallel 2` empirically tested; slot priming fixed; trade-offs documented
**Depends on**: Phase 7
**Requirements**: PAR-01
**Success Criteria** (what must be TRUE):
  1. `--parallel 2` empirically tested with VRAM measurement
  2. Slot priming sends N warmup requests for N parallel slots (not just slot 0)
  3. Context window vs parallel trade-off table in README
  4. Outcome documented: either `--parallel 2` ships or ruled out with measured reason
**Research**: Likely (NemotronH SSM state per parallel slot; llama.cpp issue #19552)
**Research topics**: NemotronH SSM recurrent state per slot VRAM; empirical OOM threshold at `--parallel 2`
**Plans**: TBD

Plans:
- [ ] 08-01: Parallel slots investigation + slot priming fix + README update

#### Phase 9: Streaming E2E + Docs
**Goal**: Streaming verified with real clients; curl examples and integration snippets updated
**Depends on**: Phase 7
**Requirements**: STR-01
**Success Criteria** (what must be TRUE):
  1. Streaming verified with Claude Code against live endpoint
  2. Streaming verified with Mistral Vibe against live endpoint
  3. curl examples with `-N` flag in README
  4. Integration snippets updated with streaming examples
**Research**: Unlikely (standard SSE patterns; already documented in FEATURES.md)
**Plans**: TBD

Plans:
- [ ] 09-01: Streaming E2E tests + doc updates

#### Phase 10: Codebase Cleanup
**Goal**: Dead code removed; codebase reads cleanly for a new user
**Depends on**: Phase 9 (code changes settled)
**Requirements**: CLN-01
**Success Criteria** (what must be TRUE):
  1. `download_model.py` removed from repo
  2. `get_cached_model_path()` removed from `nemotron.py`
  3. Stale comments fixed
  4. Codebase reads cleanly for a new user with no dead ends
**Research**: Unlikely (straightforward file removal)
**Plans**: TBD

Plans:
- [ ] 10-01: Remove dead code + fix stale comments

## Progress

**Execution Order:** 7 → 8 → 9 → 10

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Core Deployment Script | v0.1.0 | 2/2 | Complete | 2026-03-20 |
| 2. Integration Guides | v0.1.0 | 1/1 | Complete | 2026-03-20 |
| 3. README & Documentation | v0.1.0 | 2/2 | Complete | 2026-03-22 |
| 4. Streaming Support | v0.1.0 | 1/1 | Complete | 2026-03-22 |
| 5. Model Caching | v0.1.0 | 1/1 (2 skipped) | Complete | 2026-03-22 |
| 6. Warmup Performance | v0.1.0 | 1/1 | Complete | 2026-03-22 |
| 7. E2E Verification | v0.2.0 | 0/TBD | Not started | - |
| 8. Parallel Requests | v0.2.0 | 0/TBD | Not started | - |
| 9. Streaming E2E + Docs | v0.2.0 | 0/TBD | Not started | - |
| 10. Codebase Cleanup | v0.2.0 | 0/TBD | Not started | - |
