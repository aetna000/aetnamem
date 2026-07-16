#!/usr/bin/env python3
"""Reproduce the bounded-recall probe reported in governed-memory.tex."""

from __future__ import annotations

import argparse
import json
from math import ceil
import platform
from pathlib import Path
from statistics import median
import subprocess
import sys
from time import perf_counter
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aetnamem import Memory  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def rank_of(rows: list[dict[str, object]], record_id: str) -> int | None:
    return next(
        (index for index, row in enumerate(rows, start=1) if row["id"] == record_id),
        None,
    )


def git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def source_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as source:
        return str(tomllib.load(source)["project"]["version"])


def host_metadata() -> dict[str, object]:
    metadata: dict[str, object] = {
        "operating_system": platform.system(),
        "release": platform.release(),
        "python_process_machine": platform.machine(),
        "python": platform.python_version(),
    }
    if platform.system() == "Darwin":
        cpu = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        memory = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        metadata.update({"cpu": cpu, "memory_bytes": int(memory)})
    return metadata


def run(records: int, iterations: int, candidate_cap: int) -> dict[str, object]:
    root = ROOT
    memory = Memory(":memory:", recall_candidate_limit=candidate_cap)

    ingest_started = perf_counter()
    memory.remember("bench", "My boss is Sarah.")
    target = memory.remember(
        "bench", "Sarah's preferred airport is SEA."
    )["records"][0]
    for index in range(records):
        memory.remember(
            "bench",
            f"My synthetic setting {index} is synthetic-value-{index}.",
        )
    ingest_ms = (perf_counter() - ingest_started) * 1000

    query = "What does my boss use for flights?"
    for _ in range(3):
        memory.recall("bench", query, limit=10, use_graph=False)
        memory.recall("bench", query, limit=10, use_graph=True)

    direct_times: list[float] = []
    graph_times: list[float] = []
    direct_rows: list[dict[str, object]] = []
    graph_rows: list[dict[str, object]] = []
    for _ in range(iterations):
        started = perf_counter()
        direct_rows = memory.recall("bench", query, limit=10, use_graph=False)
        direct_times.append((perf_counter() - started) * 1000)

        started = perf_counter()
        graph_rows = memory.recall("bench", query, limit=10, use_graph=True)
        graph_times.append((perf_counter() - started) * 1000)

    event = memory.get_retrieval_log("bench")[-1]
    result = {
        "artifact": {
            "aetnamem_version": source_version(root),
            "commit": git_commit(root),
            "script": "paper/scripts/run_governed_memory_probe.py",
        },
        "host": host_metadata(),
        "workload": {
            "canonical_records": records + 2,
            "synthetic_records": records,
            "query": query,
            "iterations": iterations,
            "warmup_iterations": 3,
            "candidate_cap": candidate_cap,
            "result_limit": 10,
            "database": "SQLite :memory:",
        },
        "results": {
            "ingest_ms": round(ingest_ms, 3),
            "direct_target_rank": rank_of(direct_rows, target["id"]),
            "graph_target_rank": rank_of(graph_rows, target["id"]),
            "logged_candidates": len(event["candidates"]),
            "graph_visited_edges": event["raw"]["visited_edges"],
            "direct_ms": {
                "median": round(median(direct_times), 3),
                "p95_order_statistic": round(percentile(direct_times, 0.95), 3),
            },
            "graph_ms": {
                "median": round(median(graph_times), 3),
                "p95_order_statistic": round(percentile(graph_times, 0.95), 3),
            },
        },
        "interpretation_limits": [
            "Single host and one synthetic query.",
            "In-memory SQLite excludes durable I/O and encryption overhead.",
            "Latency intervals exclude ingestion and graph construction.",
            "This is not a retrieval-quality, concurrency, or million-record benchmark.",
        ],
    }
    memory.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=10_000)
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--candidate-cap", type=int, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.records, args.iterations, args.candidate_cap)
    document = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(document, encoding="utf-8")
    else:
        sys.stdout.write(document)


if __name__ == "__main__":
    main()
