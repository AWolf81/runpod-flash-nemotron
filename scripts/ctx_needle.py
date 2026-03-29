#!/usr/bin/env python3
"""
ctx_needle.py - Simple context-size benchmark using a needle-in-haystack task.

Purpose:
- Validate effective context limits for a deployed endpoint/runtime.
- Detect when long-context retrieval begins to degrade.

The script sends long prompts with a single embedded secret key ("needle").
The model must return the key exactly. For each target context size, it reports:
- retrieval pass rate
- exact-match rate
- request errors (often indicates context cap hit)
- latency and prompt token size

Usage examples:
  python scripts/ctx_needle.py --label p2-ctx100k
  python scripts/ctx_needle.py --contexts 32768,65536,90000,100000 --samples 2 --label p2-ctx100k
  python scripts/ctx_needle.py --contexts 32768,65536,100000,115000,130000 --samples 2 --label p1-ctx131072
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = REPO_ROOT / "docs" / "benchmarks"
DEFAULT_SUMMARY_MD = BENCHMARK_DIR / "ctx-needle-summary.md"
DEFAULT_ENDPOINT = "https://c1fb77ul6l2dw2.api.runpod.ai"
DEFAULT_MODEL = "nemotron-super-120b-iq4"

FILLER_LINE = (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron "
    "pi rho sigma tau upsilon phi chi psi omega red blue green yellow orange violet "
    "north south east west one two three four five six seven eight nine ten"
)
APPROX_TOKENS_PER_FILLER_LINE = 42


def load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def resolve_setting(
    arg_value: str,
    bench_env_key: str,
    legacy_env_key: str,
    default_value: str,
) -> tuple[str, str]:
    if arg_value:
        return arg_value, "arg"

    bench_env = os.environ.get(bench_env_key, "").strip()
    if bench_env:
        return bench_env, bench_env_key

    legacy_env = os.environ.get(legacy_env_key, "").strip()
    if legacy_env:
        return legacy_env, legacy_env_key

    return default_value, "default"


def sanitize_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "model"


def extract_endpoint_id(endpoint: str) -> str:
    value = endpoint.strip()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/", 1)[0]
    value = value.removesuffix(".api.runpod.ai")
    return value


def md_escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def parse_contexts(value: str) -> list[int]:
    contexts: list[int] = []
    seen: set[int] = set()
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ctx = int(raw)
        except ValueError as e:
            raise ValueError(f"Invalid context value: {raw}") from e
        if ctx <= 0:
            raise ValueError(f"Context must be > 0: {ctx}")
        if ctx not in seen:
            contexts.append(ctx)
            seen.add(ctx)
    if not contexts:
        raise ValueError("No valid contexts supplied.")
    return contexts


def ensure_output_path(args: argparse.Namespace, model: str) -> Path:
    if args.output:
        return Path(args.output)
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return BENCHMARK_DIR / f"ctx-needle-{sanitize_slug(model)}-{ts}.json"


def fetch_runtime_config(endpoint: str, api_key: str) -> dict[str, Any] | None:
    try:
        import httpx
    except Exception:
        return None

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(f"{endpoint}/admin/debug", headers=headers)
        if r.status_code != 200:
            return {"error": f"admin_debug_http_{r.status_code}"}
        data = r.json()
        cfg = data.get("llama_runtime_config")
        return cfg if isinstance(cfg, dict) else None
    except Exception as e:
        return {"error": f"{e.__class__.__name__}: {e}"}


def build_filler(approx_tokens: int, prefix: str) -> str:
    if approx_tokens <= 0:
        return ""
    line_count = max(1, approx_tokens // APPROX_TOKENS_PER_FILLER_LINE)
    lines = [f"{prefix}-{i:05d}: {FILLER_LINE}" for i in range(line_count)]
    return "\n".join(lines)


def build_prompt(target_ctx: int, needle: str, needle_position: float) -> str:
    # We target an approximate prompt token size. Actual token usage is measured
    # from API response usage.prompt_tokens and reported in results.
    overhead_tokens = 220
    filler_budget = max(512, target_ctx - overhead_tokens)
    pre_tokens = int(filler_budget * needle_position)
    post_tokens = max(0, filler_budget - pre_tokens)

    pre = build_filler(pre_tokens, "pre")
    post = build_filler(post_tokens, "post")

    return (
        "You will receive a long document.\n"
        "Find the exact secret key and reply with ONLY that key.\n"
        "If not found, reply with NOT_FOUND.\n\n"
        "DOCUMENT START\n"
        f"{pre}\n\n"
        "NEEDLE SECTION\n"
        f"The secret key is: {needle}\n"
        "END NEEDLE SECTION\n\n"
        f"{post}\n"
        "DOCUMENT END\n\n"
        "Question: What is the secret key?\n"
        "Answer with only the key."
    )


def summarize_context(
    context_results: list[dict[str, Any]],
    target_ctx: int,
) -> dict[str, Any]:
    sample_count = len(context_results)
    contains_count = sum(1 for r in context_results if r.get("contains_needle"))
    exact_count = sum(1 for r in context_results if r.get("exact_match"))
    request_errors = sum(1 for r in context_results if r.get("error"))

    prompt_tokens = [r["prompt_tokens"] for r in context_results if isinstance(r.get("prompt_tokens"), int)]
    latencies = [r["latency_s"] for r in context_results if isinstance(r.get("latency_s"), (int, float))]
    tok_s_vals = [r["tok_s"] for r in context_results if isinstance(r.get("tok_s"), (int, float))]

    first_error = next((r.get("error") for r in context_results if r.get("error")), "")

    return {
        "target_ctx": target_ctx,
        "samples": sample_count,
        "contains_passed": contains_count,
        "exact_passed": exact_count,
        "contains_pass_pct": round((contains_count / sample_count * 100.0), 1) if sample_count else 0.0,
        "exact_pass_pct": round((exact_count / sample_count * 100.0), 1) if sample_count else 0.0,
        "request_errors": request_errors,
        "avg_prompt_tokens": round(statistics.mean(prompt_tokens), 1) if prompt_tokens else 0.0,
        "avg_latency_s": round(statistics.mean(latencies), 3) if latencies else 0.0,
        "avg_tok_s": round(statistics.mean(tok_s_vals), 2) if tok_s_vals else 0.0,
        "first_error": first_error,
        "cases": context_results,
    }


def add_degradation_notes(
    per_ctx: list[dict[str, Any]],
    exact_drop_pp: float,
    latency_ratio: float,
) -> None:
    baseline: dict[str, Any] | None = None
    for row in per_ctx:
        notes: list[str] = []

        if row["request_errors"] >= row["samples"]:
            notes.append("limit-hit")
        elif row["request_errors"] > 0:
            notes.append("partial-errors")

        if baseline is None and row["request_errors"] < row["samples"]:
            baseline = row
            row["degradation"] = "baseline"
            continue

        if baseline is None:
            row["degradation"] = ", ".join(notes) if notes else "-"
            continue

        exact_drop = baseline["exact_pass_pct"] - row["exact_pass_pct"]
        if exact_drop >= exact_drop_pp:
            notes.append(f"exact-drop-{exact_drop:.1f}pp")

        base_latency = baseline["avg_latency_s"]
        row_latency = row["avg_latency_s"]
        if base_latency > 0 and row_latency > base_latency * latency_ratio:
            notes.append(f"latency-x{row_latency / base_latency:.2f}")

        row["degradation"] = ", ".join(notes) if notes else "-"


def update_summary_markdown(summary_path: Path, run: dict[str, Any], output_path: Path) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.is_absolute():
        try:
            output_ref = output_path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            output_ref = output_path.as_posix()
    else:
        output_ref = output_path.as_posix()

    runtime = run.get("runtime_config") or {}
    if runtime:
        runtime_label = f"p{runtime.get('parallel', '?')}/ctx{runtime.get('ctx_size', '?')}"
    else:
        runtime_label = "-"

    lines: list[str] = []
    for row in run.get("contexts", []):
        lines.append(
            "| {timestamp} | {label} | {runtime} | {target} | {samples} | {contains:.1f}% | {exact:.1f}% "
            "| {prompt:.1f} | {lat:.2f}s | {errors} | {degrade} | [{json_name}]({json_path}) |\n".format(
                timestamp=md_escape(run["timestamp_utc"]),
                label=md_escape(run.get("label") or "-"),
                runtime=md_escape(runtime_label),
                target=row["target_ctx"],
                samples=row["samples"],
                contains=row["contains_pass_pct"],
                exact=row["exact_pass_pct"],
                prompt=row["avg_prompt_tokens"],
                lat=row["avg_latency_s"],
                errors=row["request_errors"],
                degrade=md_escape(row.get("degradation") or "-"),
                json_name=md_escape(Path(output_ref).name),
                json_path=md_escape(output_ref),
            )
        )

    if not summary_path.exists():
        summary_path.write_text(
            "# Context Needle Benchmark Summary\n\n"
            "Generated by `scripts/ctx_needle.py`. One row per context target.\n\n"
            "| Timestamp (UTC) | Label | Runtime | target ctx | samples | contains pass | exact pass | avg prompt toks | avg latency | request errors | degradation | JSON |\n"
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|\n"
            + "".join(lines)
        )
        return

    with summary_path.open("a") as f:
        for line in lines:
            f.write(line)


def run_ctx_needle(args: argparse.Namespace) -> int:
    load_env()

    endpoint, endpoint_source = resolve_setting(
        args.endpoint,
        "NEMOTRON_BENCH_ENDPOINT",
        "NEMOTRON_ENDPOINT",
        DEFAULT_ENDPOINT,
    )
    model, model_source = resolve_setting(
        args.model,
        "NEMOTRON_BENCH_MODEL",
        "NEMOTRON_MODEL",
        DEFAULT_MODEL,
    )
    contexts = parse_contexts(args.contexts)

    api_key = os.environ.get("RUNPOD_API_KEY", "")
    output_path = ensure_output_path(args, model)
    summary_path = Path(args.summary_md) if args.summary_md else None
    run_label = args.label or os.environ.get("NEMOTRON_BENCH_LABEL", "").strip()

    try:
        from openai import OpenAI
    except ImportError:
        print("Error: openai package not installed. Run: pip install openai", file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key or "dummy", base_url=f"{endpoint}/v1", timeout=args.request_timeout)
    runtime_cfg = fetch_runtime_config(endpoint, api_key)

    print("Context needle benchmark")
    print(f"  endpoint        : {endpoint} ({endpoint_source})")
    print(f"  model           : {model} ({model_source})")
    if run_label:
        print(f"  label           : {run_label}")
    if runtime_cfg:
        print(f"  runtime         : {runtime_cfg}")
    print(f"  contexts        : {contexts}")
    print(f"  samples/ctx     : {args.samples}")
    print(f"  needle_position : {args.needle_position:.2f}")
    print()

    all_context_rows: list[dict[str, Any]] = []

    for target_ctx in contexts:
        print(f"=== target ctx {target_ctx} ===")
        ctx_cases: list[dict[str, Any]] = []
        for i in range(1, args.samples + 1):
            needle = f"NEEDLE-{target_ctx}-{i}-{secrets.token_hex(4)}"
            prompt = build_prompt(target_ctx, needle, args.needle_position)

            started = time.monotonic()
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Return only the secret key, with no explanation.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=args.max_tokens,
                    temperature=0.0,
                )
                elapsed = time.monotonic() - started
                text = (response.choices[0].message.content or "").strip()
                usage = response.usage
                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
                completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
                tok_s = (completion_tokens / elapsed) if elapsed > 0 else 0.0
                contains_needle = needle in text
                exact_match = text == needle
                finish_reason = response.choices[0].finish_reason

                status = "PASS" if contains_needle else "FAIL"
                print(
                    f"  [{i}/{args.samples}] {status} "
                    f"prompt={prompt_tokens} tok latency={elapsed:.2f}s finish={finish_reason}"
                )

                ctx_cases.append(
                    {
                        "sample": i,
                        "needle": needle,
                        "response": text,
                        "contains_needle": contains_needle,
                        "exact_match": exact_match,
                        "latency_s": round(elapsed, 3),
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "tok_s": round(tok_s, 2),
                        "finish_reason": finish_reason,
                        "error": "",
                    }
                )
            except Exception as e:
                elapsed = time.monotonic() - started
                err = f"{e.__class__.__name__}: {e}"
                print(f"  [{i}/{args.samples}] ERROR latency={elapsed:.2f}s {err}")
                ctx_cases.append(
                    {
                        "sample": i,
                        "needle": needle,
                        "response": "",
                        "contains_needle": False,
                        "exact_match": False,
                        "latency_s": round(elapsed, 3),
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "tok_s": 0.0,
                        "finish_reason": None,
                        "error": err,
                    }
                )

        row = summarize_context(ctx_cases, target_ctx)
        all_context_rows.append(row)
        print(
            "  summary:"
            f" contains={row['contains_passed']}/{row['samples']} ({row['contains_pass_pct']:.1f}%),"
            f" exact={row['exact_passed']}/{row['samples']} ({row['exact_pass_pct']:.1f}%),"
            f" errors={row['request_errors']},"
            f" avg_prompt={row['avg_prompt_tokens']:.1f},"
            f" avg_latency={row['avg_latency_s']:.2f}s"
        )
        print()

    add_degradation_notes(
        all_context_rows,
        exact_drop_pp=args.degradation_exact_drop_pp,
        latency_ratio=args.degradation_latency_ratio,
    )

    print("=== Context Sweep Summary ===")
    for row in all_context_rows:
        print(
            f"  ctx={row['target_ctx']:>6d} "
            f"contains={row['contains_pass_pct']:>5.1f}% "
            f"exact={row['exact_pass_pct']:>5.1f}% "
            f"prompt={row['avg_prompt_tokens']:>8.1f} "
            f"lat={row['avg_latency_s']:>6.2f}s "
            f"errors={row['request_errors']:>2d} "
            f"note={row.get('degradation', '-')}"
        )

    run_data = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "endpoint_id": extract_endpoint_id(endpoint),
        "endpoint_source": endpoint_source,
        "model": model,
        "model_source": model_source,
        "label": run_label,
        "runtime_config": runtime_cfg,
        "samples_per_context": args.samples,
        "contexts_requested": contexts,
        "needle_position": args.needle_position,
        "max_tokens": args.max_tokens,
        "request_timeout_s": args.request_timeout,
        "degradation_exact_drop_pp": args.degradation_exact_drop_pp,
        "degradation_latency_ratio": args.degradation_latency_ratio,
        "contexts": all_context_rows,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(run_data, indent=2))
    print()
    print(f"Full results written to: {output_path}")

    if summary_path is not None:
        update_summary_markdown(summary_path, run_data, output_path)
        print(f"Summary updated at: {summary_path}")

    # Exit non-zero if every context failed (fully unusable benchmark run).
    if all(row["request_errors"] >= row["samples"] for row in all_context_rows):
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple context-size benchmark using needle-in-haystack retrieval.")
    parser.add_argument(
        "--contexts",
        type=str,
        default="32768,65536,90000,100000,115000,130000",
        help="Comma-separated target context sizes (approx prompt tokens).",
    )
    parser.add_argument("--samples", type=int, default=2, help="Requests per context size (default: 2).")
    parser.add_argument(
        "--needle-position",
        type=float,
        default=0.85,
        help="Needle insertion position in filler [0.0..1.0] (default: 0.85).",
    )
    parser.add_argument("--max-tokens", type=int, default=32, help="Max completion tokens (default: 32).")
    parser.add_argument("--request-timeout", type=float, default=180.0, help="HTTP request timeout seconds.")
    parser.add_argument("--endpoint", type=str, default="", help="Override endpoint URL.")
    parser.add_argument("--model", type=str, default="", help="Override model id.")
    parser.add_argument("--label", type=str, default="", help="Run label (e.g. p2-ctx100k).")
    parser.add_argument(
        "--degradation-exact-drop-pp",
        type=float,
        default=20.0,
        help="Flag degradation if exact-match drops by at least this many percentage points vs baseline.",
    )
    parser.add_argument(
        "--degradation-latency-ratio",
        type=float,
        default=2.0,
        help="Flag degradation if latency exceeds baseline by this factor.",
    )
    parser.add_argument("--output", type=str, default="", help="Write JSON results (default: auto in docs/benchmarks).")
    parser.add_argument(
        "--summary-md",
        type=str,
        default=str(DEFAULT_SUMMARY_MD),
        help="Append per-context rows to markdown summary (set empty string to disable).",
    )
    args = parser.parse_args()

    args.samples = max(1, args.samples)
    args.needle_position = min(1.0, max(0.0, args.needle_position))
    args.max_tokens = max(4, args.max_tokens)
    args.request_timeout = max(5.0, args.request_timeout)

    sys.exit(run_ctx_needle(args))


if __name__ == "__main__":
    main()
