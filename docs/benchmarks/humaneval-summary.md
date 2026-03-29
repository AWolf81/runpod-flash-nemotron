# HumanEval Benchmark Summary

Curated benchmark rows used for decisions.  
Raw per-run artifacts remain in `docs/benchmarks/humaneval-*.json`.

| Timestamp (UTC) | Label | Model | Endpoint ID | Runtime | n | Passed | pass@1 | avg tok/s | avg latency | Failed tasks | JSON |
|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|
| 2026-03-29T15:51:44.485234+00:00 | probe-p1-131072 | `nemotron-super-120b-iq4` | `c1fb77ul6l2dw2` | p1/ctx131072 | 1 | 1 | 100.0% | 26.2 | 14.08s | - | [humaneval-nemotron-super-120b-iq4-2026-03-29-175129.json](docs/benchmarks/humaneval-nemotron-super-120b-iq4-2026-03-29-175129.json) |
| 2026-03-29T17:56:14.165076+00:00 | p2-ctx100k-fixed | `nemotron-super-120b-iq4` | `c1fb77ul6l2dw2` | p2/ctx100000 | 20 | 16 | 80.0% | 77.7 | 4.30s | HumanEval/1, HumanEval/3, HumanEval/10, +1 | [humaneval-nemotron-super-120b-iq4-2026-03-29-195447.json](docs/benchmarks/humaneval-nemotron-super-120b-iq4-2026-03-29-195447.json) |
| 2026-03-29T19:44:08.333007+00:00 | p2-ctx100k-n32 | `nemotron-super-120b-iq4` | `c1fb77ul6l2dw2` | p2/ctx100000 | 32 | 28 | 87.5% | 56.4 | 5.50s | HumanEval/1, HumanEval/3, HumanEval/10, +1 | [humaneval-nemotron-super-120b-iq4-2026-03-29-214110.json](docs/benchmarks/humaneval-nemotron-super-120b-iq4-2026-03-29-214110.json) |
| 2026-03-29T18:13:51.070303+00:00 | **p2-ctx100k-full** ★ | `nemotron-super-120b-iq4` | `c1fb77ul6l2dw2` | p2/ctx100000 | **164** | **95** | **57.9%** | 78.9 | 4.93s | HumanEval/1, HumanEval/3, HumanEval/10, +66 | [humaneval-nemotron-super-120b-iq4-2026-03-29-200017.json](docs/benchmarks/humaneval-nemotron-super-120b-iq4-2026-03-29-200017.json) |

## Notes

- **Primary HumanEval baseline**: `p2-ctx100k-full` (2026-03-29), **57.9% pass@1 on 164**.
- **Fixed-eval-code reference run**: `p2-ctx100k-fixed` (2026-03-29) at `n=20`.
- **Context-window viability check**: `probe-p1-131072` confirms requests run at `p1/ctx131072`.
- **Quick comparability point (`n=32`)**: `p2-ctx100k-n32` scored **87.5% (28/32)** on 2026-03-29.
- For context-limit and long-context degradation tracking, use `scripts/ctx_needle.py` and `docs/benchmarks/ctx-needle-summary.md` instead of HumanEval.
