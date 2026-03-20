# Feature Research

**Domain:** Serverless AI inference deployment tool (developer tooling)
**Researched:** 2026-03-20
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Single-file deployment script | Developer tools must minimize setup friction | LOW | `nemotron.py` + `flash deploy` |
| OpenAI-compatible API endpoint | All major AI coding tools consume OpenAI format | LOW | llama-server provides `/v1/chat/completions` out of the box |
| Claude Code integration snippet | Primary target tool; users copy-paste config | LOW | `~/.claude/settings.json` or env vars |
| Cost breakdown | Developers need to budget before committing | LOW | A100 80GB ~$1.89/hr, ~$20/month = ~10.5 GPU-hours |
| HuggingFace model download instructions | `HF_TOKEN` requirement must be documented | LOW | `unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF` |
| Scale-to-zero documentation | Serverless users expect idle cost = $0 | MEDIUM | `workers=(0,1)` with cold start tradeoff explained |
| README quickstart (copy-paste) | OSS repos must work in <5 minutes | LOW | One-command deploy |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Network Volume model caching | Eliminates 83.8 GB re-download on every cold start | MEDIUM | 100 GB persistent volume; model downloaded once |
| FlashBoot support | Snapshot-based cold starts vs full container init | LOW | `flashboot=True` in RunPod Flash SDK |
| OpenCode + Mistral Vibe integration guides | Covers full OSS AI coding assistant ecosystem | LOW | Three tools, one endpoint |
| NVIDIA-recommended sampling defaults | Pre-tuned `--temp 1.0 --top-p 0.95` | LOW | Per NVIDIA's own guidance for this model |
| CPU offload flag documentation | `--override-tensor "exps=CPU"` is non-obvious | LOW | MoE experts must stay in RAM; undocumented by most guides |
| EU-RO-1 datacenter callout | Affects latency for non-EU users | LOW | RunPod Flash serverless restriction |
| idle_timeout tuning guide | Reduces billing on short sessions | LOW | Controls when scale-to-zero kicks in |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| vLLM FP8 path | Better throughput | Requires 2×H100 (~$6+/hr), blows $20/month budget | Stay on GGUF via llama-server |
| Multi-user deployment | Teams want to share | Serverless cold starts + single-context model = bad multi-user UX; out of scope | Point users to dedicated inference providers |
| Web UI / chat interface | Nice to demo | Scope creep; adds complexity; not needed for API backend use case | Use existing UIs (Claude Code, OpenCode) |
| Other model support | Flexibility | This repo's value is the specific Nemotron setup; generalizing dilutes it | Link to generic llama-server guides |
| Streaming by default | Better UX | llama-server supports it; document but don't configure by default to keep script simple | Add as optional flag in config snippets |
| Automatic HF model download on deploy | Convenience | Downloads at deploy time increase script complexity; better to download on first worker start | Download within worker handler |

## Feature Dependencies

```
[Claude Code Integration]
    └──requires──> [OpenAI-compatible API endpoint]
                       └──requires──> [llama-server running]
                                          └──requires──> [Model downloaded to Network Volume]

[Scale-to-zero config]
    └──requires──> [Network Volume caching]
                       (without it, cold start = 2-5 min model download every time)

[FlashBoot fast cold start]
    └──enhances──> [Scale-to-zero config]

[OpenCode Integration] ──parallel──> [Claude Code Integration]
[Mistral Vibe Integration] ──parallel──> [Claude Code Integration]
```

### Dependency Notes

- **Model caching requires Network Volume:** Without the 100 GB persistent volume, every cold start re-downloads 83.8 GB — making scale-to-zero unusable in practice.
- **Scale-to-zero + FlashBoot:** FlashBoot reduces cold start to container init time; still requires Network Volume for model cache.
- **All integrations share the same endpoint:** Claude Code, OpenCode, and Mistral Vibe all point to the same RunPod proxy URL — document once, reference three times.

## MVP Definition

### Launch With (v1)

Minimum viable product — what's needed to validate the concept.

- [ ] `nemotron.py` — single deployment script with Endpoint, GpuType, PodTemplate, Network Volume, FlashBoot
- [ ] llama-server startup with correct flags (`-ngl 99 --override-tensor "exps=CPU" -c 8192 -fa --no-mmap -np 1 --cont-batching`)
- [ ] Model download handler (first-run download via `snapshot_download`, cached to Network Volume)
- [ ] Claude Code integration snippet (`~/.claude/settings.json` + env var approach)
- [ ] OpenCode integration snippet (`~/.config/opencode/config.json`)
- [ ] Mistral Vibe integration snippet (env var override)
- [ ] Cost breakdown table (scale-to-zero vs always-on vs $20/month math)
- [ ] Scale-to-zero vs always-on config documentation
- [ ] MIT LICENSE
- [ ] README with one-command quickstart

### Add After Validation (v1.x)

Features to add once core is working.

- [ ] `idle_timeout` tuning guide — once users report billing surprises
- [ ] Context window tuning documentation (`-c` flag options) — once users ask about longer contexts
- [ ] Streaming config examples — if users request it

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] Other quant variants (Q8_0 for quality, Q3_K_M for smaller VRAM) — research needed
- [ ] Multi-region deployment guide — if RunPod Flash expands beyond EU-RO-1
- [ ] GitHub Actions deploy workflow — convenience feature, not core value

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| `nemotron.py` deployment script | HIGH | MEDIUM | P1 |
| Network Volume model caching | HIGH | LOW | P1 |
| Claude Code integration | HIGH | LOW | P1 |
| OpenCode integration | HIGH | LOW | P1 |
| Mistral Vibe integration | HIGH | LOW | P1 |
| Scale-to-zero documentation | HIGH | LOW | P1 |
| Cost breakdown | HIGH | LOW | P1 |
| FlashBoot config | MEDIUM | LOW | P1 |
| CPU offload flag documentation | HIGH | LOW | P1 |
| `idle_timeout` tuning | MEDIUM | LOW | P2 |
| Streaming examples | LOW | LOW | P3 |
| Multi-region guide | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | Ollama (local) | text-generation-inference (self-hosted) | Our Approach |
|---------|----------------|----------------------------------------|--------------|
| Deployment model | Local machine | Docker/K8s, always-on server | Serverless, pay-per-use |
| Cost | Hardware cost + electricity | VPS/server cost | ~$20/month GPU seconds |
| Cold start | None | None | 0s (always-on) or ~2-5min (scale-to-zero) |
| Model support | Many | Many | Nemotron-3-Super-120B only |
| OpenAI compat | Yes | Yes | Yes (llama-server) |
| Setup complexity | 1 command | Medium | 1 command (`flash deploy`) |
| 120B model support | Requires high-end hardware | Requires multi-GPU server | A100 80GB via GGUF |

## Sources

- RunPod Flash SDK documentation (runpod.io/docs) — deployment patterns, GpuGroup, NetworkVolume, FlashBoot
- llama.cpp server documentation (github.com/ggml-org/llama.cpp) — server flags, GGUF loading
- NVIDIA Nemotron-3-Super-120B-A12B model card (huggingface.co/unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF)
- Claude Code documentation — model configuration, API key / base URL settings
- OpenCode repository (github.com/sst/opencode) — config.json structure
- RunPod community forums — pricing, EU-RO-1 restrictions, scale-to-zero patterns
- Competitor analysis: Ollama, text-generation-inference project pages

---
*Feature research for: Serverless AI inference deployment tool (runpod-flash-nemotron)*
*Researched: 2026-03-20*
