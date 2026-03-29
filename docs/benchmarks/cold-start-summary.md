# Cold Start Summary

Generated: `2026-03-29T16:57:44.612124+00:00`

Source: `warmup.sh` logs (`docs/benchmarks/warmup-*.log`).
Duration is the final `[XmYs]` marker before `Ready and stable`.

## All Ready Runs

- samples: **22**
- min: **22s** (00:22)
- max: **492s** (08:12)
- avg: **119.6s** (02:00)
- median: **92.0s**

## Benchmark-Labeled Runs (excluding `probe-*` and `verify-*`)

- samples: **17**
- min: **22s** (00:22)
- max: **329s** (05:29)
- avg: **103.8s** (01:44)
- median: **89.0s**

## Per Run

| Log | Label | Ready | Time (s) | Time (mm:ss) |
|---|---|---|---:|---:|
| `docs/benchmarks/warmup-p1-ctx100k-safe-2026-03-29-172128.log` | `p1-ctx100k-safe` | yes | 22 | 00:22 |
| `docs/benchmarks/warmup-p1-ctx131072-exp-2026-03-29-174319.log` | `p1-ctx131072-exp` | yes | 22 | 00:22 |
| `docs/benchmarks/warmup-p1-ctx131072-exp-2026-03-29-175212.log` | `p1-ctx131072-exp` | yes | 22 | 00:22 |
| `docs/benchmarks/warmup-p2-ctx100k-safe-w2-2026-03-29-180457.log` | `p2-ctx100k-safe-w2` | yes | 22 | 00:22 |
| `docs/benchmarks/warmup-p2-ctx32768-2026-03-29-170541.log` | `p2-ctx32768` | yes | 22 | 00:22 |
| `docs/benchmarks/warmup-verify-gate-2026-03-29-171028.log` | `verify-gate` | yes | 22 | 00:22 |
| `docs/benchmarks/warmup-p2-ctx16384-2026-03-29-171615.log` | `p2-ctx16384` | yes | 23 | 00:23 |
| `docs/benchmarks/warmup-p2-ctx24576-2026-03-29-170933.log` | `p2-ctx24576` | yes | 23 | 00:23 |
| `docs/benchmarks/warmup-p1-ctx32768-2026-03-29-165249.log` | `p1-ctx32768` | yes | 32 | 00:32 |
| `docs/benchmarks/warmup-probe-p2-ctx100k-w2-2026-03-29-181044.log` | `probe-p2-ctx100k-w2` | yes | 80 | 01:20 |
| `docs/benchmarks/warmup-p2-ctx100k-safe-w2-2026-03-29-174607.log` | `p2-ctx100k-safe-w2` | yes | 89 | 01:29 |
| `docs/benchmarks/warmup-p1-ctx100k-safe-2026-03-29-173641.log` | `p1-ctx100k-safe` | yes | 95 | 01:35 |
| `docs/benchmarks/warmup-probe-p1-131072-2026-03-29-174903.log` | `probe-p1-131072` | yes | 117 | 01:57 |
| `docs/benchmarks/warmup-p1-ctx32768-2026-03-29-183056.log` | `p1-ctx32768` | yes | 123 | 02:03 |
| `docs/benchmarks/warmup-probe-p2-ctx100k-w2-2026-03-29-180636.log` | `probe-p2-ctx100k-w2` | yes | 157 | 02:37 |
| `docs/benchmarks/warmup-p2-ctx100k-safe-w2-2026-03-29-181315.log` | `p2-ctx100k-safe-w2` | yes | 176 | 02:56 |
| `docs/benchmarks/warmup-p2-ctx100k-1worker-2026-03-29-183759.log` | `p2-ctx100k-1worker` | yes | 178 | 02:58 |
| `docs/benchmarks/warmup-p1-ctx32768-2026-03-29-182950.log` | `p1-ctx32768` | yes | 188 | 03:08 |
| `docs/benchmarks/warmup-p1-ctx32768-2026-03-29-164954.log` | `p1-ctx32768` | yes | 198 | 03:18 |
| `docs/benchmarks/warmup-p2-ctx100k-safe-w4-trigger4-2026-03-29-182551.log` | `p2-ctx100k-safe-w4-trigger4` | yes | 200 | 03:20 |
| `docs/benchmarks/warmup-p2-ctx100k-safe-w2-final-2026-03-29-183517.log` | `p2-ctx100k-safe-w2-final` | yes | 329 | 05:29 |
| `docs/benchmarks/warmup-probe-p1-100k-2026-03-29-172617.log` | `probe-p1-100k` | yes | 492 | 08:12 |
