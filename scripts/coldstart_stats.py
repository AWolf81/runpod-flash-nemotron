#!/usr/bin/env python3
"""
Summarize warmup cold-start timings from warmup logs.

Parses docs/benchmarks/warmup-*.log and writes:
  - docs/benchmarks/cold-start-times.csv
  - docs/benchmarks/cold-start-summary.md
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GLOB = "docs/benchmarks/warmup-*.log"
DEFAULT_CSV = Path("docs/benchmarks/cold-start-times.csv")
DEFAULT_MD = Path("docs/benchmarks/cold-start-summary.md")


@dataclass
class WarmupSample:
    log_file: str
    label: str
    ready_stable: bool
    elapsed_s: int | None


def parse_elapsed_seconds(lines: list[str]) -> int | None:
    elapsed = None
    for line in lines:
        match = re.search(r"\[(\d+)m(\d+)s\]", line)
        if match:
            elapsed = int(match.group(1)) * 60 + int(match.group(2))
    return elapsed


def parse_label(path: Path) -> str:
    name = path.stem
    if name.startswith("warmup-"):
        name = name[len("warmup-") :]
    match = re.match(r"(.+)-\d{4}-\d{2}-\d{2}-\d{6}$", name)
    if match:
        return match.group(1)
    return name


def format_mmss(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def build_samples(log_glob: str) -> list[WarmupSample]:
    samples: list[WarmupSample] = []
    for path in sorted(REPO_ROOT.glob(log_glob)):
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        samples.append(
            WarmupSample(
                log_file=str(path.relative_to(REPO_ROOT)),
                label=parse_label(path),
                ready_stable=any("==> Ready and stable." in line for line in lines),
                elapsed_s=parse_elapsed_seconds(lines),
            )
        )
    return samples


def write_csv(path: Path, samples: list[WarmupSample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "log_file",
                "label",
                "ready_stable",
                "elapsed_seconds",
                "elapsed_mmss",
            ]
        )
        for row in samples:
            writer.writerow(
                [
                    row.log_file,
                    row.label,
                    "yes" if row.ready_stable else "no",
                    "" if row.elapsed_s is None else row.elapsed_s,
                    format_mmss(row.elapsed_s),
                ]
            )


def write_markdown(path: Path, samples: list[WarmupSample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ready = [s for s in samples if s.ready_stable and s.elapsed_s is not None]
    benchmark_only = [
        s
        for s in ready
        if not (s.label.startswith("probe-") or s.label.startswith("verify-"))
    ]

    lines: list[str] = [
        "# Cold Start Summary",
        "",
        f"Generated: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "Source: `warmup.sh` logs (`docs/benchmarks/warmup-*.log`).",
        "Duration is the final `[XmYs]` marker before `Ready and stable`.",
        "",
    ]

    if ready:
        ready_seconds = [s.elapsed_s for s in ready if s.elapsed_s is not None]
        lines.extend(
            [
                "## All Ready Runs",
                "",
                f"- samples: **{len(ready_seconds)}**",
                f"- min: **{min(ready_seconds)}s** ({format_mmss(min(ready_seconds))})",
                f"- max: **{max(ready_seconds)}s** ({format_mmss(max(ready_seconds))})",
                f"- avg: **{mean(ready_seconds):.1f}s** ({format_mmss(round(mean(ready_seconds)))})",
                f"- median: **{median(ready_seconds):.1f}s**",
                "",
            ]
        )

    if benchmark_only:
        b_seconds = [s.elapsed_s for s in benchmark_only if s.elapsed_s is not None]
        lines.extend(
            [
                "## Benchmark-Labeled Runs (excluding `probe-*` and `verify-*`)",
                "",
                f"- samples: **{len(b_seconds)}**",
                f"- min: **{min(b_seconds)}s** ({format_mmss(min(b_seconds))})",
                f"- max: **{max(b_seconds)}s** ({format_mmss(max(b_seconds))})",
                f"- avg: **{mean(b_seconds):.1f}s** ({format_mmss(round(mean(b_seconds)))})",
                f"- median: **{median(b_seconds):.1f}s**",
                "",
            ]
        )

    lines.extend(
        [
            "## Per Run",
            "",
            "| Log | Label | Ready | Time (s) | Time (mm:ss) |",
            "|---|---|---|---:|---:|",
        ]
    )
    for s in sorted(
        samples,
        key=lambda item: item.elapsed_s if item.elapsed_s is not None else 10**9,
    ):
        sec = "-" if s.elapsed_s is None else str(s.elapsed_s)
        mmss = format_mmss(s.elapsed_s)
        ready = "yes" if s.ready_stable else "no"
        lines.append(f"| `{s.log_file}` | `{s.label}` | {ready} | {sec} | {mmss} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize warmup cold-start times.")
    parser.add_argument("--logs-glob", default=DEFAULT_GLOB)
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples = build_samples(args.logs_glob)
    csv_out = (REPO_ROOT / args.csv_out).resolve()
    md_out = (REPO_ROOT / args.md_out).resolve()

    write_csv(csv_out, samples)
    write_markdown(md_out, samples)

    ready = [s for s in samples if s.ready_stable and s.elapsed_s is not None]
    if not ready:
        print("No ready warmup runs found.")
        return 0

    vals = [s.elapsed_s for s in ready if s.elapsed_s is not None]
    print(f"samples={len(vals)} min={min(vals)}s max={max(vals)}s avg={mean(vals):.1f}s")
    print(f"csv={csv_out}")
    print(f"md={md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
