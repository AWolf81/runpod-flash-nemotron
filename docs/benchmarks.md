# Nemotron Endpoint Benchmarks

Reference for cold start timing, volume throughput, --mlock evaluation, warmup cost analysis, HumanEval coding benchmarks, and long-context retrieval checks.

---

## HumanEval pass@1 (Coding Benchmark)

Evaluated on the full [OpenAI HumanEval](https://github.com/openai/human-eval) benchmark (164 Python coding problems) using `scripts/humaneval.py`.

### Setup

- Model: `nemotron-super-120b-iq4` (IQ4_XS GGUF, RTX Pro 6000 Blackwell 96 GB)
- Endpoint: RunPod Flash, `p2/ctx100k` (parallel=2, ctx_size=100000, flash_attn=on)
- Evaluation: single sample per problem, temperature=0.0 (greedy), max_tokens=512
- Script: `check_correctness` from the `human-eval` package; prompt prepended internally by the library

### Result (2026-03-29, full 164 problems)

| Metric | Value |
|---|---|
| **pass@1** | **57.9% (95/164)** |
| avg generation speed | 78.9 tok/s |
| avg latency | 4.93 s/problem |
| workers | 1 |
| runtime | p2/ctx100000 |

Full results JSON: [humaneval-nemotron-super-120b-iq4-2026-03-29-200017.json](benchmarks/humaneval-nemotron-super-120b-iq4-2026-03-29-200017.json)

### Context on the Score

**57.9% on 164 problems** is the correct full-set baseline. Earlier runs reporting 80% used only the first 20 problems (`n=20`), which are the easiest in the dataset and are not representative.

The 69 failures break down as:
- **Truncated completions** (~15–20 failures): model re-echoes the docstring before writing the implementation and hits the 512-token limit mid-string, producing a syntax error. Raising `--max-tokens` to 2048 is expected to recover several of these.
- **Logic errors** (~50 failures): genuine incorrect implementations (wrong algorithm, off-by-one, incorrect string handling).

All failures are `checker_assertion` type — no `request_error` or `checker_timeout` failures, confirming the endpoint and evaluation harness are stable.

### Generation Speed Note

The 78.9 tok/s observed here is ~3× higher than earlier `p2/ctx100k` runs (which showed ~24.9 tok/s). Investigation confirmed the earlier runs hit the endpoint during or immediately after a cold start transition; the 78.9 tok/s is the real steady-state throughput for this config on a warm worker.

### Running the Benchmark

```bash
# Full 164-problem run (recommended)
python scripts/humaneval.py --n 164 --workers 1 --failures --label p2-ctx100k

# Quick 20-problem check (note: first 20 are easy, not representative of full score)
python scripts/humaneval.py --n 20 --workers 1 --failures

# With higher token limit (recommended for accurate scoring)
python scripts/humaneval.py --n 164 --max-tokens 2048 --failures --label p2-ctx100k-2k
```

Results are appended to [docs/benchmarks/humaneval-summary.md](benchmarks/humaneval-summary.md). This table is intentionally curated to only keep decision-relevant runs.

## Context Size Needle Benchmark (CTX Limit + Degradation)

HumanEval is a coding benchmark, not a long-context retrieval benchmark.  
For context-window feasibility and degradation, run `scripts/ctx_needle.py`.

What this measures:
- Whether a given prompt size can run at all (request errors usually indicate context cap).
- Whether retrieval quality drops as context grows (needle match rate).
- Latency trend versus the smallest successful context in the sweep.

### Commands

```bash
# 1) Validate p2 / ctx100k runtime
LLAMA_PARALLEL=2 LLAMA_CTX_SIZE=100000 flash deploy --env production
NEMOTRON_BENCH_ENDPOINT="https://c1fb77ul6l2dw2.api.runpod.ai" \
python scripts/ctx_needle.py \
  --contexts 32768,65536,90000,100000,115000 \
  --samples 2 \
  --label p2-ctx100k-needle

# 2) Validate p1 / ctx131072 runtime (~130k feasibility target)
LLAMA_PARALLEL=1 LLAMA_CTX_SIZE=131072 flash deploy --env production
NEMOTRON_BENCH_ENDPOINT="https://c1fb77ul6l2dw2.api.runpod.ai" \
python scripts/ctx_needle.py \
  --contexts 32768,65536,100000,115000,130000 \
  --samples 2 \
  --label p1-ctx131072-needle
```

Outputs:
- JSON artifact: `docs/benchmarks/ctx-needle-*.json`
- Markdown summary: `docs/benchmarks/ctx-needle-summary.md`

### Latest Context-Cap Summary (2026-03-29)

Measured with `scripts/ctx_needle.py` on warmed workers (single-request `p1`), using prompt-token counts reported by the API.

| Runtime | Recommended safe prompt size | Max observed without context error | Hard fail limit observed | Notes |
|---|---:|---:|---:|---|
| `p2/ctx100000` | ~40k prompt tokens (provisional) | **24,169** prompt tokens | **88,694** prompt tokens (`n_ctx=50176`) | `~50k` behaves like a fail boundary on this setup; treat p2 as experimental until re-validated. |
| `p1/ctx100000` | ~90k prompt tokens | **94,792** prompt tokens | **100,207** prompt tokens (`n_ctx=100096`) | Practical boundary is very close to 100k; keep headroom for tokenizer variance. |
| `p1/ctx131072` | ~125k prompt tokens | **130,076** prompt tokens | **132,755** prompt tokens (`n_ctx=131072`) | Upper range works, but some high-end probes intermittently hit host-level 502 before retry/cap-probe confirmation. |

Interpretation:
- **p1 recommendation**: use ~**65k prompt tokens** as the default for agentic workflows; reserve 100k+ for exceptional long-context tasks.
- For `p2`, **~50k is not a safe target** on current evidence; it aligns with the observed failure boundary (`n_ctx=50176`), not a comfort zone.
- If you want predictable behavior, target the **safe** column.
- If you want absolute edge testing, use values near the **max observed** column and expect occasional instability.
- Any request above the **hard fail** boundary is rejected by llama-server with `exceed_context_size_error`.

---

Reference for cold start timing, volume throughput, --mlock evaluation, and warmup cost analysis.

---

## Network Volume Throughput

The primary bottleneck for cold start is the RunPod network volume read speed. llama-server uses
`mmap()` to load the model, so tensors are loaded lazily — but CUDA immediately triggers page faults
across the full 79 GB model weight set, forcing sequential read from the volume.

**Formula:**
```
mmap load time ≈ model_size / volume_throughput
```

RunPod network volumes typically deliver **200–800 MB/s** single-stream sequential read.

| Throughput | 79 GB load time | Notes |
|---|---|---|
| 200 MB/s | ~6.6 min | Low end; matches observed 3–6 min load |
| 400 MB/s | ~3.3 min | Mid range |
| 800 MB/s | ~1.6 min | High end (unlikely sustained) |

**Full cold start breakdown (baseline, single-stream sequential read):**

| Stage | Duration | What happens |
|---|---|---|
| Binary restore from volume | ~1 s | `cp /runpod-volume/cache/llama-server /app/llama-server` |
| Model mmap (volume → page cache) | ~3–7 min | Network volume read at 200–400 MB/s |
| CUDA tensor transfer (page cache → VRAM) | ~3–5 min | PCIe Gen4 x16 (~15–20 GB/s real); 60 GB GPU weights |
| KV cache + context allocation | ~1–2 min | 32768 ctx, 4–8 GB VRAM |
| **Total observed (baseline)** | **~16m30s** | Phase 5 measurement, single dd stream |
| **Total observed (optimized)** | **~8m45s** | 4 concurrent dd streams per shard (preload_model()) |

The optimized path runs `preload_model()` in `auto_warmup()` before starting llama-server: 4
parallel `dd` readers per shard pre-populate Linux page cache, so CUDA DMA hits RAM (~50 GB/s)
rather than the network volume (~200 MB/s). This halves cold start time.

### Throughput Benchmark Command

Run this on a live RunPod worker (not locally — `/runpod-volume` does not exist on the dev machine):

```bash
# Single-stream sequential read — establishes the volume's baseline throughput
dd if=/runpod-volume/models/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf \
   of=/dev/null bs=128M iflag=direct 2>&1 | tail -1
```

`iflag=direct` bypasses the page cache, giving a true network volume number (not cached).

For a parallel-stream benchmark that mirrors the actual preload strategy:

```bash
# 4 concurrent streams on shard 1 (mirrors preload_model())
FILE=/runpod-volume/models/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf
SIZE=$(stat -c%s "${FILE}")
BS=$((128 * 1024 * 1024))
BLOCKS=$(( (SIZE + BS - 1) / BS ))
BPS=$(( (BLOCKS + 3) / 4 ))
for s in 0 1 2 3; do
    dd if="${FILE}" of=/dev/null bs="${BS}" skip=$(( s * BPS )) count="${BPS}" 2>/dev/null &
done
wait
echo "Done"
```

### How to Run

1. Ensure the binary and model are seeded: `python nemotron.py seed`
2. Deploy: `flash deploy`
3. SSH into the RunPod worker via the RunPod console, or use a manual job
4. Run the `dd` command above and record the MB/s figure
5. Add result to the Results table in the Cold Start Timing section below

---

## Cold Start Timing

**Definition:** Cold start = RunPod worker boot → llama-server first token ready.

This applies when `workers_min=0` (scale-to-zero) and a new request wakes the endpoint.
The worker boots, runs `install_llama_server.sh`, restores the cached binary, pre-loads page cache,
and starts llama-server. The endpoint only serves requests once `GET /health` returns `{"status":"ready"}`.

### Timing Methodology

`warmup.sh` polls `/health` every 10s and prints a timestamped status line. The elapsed wall time
from script start to the "Ready!" message is the cold start duration.

```bash
# Run from your local machine after deploy
time bash warmup.sh https://<ENDPOINT_ID>-8080.proxy.runpod.net
```

`warmup.sh` already prints `HH:MM:SS — <status>` per poll. The final timestamp when status
transitions to `ready` is the cold start end. `time` gives the total wall duration.

### What to Record

| Metric | How to measure |
|---|---|
| Binary restore time | install_llama_server.sh stdout: "Restoring llama-server from volume cache" → binary ready |
| Page cache preload time | install_llama_server.sh stdout: "Pre-loading model shards..." → "Page cache warm" |
| Model load time (VRAM) | warmup.sh: `warming_up (loading tensors)` → `ready` transition |
| Total cold start | `time bash warmup.sh ...` wall time |
| Volume throughput | dd benchmark (see above) |

### Results

| Date | Binary Status | Page Cache Preload | Model Load (VRAM) | Total Cold Start | Volume Throughput | Notes |
|---|---|---|---|---|---|---|
| 2026-03-22 | cached (volume) | ~4m15s (4 streams/shard) | ~4m30s | ~8m45s | ~200 MB/s est. | Optimized; 4 parallel dd streams per shard |
| 2026-03-15 | cached (volume) | none (sequential) | ~10m | ~16m30s | ~200 MB/s est. | Baseline; single-stream sequential mmap |

_Add new rows after each cold start measurement. Volume throughput column: run the dd benchmark
above on the same worker and record MB/s._

---

## --mlock Evaluation

### What --mlock Does

`--mlock` calls `mlock()` on the model's memory-mapped pages, pinning them in physical RAM. Pages
pinned with mlock cannot be swapped out. On the **same worker instance**: a second cold start
(e.g., llama-server restart) skips re-paging since the pages are still resident. On a **new worker
boot** (scale-to-zero): no benefit — pages were never loaded on that instance.

### VRAM Context for This Model

| Resource | Size |
|---|---|
| Model weights (GPU layers) | ~60 GB VRAM |
| KV cache (32768 ctx) | ~4–8 GB VRAM |
| CUDA overhead | ~3–5 GB |
| **Total VRAM used** | **~67–73 GB of 96 GB** |
| VRAM headroom | ~24–30 GB |

### Why --mlock Does Not Help Here

The bottleneck is **network volume read throughput → PCIe DMA to VRAM**, not CPU page fault
resolution:

1. llama-server uses `mmap()`. The model file is memory-mapped from the network volume.
2. When CUDA loads tensors, it triggers page faults. The kernel must read 79 GB from
   `/runpod-volume` (network-attached storage) at ~200 MB/s.
3. `--mlock` would pin those CPU pages after they are faulted in, but it does **not** speed up the
   initial fault resolution — the network read still has to happen first.
4. For repeated restarts on the same worker: `--mlock` helps (pages stay pinned). But scale-to-zero
   means every cold start is a new worker.

**Additional risk:** `--mlock` forces page population eagerly. For a 79 GB model on a network
volume, this could serialize and slow down startup vs. on-demand lazy loading.

### Verdict

**Do NOT add `--mlock` to `auto_warmup()` in `install_llama_server.sh`.**

The current approach (parallel `dd` preload via `preload_model()`) achieves the same goal — warm
page cache before llama-server starts — without the risks of `mlock()`.

Re-evaluate if RunPod introduces local NVMe model storage: on NVMe, `--mlock` prevents OS
eviction of pages and could genuinely help repeat-start latency.

### Current `auto_warmup()` Flags (Unchanged)

```
--n-gpu-layers 99    # offload all layers to GPU
--parallel 1         # single request slot (sufficient for single-developer use)
--ctx-size 32768     # 32K context window
--flash-attn on      # FlashAttention2 for memory efficiency
```

### Context Window Policy (96 GB VRAM, IQ4_XS)

For this deployment profile (~61 GiB base model load on RTX Pro 6000 Blackwell 96 GB):

| Tier | Context cap | Intent |
|---|---|---|
| Safe | `100000` | Production default for stable headroom |
| Experimental | `131072` | Upper-limit stress testing only |

Anything above `131072` is rejected by runtime config validation (`nemotron.py`) and should not be benchmarked on this SKU.

Use the built-in limits sweep profile:

```bash
BENCH_PROFILE=limits BENCH_ALLOW_EXPERIMENTAL=1 \
bash scripts/run_humaneval_sweep.sh c1fb77ul6l2dw2
```

---

## Cost of Warmup

### Hardware Rate

| GPU | VRAM | RunPod Serverless Rate |
|---|---|---|
| RTX Pro 6000 Blackwell | 96 GB | **$1.69/hr** |

### Per-Cold-Start Cost

With the optimized 8m45s cold start (~10 min rounded up for full tensor settling):

```
Cost per warmup = $1.69/hr ÷ 60 min/hr × 10 min = $0.28
```

With the baseline 16m30s:

```
Cost per warmup (baseline) = $1.69/hr ÷ 60 × 17 min = $0.48
```

The 4-parallel-stream optimization saves **~$0.20 per cold start**, or **~$17.60/month** at 88
warmups/month.

### Monthly Cost Model

**Assumptions (single developer, AI-assisted coding):**

- 40 h/week × 4.33 weeks = ~173 h/month total coding
- AI utilization: ~35% of coding time → ~60 active AI-session hours/month
- Scale-to-zero pattern: each session start triggers a warmup
- Typical pattern: ~4 cold starts/workday (morning, post-lunch, after breaks/context switches)
- 22 workdays × 4 warmups = **88 warmups/month**

**Warmup overhead by usage pattern:**

| Usage pattern | Warmups/month | Warmup cost/month | Notes |
|---|---|---|---|
| Light (1/day) | 22 | $6.16 | One focused session per workday |
| Typical (4/day) | 88 | **$24.64** | 4 context switches per workday |
| Heavy (8/day) | 176 | $49.28 | Pair programming / frequent context switches |
| Always-on (idle_timeout=∞) | 1 | $0.28 | One boot, never scales to zero |

_All figures use the optimized $0.28/warmup. Add ~72% if still on baseline (16m30s → $0.48/warmup)._

### Monthly Total Cost Estimate

At **typical (4/day)** usage and `idle_timeout=1800` (30 min):

| Line item | Est. hours/month | Cost/month |
|---|---|---|
| Warmup overhead (88 × 10 min) | ~14.7 h | $24.64 |
| Active inference GPU-seconds | ~60 h × 35% utilization = ~21 h | ~$35.49 |
| Idle time within sessions (endpoint warm but idle) | ~39 h | ~$65.91 |
| **Total (typical, scale-to-zero)** | — | **~$126/month** |

> Idle time is the dominant cost when `idle_timeout` is high. Tune `idle_timeout` aggressively
> (300–1800 s) to minimize idle billing while staying within a single session.

### Break-Even: Scale-to-Zero vs Always-On

For a full 9-hour workday:

| Mode | Daily cost | Monthly (22 days) |
|---|---|---|
| Always-on (9h continuous) | 9 × $1.69 = **$15.21/day** | **$334.62/month** |
| Scale-to-zero, 4 warmups | 4 × $0.28 + inference ≈ **$1.12/day** (warmup only) | **~$25/month** (warmup only) |

**Scale-to-zero wins decisively** unless the endpoint runs continuous inference for most of the
workday. Even at 8 warmups/day ($2.24/day warmup cost), scale-to-zero is far cheaper than
always-on for a single developer.

### Recommended `idle_timeout` Values

| `idle_timeout` | Scenario | Notes |
|---|---|---|
| `300` (5 min) | Aggressive scale-to-zero; sporadic use | Cheapest for infrequent sessions |
| `3600` (1 h) | Focused coding session | Stays warm within a 1h block; scales down between sessions |
| `28800` (8 h) | Workday-long session | One warmup per day; $15.21/day if endpoint stays idle |

Current setting in `nemotron.py`: `idle_timeout=1800` (30 min) — reasonable default for a
developer who works in 30-min focused blocks with breaks.

### Summary

- Optimized cold start: **~8m45s**, **$0.28/warmup**
- Baseline cold start: **~16m30s**, **$0.48/warmup**
- Typical monthly warmup overhead (4/day): **$24.64/month**
- Monthly total at typical usage: **~$126/month** (dominated by idle time, not warmup)
- Always-on comparison: **$334/month** — scale-to-zero wins for single-developer use
