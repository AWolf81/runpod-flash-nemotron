#!/usr/bin/env bash
# bench.sh — Benchmark the Nemotron endpoint.
#
# Fires N sequential requests and prints per-run timings plus aggregate stats.
#
# Usage:
#   bash scripts/bench.sh                    # 20 requests, loads .env
#   bash scripts/bench.sh 40                 # 40 requests
#   RUNPOD_API_KEY=rp_... bash scripts/bench.sh

set -euo pipefail

# Load .env from repo root if RUNPOD_API_KEY is not already set
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -z "${RUNPOD_API_KEY:-}" ]] && [[ -f "${SCRIPT_DIR}/../.env" ]]; then
    set -a; source "${SCRIPT_DIR}/../.env"; set +a
fi

if [[ -z "${RUNPOD_API_KEY:-}" ]]; then
    echo "Error: RUNPOD_API_KEY is not set." >&2
    echo "Usage: RUNPOD_API_KEY=rp_... bash scripts/bench.sh [N]" >&2
    exit 1
fi

N=${1:-20}
ENDPOINT="${NEMOTRON_ENDPOINT:-https://hf1ui3wrdsa31u.api.runpod.ai}"

echo "Benchmarking ${ENDPOINT}"
echo "  n=${N}"
echo ""

results=""
for i in $(seq 1 $N); do
    response=$(curl -s --max-time 180 "${ENDPOINT}/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
        -d '{"messages":[{"role":"user","content":"Explain how transformers work in 3 paragraphs"}],"max_tokens":300}')

    row=$(echo "$response" | python3 -c "
import sys, json
raw = sys.stdin.read()
try:
    d = json.loads(raw)
    t = d['timings']
    u = d['usage']
    print(f\"{t['predicted_per_second']:.2f} {t['prompt_per_second']:.2f} {t['predicted_ms']:.0f} {u['completion_tokens']} {u['prompt_tokens']}\")
except Exception as e:
    print(f'ERROR: {e} | response: {raw[:300]}', file=sys.stderr)
" 2>&1)

    if [[ "$row" == ERROR* ]]; then
        echo "  run $i/$N FAILED: $row" >&2
    else
        gen=$(echo "$row" | cut -d' ' -f1)
        echo "  run $i/$N  gen=${gen} tok/s" >&2
        results+="$row"$'\n'
    fi
done

echo "$results" | python3 -c "
import sys, statistics

rows = [line.split() for line in sys.stdin.read().strip().splitlines() if line.strip()]
if not rows:
    print('No successful results.')
    exit(1)

gen   = [float(r[0]) for r in rows]
prompt= [float(r[1]) for r in rows]
lat   = [float(r[2]) for r in rows]
ctoks = [int(r[3]) for r in rows]
ptoks = [int(r[4]) for r in rows]

def stats(label, values, unit=''):
    s = sorted(values)
    n = len(s)
    p = lambda pct: s[min(int(n * pct), n-1)]
    print(f'{label} (n={n}):')
    print(f'  mean={statistics.mean(s):.1f}{unit}  stdev={statistics.stdev(s):.1f}{unit}')
    print(f'  min={s[0]:.1f}{unit}  p50={p(0.50):.1f}{unit}  p75={p(0.75):.1f}{unit}  p90={p(0.90):.1f}{unit}  p99={p(0.99):.1f}{unit}  max={s[-1]:.1f}{unit}')

print(f'\n=== Benchmark Results (n={len(gen)}) ===\n')
stats('Generation speed', gen, ' tok/s')
print()
stats('Prompt speed', prompt, ' tok/s')
print()
stats('Generation latency', lat, ' ms')
print()
print(f'Avg completion tokens: {statistics.mean(ctoks):.0f}')
print(f'Avg prompt tokens:     {statistics.mean(ptoks):.0f}')
"
