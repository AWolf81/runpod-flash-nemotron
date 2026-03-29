#!/usr/bin/env python3
"""
humaneval.py - HumanEval pass@1 benchmark for Nemotron endpoints.

Runs a subset (or all 164) HumanEval problems against an OpenAI-compatible
endpoint and reports pass@1 accuracy plus generation speed.

Defaults are tuned for this repo's IQ4 deployment and can be overridden via
CLI args or env vars.

Resolution order:
  endpoint: --endpoint > NEMOTRON_BENCH_ENDPOINT > NEMOTRON_ENDPOINT > default
  model   : --model > NEMOTRON_BENCH_MODEL > NEMOTRON_MODEL > default

Usage:
  python scripts/humaneval.py
  python scripts/humaneval.py --n 164
  python scripts/humaneval.py --workers 2 --label p2-ctx24k
  NEMOTRON_BENCH_MODEL=nemotron-super-120b-q4 python scripts/humaneval.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = REPO_ROOT / "docs" / "benchmarks"
DEFAULT_SUMMARY_MD = BENCHMARK_DIR / "humaneval-summary.md"
DEFAULT_ENDPOINT = "https://c1fb77ul6l2dw2.api.runpod.ai"
DEFAULT_MODEL = "nemotron-super-120b-iq4"


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


def short_text(text: str, max_chars: int) -> str:
    text = (text or "").strip().replace("\r\n", "\n")
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."


def ensure_output_path(args: argparse.Namespace, model: str) -> Path:
    if args.output:
        return Path(args.output)
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return BENCHMARK_DIR / f"humaneval-{sanitize_slug(model)}-{ts}.json"


def strip_fences(completion: str) -> str:
    """Strip markdown fences if the model adds them."""
    lines = completion.splitlines()
    cleaned = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            cleaned.append(line)
    return "\n".join(cleaned)


def classify_checker_failure(message: str) -> str:
    m = (message or "").lower()
    if "timed out" in m:
        return "checker_timeout"
    if "failed" in m or "assert" in m:
        return "checker_assertion"
    if m:
        return "checker_error"
    return "checker_fail"


def get_completion(client, prompt: str, model: str, max_tokens: int) -> dict[str, Any]:
    t0 = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert Python programmer. "
                    "Complete the function body exactly as asked. "
                    "Output ONLY raw Python code with no markdown fences and no explanation."
                ),
            },
            {"role": "user", "content": f"Complete this Python function:\n\n{prompt}"},
        ],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    elapsed = time.monotonic() - t0

    choice = response.choices[0]
    content = choice.message.content or ""

    usage = response.usage
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
    total_tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage else 0

    tok_s = 0.0
    if elapsed > 0 and completion_tokens > 0:
        tok_s = completion_tokens / elapsed

    return {
        "text": content,
        "latency_s": elapsed,
        "tok_s": tok_s,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "finish_reason": choice.finish_reason,
    }


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


def build_failure_summary(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_type = Counter()
    by_reason = Counter()

    for r in results.values():
        if r.get("passed"):
            continue
        failure_type = r.get("failure_type") or "unknown"
        by_type[failure_type] += 1

        reason = (r.get("error") or r.get("checker_result") or "unknown").strip()
        reason = short_text(reason.replace("\n", " "), 180)
        by_reason[reason] += 1

    return {
        "by_type": dict(by_type),
        "top_reasons": [{"reason": reason, "count": count} for reason, count in by_reason.most_common(8)],
    }


def md_escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


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

    failed_tasks = [t["task_id"] for t in run.get("failed_tasks", [])]
    failed_preview = ", ".join(failed_tasks[:3]) if failed_tasks else "-"
    if len(failed_tasks) > 3:
        failed_preview = f"{failed_preview}, +{len(failed_tasks) - 3}"

    line = (
        "| {timestamp} | {label} | `{model}` | `{endpoint}` | {runtime} | {n} | {passed} "
        "| {pass_pct:.1f}% | {tok_s:.1f} | {lat_s:.2f}s | {failed} | [{json_name}]({json_path}) |\n"
    ).format(
        timestamp=md_escape(run["timestamp_utc"]),
        label=md_escape(run.get("label") or "-"),
        model=md_escape(run["model"]),
        endpoint=md_escape(run.get("endpoint_id") or "-"),
        runtime=md_escape(runtime_label),
        n=run["n_problems"],
        passed=run["passed"],
        pass_pct=run["pass_at_1_pct"],
        tok_s=run["avg_tok_s"],
        lat_s=run["avg_latency_s"],
        failed=md_escape(failed_preview),
        json_name=md_escape(Path(output_ref).name),
        json_path=md_escape(output_ref),
    )

    if not summary_path.exists():
        summary_path.write_text(
            "# HumanEval Benchmark Summary\n\n"
            "Generated by `scripts/humaneval.py`. One row per benchmark run.\n\n"
            "| Timestamp (UTC) | Label | Model | Endpoint ID | Runtime | n | Passed | pass@1 | avg tok/s | avg latency | Failed tasks | JSON |\n"
            "|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|\n"
            f"{line}"
        )
        return

    with summary_path.open("a") as f:
        f.write(line)


def run_humaneval(args: argparse.Namespace) -> int:
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

    api_key = os.environ.get("RUNPOD_API_KEY", "")
    output_path = ensure_output_path(args, model)
    summary_path = Path(args.summary_md) if args.summary_md else None

    try:
        from openai import OpenAI
    except ImportError:
        print("Error: openai package not installed. Run: pip install openai", file=sys.stderr)
        return 2

    try:
        from human_eval.data import read_problems
        from human_eval.execution import check_correctness
    except ImportError:
        print(
            "Error: human-eval package not installed.\n"
            "Run: pip install human-eval\n"
            "  or: pip install git+https://github.com/openai/human-eval.git",
            file=sys.stderr,
        )
        return 2

    client = OpenAI(api_key=api_key or "dummy", base_url=f"{endpoint}/v1")

    problems = read_problems()
    task_ids = list(problems.keys())
    if args.n < len(task_ids):
        task_ids = task_ids[: args.n]

    run_label = args.label or os.environ.get("NEMOTRON_BENCH_LABEL", "").strip()
    runtime_cfg = fetch_runtime_config(endpoint, api_key)

    print("HumanEval benchmark")
    print(f"  endpoint : {endpoint} ({endpoint_source})")
    print(f"  model    : {model} ({model_source})")
    if run_label:
        print(f"  label    : {run_label}")
    if runtime_cfg:
        print(f"  runtime  : {runtime_cfg}")
    print(f"  problems : {len(task_ids)} / 164")
    print(f"  workers  : {args.workers}")
    print(f"  timeout  : {args.timeout}s per problem")
    print()

    results: dict[str, dict[str, Any]] = {}

    def solve(task_id: str) -> tuple[str, dict[str, Any]]:
        problem = problems[task_id]

        try:
            completion = get_completion(client, problem["prompt"], model, args.max_tokens)
            solution = strip_fences(completion["text"])
            checker = check_correctness(problem, solution, timeout=args.timeout)
            checker_result = str(checker.get("result", ""))
            passed = bool(checker.get("passed"))

            if passed:
                failure_type = None
                error = None
            else:
                failure_type = classify_checker_failure(checker_result)
                error = checker_result

            return task_id, {
                "passed": passed,
                "failure_type": failure_type,
                "error": error,
                "checker_result": checker_result,
                "completion": completion["text"],
                "completion_preview": short_text(completion["text"], args.preview_chars),
                "tok_s": completion["tok_s"],
                "latency_s": completion["latency_s"],
                "prompt_tokens": completion["prompt_tokens"],
                "completion_tokens": completion["completion_tokens"],
                "total_tokens": completion["total_tokens"],
                "finish_reason": completion["finish_reason"],
            }

        except Exception as e:
            return task_id, {
                "passed": False,
                "failure_type": "request_error",
                "error": f"{e.__class__.__name__}: {e}",
                "checker_result": "",
                "completion_preview": "",
                "tok_s": 0.0,
                "latency_s": 0.0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "finish_reason": None,
            }

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(solve, tid): tid for tid in task_ids}
        for future in as_completed(futures):
            task_id, result = future.result()
            results[task_id] = result
            completed += 1

            status = "PASS" if result["passed"] else "FAIL"
            tok_s = result["tok_s"]
            line = f"  [{completed:3d}/{len(task_ids)}] {task_id:<20s} {status}  {tok_s:5.1f} tok/s"
            if not result["passed"] and result.get("failure_type"):
                line += f"  ({result['failure_type']})"
            print(line)

    ordered_results = {tid: results[tid] for tid in task_ids}

    passed = sum(1 for r in ordered_results.values() if r["passed"])
    total = len(ordered_results)
    pass_at_1 = (passed / total * 100) if total else 0.0

    tok_s_vals = [r["tok_s"] for r in ordered_results.values() if r["tok_s"] > 0]
    avg_tok_s = (sum(tok_s_vals) / len(tok_s_vals)) if tok_s_vals else 0.0

    latency_vals = [r["latency_s"] for r in ordered_results.values() if r["latency_s"] > 0]
    avg_latency_s = (sum(latency_vals) / len(latency_vals)) if latency_vals else 0.0

    failed_tasks = []
    for task_id, r in ordered_results.items():
        if r["passed"]:
            continue
        failed_tasks.append(
            {
                "task_id": task_id,
                "failure_type": r.get("failure_type") or "unknown",
                "error": r.get("error") or "",
                "checker_result": r.get("checker_result") or "",
                "completion": r.get("completion") or "",
                "completion_preview": r.get("completion_preview") or "",
            }
        )

    print()
    print(f"=== HumanEval Results (n={total}) ===")
    print()
    print(f"  pass@1        : {passed}/{total}  ({pass_at_1:.1f}%)")
    print(f"  avg gen speed : {avg_tok_s:.1f} tok/s")
    print(f"  avg latency   : {avg_latency_s:.2f} s")
    print()

    if args.failures and failed_tasks:
        print(f"Failed problems ({len(failed_tasks)}):")
        for item in failed_tasks:
            reason = item["error"] or item["checker_result"]
            print(f"  {item['task_id']}: {item['failure_type']} - {short_text(reason, 220)}")
        print()

    run_data = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "endpoint_id": extract_endpoint_id(endpoint),
        "endpoint_source": endpoint_source,
        "model": model,
        "model_source": model_source,
        "label": run_label,
        "runtime_config": runtime_cfg,
        "n_problems": total,
        "passed": passed,
        "pass_at_1_pct": round(pass_at_1, 2),
        "avg_tok_s": round(avg_tok_s, 2),
        "avg_latency_s": round(avg_latency_s, 3),
        "workers": args.workers,
        "max_tokens": args.max_tokens,
        "timeout_s": args.timeout,
        "failure_summary": build_failure_summary(ordered_results),
        "failed_tasks": failed_tasks,
        "results": ordered_results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(run_data, indent=2))
    print(f"Full results written to: {output_path}")

    if summary_path is not None:
        update_summary_markdown(summary_path, run_data, output_path)
        print(f"Summary updated at: {summary_path}")

    return 0 if passed == total else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="HumanEval pass@1 benchmark for Nemotron endpoint")
    parser.add_argument("--n", type=int, default=20, help="Number of problems to run (default: 20, max: 164)")
    parser.add_argument("--workers", type=int, default=1, help="Parallel request workers (default: 1)")
    parser.add_argument("--max-tokens", type=int, default=512, help="Max tokens per completion (default: 512)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Execution timeout per problem in seconds")
    parser.add_argument("--endpoint", type=str, default="", help="Override endpoint URL")
    parser.add_argument("--model", type=str, default="", help="Override model id")
    parser.add_argument("--label", type=str, default="", help="Run label (e.g. p2-ctx24k)")
    parser.add_argument("--preview-chars", type=int, default=360, help="Chars to keep for completion preview in JSON")
    parser.add_argument("--failures", action="store_true", help="Print failed problem details at the end")
    parser.add_argument("--output", type=str, default="", help="Write JSON results (default: auto in docs/benchmarks)")
    parser.add_argument(
        "--summary-md",
        type=str,
        default=str(DEFAULT_SUMMARY_MD),
        help="Append a row to summary markdown (set empty string to disable)",
    )
    args = parser.parse_args()

    args.n = max(1, min(args.n, 164))
    args.preview_chars = max(80, args.preview_chars)

    sys.exit(run_humaneval(args))


if __name__ == "__main__":
    main()
