# Pitfalls Research

**Domain:** Serverless AI inference deployment (RunPod Flash + GGUF)
**Researched:** 2026-03-20
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: UD-Q4_K_XL Fails to Load on Old llama.cpp Builds

**What goes wrong:**
llama.cpp builds before commit `88915cb55c` (pre-PR #20411) fail to load the UD-Q4_K_XL quant with a tensor shape mismatch error. The worker starts, attempts model load, then crashes silently or throws a cryptic assertion error. The endpoint appears deployed but never becomes healthy.

**Why it happens:**
Nemotron-3-Super uses a LatentMoE architecture with tensor shapes that older llama.cpp versions don't handle correctly. The UD-Q4_K_XL quant specifically requires the fix from PR #20411.

**How to avoid:**
Always use `ghcr.io/ggml-org/llama.cpp:server-cuda` latest, or pin to build ≥ b4900. Never use a pinned older image like `server-cuda-b3xxx`.

**Warning signs:**
Worker shows "initializing" indefinitely; logs show tensor errors or `GGML_ASSERT` failures on model load.

**Phase to address:**
Phase 1 (deployment script) — pin the correct Docker image tag.

---

### Pitfall 2: VRAM OOM at Context Lengths Beyond ~4096 Tokens

**What goes wrong:**
The 83.8 GB model weights + KV cache + compute buffers exceeds A100 80 GB VRAM at default or large context lengths. The process is SIGKILL'd silently with no warning to the user — the worker dies and RunPod marks it unhealthy.

**Why it happens:**
Model weights alone occupy ~60-65 GB of VRAM. Each additional 4096 tokens of KV cache consumes several GB more. At `-c 8192` with full KV, the total easily exceeds 80 GB.

**How to avoid:**
Use `--override-tensor "exps=CPU"` to offload MoE routed expert weights to CPU RAM — this is mandatory, not optional. Keep default context at `-c 8192` maximum. Document the tradeoff in README. Use `-fa` (flash attention) to reduce KV cache memory.

**Warning signs:**
Worker restarts mid-conversation; OOM errors in llama-server logs; requests that succeed for short prompts fail for long ones.

**Phase to address:**
Phase 1 (deployment script) — include correct llama-server flags.

---

### Pitfall 3: Cold Start Timeout — 83.8 GB Download Exceeds Worker Init Limit

**What goes wrong:**
RunPod workers have a maximum initialization timeout (~7 minutes). Downloading 83.8 GB from HuggingFace on first cold start takes far longer than this. Without a pre-populated network volume, the endpoint cycles: init → unhealthy → killed → init → ... indefinitely.

**Why it happens:**
Developers deploy the script, see the endpoint "starting," and assume it'll eventually come up. It never does because the download never completes within the timeout.

**How to avoid:**
Pre-populate the network volume before first deploy: run a one-off download job, or provide a `download.py` helper script that users run once to seed the volume. Document this as a required prerequisite step. With network volume populated, subsequent cold starts skip the download entirely.

**Warning signs:**
Endpoint health check never passes; CloudWatch/RunPod logs show download progress that resets repeatedly.

**Phase to address:**
Phase 1 (deployment script) — include model pre-download step in quickstart.

---

### Pitfall 4: NVIDIA's Official Requirements Are 8×H100 — Community-Only Support

**What goes wrong:**
NVIDIA officially targets 8×H100-80GB for Nemotron-3-Super-120B-A12B. Running on a single A100 via GGUF is entirely community-supported and untested by NVIDIA or Unsloth for this specific variant. Users may encounter undocumented behavior.

**Why it happens:**
The model card references FP8/multi-GPU as the primary deployment path. The GGUF path is maintained by the community and may lag behind model updates or have subtle incompatibilities.

**How to avoid:**
Clearly document in README that this is a community-supported GGUF path. Note the known-good llama.cpp build version. Link to the unsloth HuggingFace model discussion thread for latest known issues.

**Warning signs:**
Unexpected output degradation; model card updates that don't mention GGUF compatibility.

**Phase to address:**
Phase 3 (documentation) — README caveats section.

---

### Pitfall 5: Mamba-2 SSM Architecture May Trigger GGML_ASSERT Crashes

**What goes wrong:**
Nemotron-3-Super uses a hybrid Mamba-2 SSM + Transformer architecture. Confirmed crashes (`GGML_ASSERT` at `mamba-base.cpp:173`) have been observed on the Nano variant (same architecture family). The Super variant may exhibit similar issues under certain batch sizes or context configurations.

**Why it happens:**
llama.cpp's Mamba-2 implementation has edge cases around state management. Specific sequence lengths or batch configurations trigger assertion failures.

**How to avoid:**
Use `-np 1` (single parallel slot) to reduce SSM state complexity. Avoid `--cont-batching` with very large batch sizes. Test with several prompts before declaring deployment healthy.

**Warning signs:**
Intermittent worker crashes that don't correlate with context length; crashes on specific prompt patterns.

**Phase to address:**
Phase 1 (deployment script) — conservative `-np 1` default.

---

### Pitfall 6: Execution Timeout Too Short for Long Reasoning Responses

**What goes wrong:**
RunPod's default execution timeout (600 seconds) is insufficient for 120B model responses at ~14 tokens/second. A 16k-token response takes ~1,143 seconds. Requests time out mid-generation; the worker is killed; the user gets a truncated or empty response.

**Why it happens:**
Default timeouts are set for typical API response times (seconds, not minutes). LLM generation at 120B scale is fundamentally slower.

**How to avoid:**
Set `execution_timeout` in the RunPod Flash endpoint config to at least 1800 seconds (30 minutes). Document this in the deployment script with a comment explaining why.

**Warning signs:**
Requests complete for short prompts but fail for long ones; RunPod logs show "execution timeout exceeded."

**Phase to address:**
Phase 1 (deployment script) — set correct timeout in `Endpoint` config.

---

### Pitfall 7: Billing Starts at Worker Init, Not First Token

**What goes wrong:**
Each cold start bills GPU time from the moment the A100 is allocated, not when the first token is generated. At $0.00076/second for an A100, a 3-minute cold start costs ~$0.14 in overhead before any useful work. With frequent cold starts, this overhead can exceed the actual inference cost.

**Why it happens:**
RunPod serverless billing is per-GPU-second of allocation. Model loading (~2-3 minutes on A100 with network volume) is billed time.

**How to avoid:**
Use `idle_timeout` to keep warm workers alive between requests during active sessions. Document the cost math: cold start overhead is ~$0.14/start vs. keeping warm at $1.89/hr. Recommend keeping workers alive during active coding sessions.

**Warning signs:**
Monthly bill higher than expected despite low actual token usage; many short sessions with gaps.

**Phase to address:**
Phase 2 (cost documentation) — include cold start cost in cost breakdown.

---

### Pitfall 8: Network Volume Region-Lock Causes Queuing Delays

**What goes wrong:**
Network volumes are tied to a specific RunPod datacenter. With RunPod Flash currently restricted to EU-RO-1, if A100 80GB GPUs are scarce in that region, requests queue indefinitely waiting for GPU availability.

**Why it happens:**
A100 80GB cards are high-demand. EU-RO-1 is a single datacenter with finite capacity. No automatic failover to other regions.

**How to avoid:**
Document the EU-RO-1 restriction clearly. Advise users to check GPU availability in EU-RO-1 before committing to the setup. Monitor RunPod status page during initial setup.

**Warning signs:**
Endpoint shows "queued" status for extended periods; GPU utilization metrics never start.

**Phase to address:**
Phase 3 (documentation) — known limitations section in README.

---

### Pitfall 9: llama-server OpenAI Compatibility Gaps

**What goes wrong:**
llama-server's OpenAI compatibility is incomplete. Known gaps: `POST /v1/responses` returns 404 (Responses API not supported); streaming + tool use cannot be combined in all versions; some clients default to 30-second timeouts that fail for large model responses.

**Why it happens:**
llama-server implements a subset of the OpenAI API, prioritizing `/v1/chat/completions`. Other endpoints are partially or not implemented.

**How to avoid:**
Test each target client (Claude Code, OpenCode, Mistral Vibe) against the deployed endpoint before declaring it complete. Document known gaps. Instruct users to set client timeout to at least 300 seconds.

**Warning signs:**
Client errors like "404 Not Found" for non-chat endpoints; timeout errors for long responses.

**Phase to address:**
Phase 2 (integration guides) — test each client and document known limitations.

---

### Pitfall 10: HF_TOKEN Baked Into Deployment Script

**What goes wrong:**
If `HF_TOKEN` is hardcoded in `nemotron.py` and committed to a public GitHub repo, the token is permanently exposed. Even after removal, git history retains it.

**Why it happens:**
Developers copy-paste token values into scripts during testing and forget to parameterize them. A public OSS repo amplifies the blast radius.

**How to avoid:**
Always pass `HF_TOKEN` via RunPod Secrets (environment variables), never hardcode in the script. In `nemotron.py`, read it via `os.environ["HF_TOKEN"]`. Add `*.env` and explicit token patterns to `.gitignore`. Add a prominent warning in the README.

**Warning signs:**
HuggingFace sends token compromise emails; unexpected API usage on HF account.

**Phase to address:**
Phase 1 (deployment script) — use `os.environ` for all secrets from the start.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hardcoding model path in script | Simpler code | Breaks when model moves; users can't customize | Never — use constants |
| No model hash verification | Faster download | Silent model corruption goes undetected | Never for production |
| Not documenting llama-server version | Less maintenance | Users hit UD-Q4_K_XL load bug; support burden | Never — pin the version |
| Omitting idle_timeout config | Simpler deployment | Unexpected billing for idle workers | MVP only, document it |
| Single-line quickstart without prerequisites | Lower friction | Users hit cold start timeout; abandon project | Document prerequisites first |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| HuggingFace download | Use `hf_hub_download` for individual files | Use `snapshot_download` with `allow_patterns="UD-Q4_K_XL/*"` — downloads all 3 split files |
| RunPod Secrets | Pass token as env var in script | Configure via RunPod dashboard Secrets; reference as `os.environ["HF_TOKEN"]` |
| llama-server startup | Call server synchronously in handler | Start server as background process; poll `/health` endpoint before serving requests |
| Claude Code config | Use `ANTHROPIC_BASE_URL` | Use `ANTHROPIC_BASE_URL` for proxy + `ANTHROPIC_API_KEY` set to any non-empty string |
| OpenCode config | Use `openai` provider type | Provider type must be `openai`; `baseURL` must include `/v1` |
| Mistral Vibe | Set `MISTRAL_API_KEY` | Set `OPENAI_BASE_URL` + `OPENAI_API_KEY`; Mistral Vibe respects OpenAI env vars |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Default context `-c 32768` | VRAM OOM; worker crashes | Set `-c 8192` maximum | Immediately on A100 80GB |
| Parallel slots `-np 4` | Increased VRAM; instability | Use `-np 1` for single-user | Any concurrent request |
| No `--no-mmap` flag | Slow model loading on network volume | Always use `--no-mmap` | Every cold start |
| Flash attention disabled | Higher VRAM KV cache | Always use `-fa` | At >4096 token contexts |
| No `--cont-batching` | Queued requests time out | Enable for responsiveness | Multiple pending requests |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| HF_TOKEN in source code | Token exposure in public repo | RunPod Secrets + `os.environ` |
| RunPod API key in script | Full account access if leaked | RunPod Secrets; never in code |
| No API key on llama-server | Open endpoint accessible by anyone with URL | Set `--api-key` flag; document in integration configs |
| Endpoint URL in README | Public repo = public endpoint | Instruct users to keep their proxy URL private |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No model pre-download step in quickstart | Users deploy, wait 10+ minutes, endpoint never comes up | Add explicit "Step 0: seed network volume" to README |
| Cold start not mentioned | Users think deployment is broken when first request takes 3 min | Prominent cold start warning with time estimate |
| No test command in README | Users unsure if deployment worked | Include `curl` test command for `/v1/chat/completions` |
| EU-RO-1 buried in docs | Non-EU users surprised by latency | Put it in README prerequisites section |
| Execution timeout not explained | Users confused when long responses fail | Explain the 1800s setting in deployment script comments |

## "Looks Done But Isn't" Checklist

- [ ] **Deployment script:** Often missing `--api-key` flag — verify llama-server requires auth
- [ ] **Model caching:** Often missing pre-population step — verify network volume has model files before first deploy
- [ ] **Claude Code integration:** Often missing timeout config — verify client doesn't use default 30s timeout
- [ ] **Cost documentation:** Often missing cold start overhead — verify cost math includes per-start billing
- [ ] **Scale-to-zero docs:** Often missing `idle_timeout` explanation — verify users know how to tune it
- [ ] **Security:** Often missing HF_TOKEN warning — verify README has prominent secrets guidance

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| UD-Q4_K_XL load failure | LOW | Update Docker image tag in `nemotron.py`; redeploy |
| VRAM OOM | LOW | Reduce `-c` value; ensure `--override-tensor "exps=CPU"` is present |
| Cold start timeout loop | MEDIUM | Manually seed network volume via RunPod pod; then retry serverless deploy |
| HF_TOKEN exposure | HIGH | Revoke token immediately on HuggingFace; create new token; update RunPod Secret |
| Execution timeout | LOW | Increase `execution_timeout` in Endpoint config; redeploy |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| UD-Q4_K_XL load failure | Phase 1: Deployment script | Test `llama-server --version` shows build ≥ b4900 |
| VRAM OOM | Phase 1: Deployment script | Test with 8192-token prompt; no OOM in logs |
| Cold start timeout | Phase 1: Deployment script | Network volume pre-populated; cold start < 5 min |
| Execution timeout | Phase 1: Deployment script | `execution_timeout=1800` in Endpoint config |
| HF_TOKEN exposure | Phase 1: Deployment script | No token literals in `nemotron.py`; `os.environ` only |
| OpenAI compat gaps | Phase 2: Integration guides | Test each client end-to-end |
| Billing surprises | Phase 2: Cost documentation | Cost math reviewed and accurate |
| EU-RO-1 region lock | Phase 3: Documentation | Noted in README prerequisites |

## Sources

- unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF model discussion on HuggingFace — UD-Q4_K_XL load bug, PR #20411 confirmation (HIGH confidence)
- llama.cpp GitHub issues and PRs — Mamba-2 SSM crash reports, GGML_ASSERT at mamba-base.cpp:173 (MEDIUM confidence)
- RunPod serverless documentation — billing model, worker init timeout, Secrets management (HIGH confidence)
- RunPod community forums — EU-RO-1 restriction, A100 availability, cold start patterns (MEDIUM confidence)
- RunPod Flash SDK source/docs — execution_timeout, idle_timeout, NetworkVolume patterns (HIGH confidence)
- HuggingFace security best practices — token management (HIGH confidence)

---
*Pitfalls research for: Serverless AI inference deployment (runpod-flash-nemotron)*
*Researched: 2026-03-20*
