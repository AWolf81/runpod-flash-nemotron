---
phase: 06-warmup-performance
plan: 01
status: complete
completed: 2026-03-22
---

# 06-01 Summary: Warmup Performance

## What Was Built

### docs/benchmarks.md (new file, 268 lines)

Four sections covering the full cold start picture:

1. **Network Volume Throughput** — dd benchmark command (run on live RunPod worker), 200–800 MB/s
   expected range, mmap load time formula, and full stage-by-stage breakdown of the 16m30s
   baseline and 8m45s optimized cold start.

2. **Cold Start Timing** — Methodology using `time bash warmup.sh`, what to record (binary restore,
   page cache preload, VRAM load, total), and a results table with both observed data points
   (baseline 16m30s, optimized 8m45s).

3. **--mlock Evaluation** — Verdict: do NOT add `--mlock`. Bottleneck is network volume read →
   PCIe DMA to VRAM, not CPU page faults. `--mlock` pins pages after fault resolution but does not
   speed up the initial network read. Current `preload_model()` parallel-dd approach achieves the
   same warm-cache goal without mlock risks. `auto_warmup()` flags in `install_llama_server.sh`
   unchanged.

4. **Cost of Warmup** — Thorough monthly cost analysis (see key numbers below).

### nemotron.py — Slot Priming Fix

`gpu_health()` now sends a one-shot priming POST to `http://127.0.0.1:8081/v1/chat/completions`
(max_tokens=1) the first time llama-server transitions to `status=ok`. This absorbs the NemotronH
hybrid-attention KV cache initialization (llama.cpp PR #13194: "forcing full prompt re-processing
due to lack of cache data"). The `gpu_api.state.slot_primed` flag ensures priming fires exactly
once per worker lifetime. Failure is non-fatal — logs a warning, marks primed, returns ready.

## Notable Decisions

- **mlock ruled out** for network volume scenario. Re-evaluate if RunPod introduces local NVMe.
- **Slot priming** uses `gpu_api.state` (FastAPI app state) rather than a module-level global, as
  module globals could be reset between requests depending on the Flash worker model.
- **finally block** guarantees `slot_primed=True` even if the priming request raises — prevents
  infinite retry loops on /health poll.
- **Warmup cost is small vs idle cost**: at typical 4 warmups/day, warmup overhead is $24.64/month
  but idle time dominates total spend. Tuning `idle_timeout` matters more than warmup speed for
  monthly bill control.

## Key Numbers (Cost of Warmup)

| Metric | Value |
|---|---|
| GPU rate | $1.69/hr (RTX Pro 6000 Blackwell) |
| Cold start (optimized) | ~8m45s |
| Cold start (baseline) | ~16m30s |
| Cost per warmup (optimized) | **$0.28** |
| Cost per warmup (baseline) | **$0.48** |
| Savings per warmup from optimization | $0.20 |
| Typical warmups/month (4/day, 22 days) | 88 |
| Monthly warmup overhead (typical) | **$24.64/month** |
| Monthly warmup overhead (baseline, same usage) | **$42.24/month** |
| Monthly total estimate (typical, scale-to-zero) | **~$126/month** |
| Always-on comparison (9h/day, 22 days) | **~$334/month** |
| Break-even recommendation | Scale-to-zero wins for single developer |

Recommended `idle_timeout` settings: 300 (sporadic), 3600 (focused sessions), 28800 (full workday).

## Verification Checklist

- [x] docs/benchmarks.md exists with all four sections
- [x] docs/benchmarks.md contains runnable dd benchmark command
- [x] docs/benchmarks.md contains warmup.sh timing methodology with 16m30s baseline
- [x] docs/benchmarks.md has results table with 2 observed data points
- [x] --mlock evaluation explains why it doesn't help for network volume + VRAM loading
- [x] nemotron.py /health sends priming request after first llama-server ok, sets slot_primed flag
- [x] install_llama_server.sh auto_warmup() flags unchanged (no regression)
