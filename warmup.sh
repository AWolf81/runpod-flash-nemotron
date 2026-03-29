#!/usr/bin/env bash
# warmup.sh — minimal warmup flow with stable-ready gating.
#
# Usage:
#   bash warmup.sh [endpoint-id|endpoint-url]
# Env:
#   RUNPOD_API_KEY=...
#   NEMOTRON_ENDPOINT=https://<id>.api.runpod.ai
#   WARMUP_RECYCLE_ON_START=1      # default 1 (force 0->1 rollout)
#   WARMUP_READY_STABLE_POLLS=3    # default 3 consecutive ready polls
#   WARMUP_POLL_INTERVAL=10        # seconds

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNPOD_REST_API="https://rest.runpod.io/v1"
RUNPOD_V2_API="https://api.runpod.ai/v2"
DEFAULT_ENDPOINT_ID="c1fb77ul6l2dw2"
POLL_INTERVAL="${WARMUP_POLL_INTERVAL:-10}"
READY_STABLE_POLLS="${WARMUP_READY_STABLE_POLLS:-3}"
MAX_WORKERS="${WARMUP_MAX_WORKERS:-2}"
WARMUP_LOG_FILE="${WARMUP_LOG_FILE:-}"
LOG_EVERY_POLLS="${WARMUP_LOG_EVERY_POLLS:-3}"
VERBOSE_COUNTS="${WARMUP_VERBOSE_COUNTS:-0}"

extract_endpoint_id() {
    local raw="$1"
    raw="${raw#http://}"
    raw="${raw#https://}"
    raw="${raw%%/*}"
    raw="${raw%%.api.runpod.ai}"
    echo "${raw}"
}

if [[ -z "${RUNPOD_API_KEY:-}" ]] && [[ -f "${SCRIPT_DIR}/.env" ]]; then
    # shellcheck source=.env
    set -a; source "${SCRIPT_DIR}/.env"; set +a
fi

_manifest_endpoint="$(python3 -c '
import json,sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
    eps = d.get("resources_endpoints") or {}
    print(eps.get("gpu_api") or next(iter(eps.values()), ""))
except Exception:
    print("")
' "${SCRIPT_DIR}/.flash/flash_manifest.json" 2>/dev/null || true)"
_endpoint_input="${1:-${NEMOTRON_ENDPOINT:-${_manifest_endpoint:-${DEFAULT_ENDPOINT_ID}}}}"
ENDPOINT_ID="$(extract_endpoint_id "${_endpoint_input}")"
ENDPOINT="https://${ENDPOINT_ID}.api.runpod.ai"

if [[ -z "${RUNPOD_API_KEY:-}" ]]; then
    echo "Error: RUNPOD_API_KEY is not set."
    exit 1
fi

log() {
    local msg="$*"
    echo "${msg}"
    if [[ -n "${WARMUP_LOG_FILE}" ]]; then
        echo "${msg}" >> "${WARMUP_LOG_FILE}"
    fi
}

fetch_worker_counts() {
    local counts
    counts="$( (curl -sS --connect-timeout 5 --max-time 6 "${RUNPOD_V2_API}/${ENDPOINT_ID}/health" \
        -H "Authorization: Bearer ${RUNPOD_API_KEY}" 2>/dev/null || true) \
        | python3 -c '
import json,sys
try:
    w=(json.load(sys.stdin).get("workers") or {})
    print(
        f"{int(w.get('ready', 0))} "
        f"{int(w.get('initializing', 0))} "
        f"{int(w.get('running', 0))} "
        f"{int(w.get('unhealthy', 0))}"
    )
except Exception:
    print("0 0 0 0")
')"
    [[ -n "${counts}" ]] || counts="0 0 0 0"
    echo "${counts}"
}

scale() {
    local min=$1 max=$2
    local result
    result="$(curl -sS --connect-timeout 5 --max-time 20 -X PATCH "${RUNPOD_REST_API}/endpoints/${ENDPOINT_ID}" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
        -d "{\"workersMin\": ${min}, \"workersMax\": ${max}}")"
    local actual_min actual_max
    actual_min="$(echo "${result}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("workersMin","?"))' 2>/dev/null || echo "?")"
    actual_max="$(echo "${result}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("workersMax","?"))' 2>/dev/null || echo "?")"
    log "    workers: min=${actual_min} max=${actual_max}"
}

_scaled_down=false
scale_down() {
    [[ "${_scaled_down}" == "true" ]] && return
    _scaled_down=true
    log ""
    log "==> Scaling down to 0 workers..."
    scale 0 "${MAX_WORKERS}" || true
    log "==> Scaled down."
}
trap scale_down INT TERM EXIT

if [[ -n "${WARMUP_LOG_FILE}" ]]; then
    mkdir -p "$(dirname "${WARMUP_LOG_FILE}")"
fi

log "==> Target endpoint: ${ENDPOINT}"
if [[ "${WARMUP_RECYCLE_ON_START:-1}" == "1" ]]; then
    log "==> Recycling workers (0 -> 1)..."
    scale 0 "${MAX_WORKERS}"
    sleep 2
fi
log "==> Scaling up to 1 worker..."
scale 1 "${MAX_WORKERS}"

log "==> Waiting for stable ready..."
ready_streak=0
warmup_sent=false
last_warmup_code=""
_wait_start=$(date +%s)
last_status="(init)"
poll_counter=0

while true; do
    poll_counter=$((poll_counter + 1))
    read -r w_ready w_init w_run w_unhealthy < <(fetch_worker_counts)
    status="$( (curl -sS --connect-timeout 5 --max-time 25 "${ENDPOINT}/health" \
        -H "Authorization: Bearer ${RUNPOD_API_KEY}" 2>/dev/null || true) \
        | python3 -c '
import json,sys
try:
    print(json.load(sys.stdin).get("status", "starting"))
except Exception:
    print("starting")
')"
    [[ -n "${status}" ]] || status="starting"
    [[ "${status}" == "unknown" ]] && status="starting"

    if [[ "${warmup_sent}" == "false" && "${status}" == "cold" ]]; then
        log "    $(date +%H:%M:%S) — triggering warmup..."
        warmup_code="$(curl -sS --connect-timeout 5 --max-time 25 -o /dev/null -w "%{http_code}" -X POST "${ENDPOINT}/warmup" \
            -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
            -H "Content-Type: application/json" \
            -d '{}' 2>/dev/null || true)"
        if [[ "${warmup_code}" == "200" ]]; then
            warmup_sent=true
            last_warmup_code=""
        else
            if [[ "${warmup_code:-000}" != "${last_warmup_code}" ]]; then
                log "    $(date +%H:%M:%S) — warmup pending (HTTP ${warmup_code:-000}), will retry"
                last_warmup_code="${warmup_code:-000}"
            fi
        fi
    fi

    if [[ "${status}" == "ready" ]]; then
        ready_streak=$((ready_streak + 1))
    else
        ready_streak=0
    fi

    status_display="${status}"
    if [[ "${status}" == "starting" ]]; then
        if (( w_ready > 0 )); then
            status_display="starting (LB pending; workers ready=${w_ready})"
        elif (( w_init > 0 || w_run > 0 )); then
            status_display="starting (workers init=${w_init} run=${w_run})"
        fi
    fi

    _elapsed=$(( $(date +%s) - _wait_start ))
    _elapsed_fmt=$(printf "%dm%02ds" $(( _elapsed / 60 )) $(( _elapsed % 60 )))
    should_log=false
    if [[ "${status_display}" != "${last_status}" ]]; then
        should_log=true
    elif (( poll_counter % LOG_EVERY_POLLS == 0 )); then
        should_log=true
    fi

    if [[ "${should_log}" == "true" ]]; then
        if [[ "${VERBOSE_COUNTS}" == "1" ]]; then
            log "    $(date +%H:%M:%S) [${_elapsed_fmt}] — ${status_display} (workers ready=${w_ready} init=${w_init} run=${w_run} unhealthy=${w_unhealthy})"
        else
            log "    $(date +%H:%M:%S) [${_elapsed_fmt}] — ${status_display}"
        fi
    fi
    if [[ "${status_display}" != "${last_status}" ]]; then
        log "    $(date +%H:%M:%S) — status change: ${last_status} -> ${status_display}"
        last_status="${status_display}"
    fi

    if [[ "${status}" == "ready" && ${ready_streak} -lt ${READY_STABLE_POLLS} ]]; then
        log "    $(date +%H:%M:%S) — ready candidate (${ready_streak}/${READY_STABLE_POLLS})"
    fi
    if [[ "${status}" == "ready" && ${ready_streak} -ge ${READY_STABLE_POLLS} ]]; then
        log ""
        log "==> Ready and stable."
        log "    Keep this terminal open; Ctrl+C scales down to 0 workers."
        break
    fi
    if [[ "${status}" != "ready" ]]; then
        # Protect against premature scale-to-zero while model is loading.
        curl -sS --connect-timeout 5 --max-time 10 -X POST "${ENDPOINT}/keepalive" \
            -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
            -H "Content-Type: application/json" \
            -d '{}' > /dev/null 2>&1 || true
    fi

    sleep "${POLL_INTERVAL}"
done

while true; do
    sleep 30
done
