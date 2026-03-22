# Nemotron Endpoint Benchmarks

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
