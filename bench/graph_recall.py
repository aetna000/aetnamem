#!/usr/bin/env python3
"""Reproducible local benchmark for candidate-capped and graph recall."""

from __future__ import annotations

import argparse
import json
from statistics import median
from time import perf_counter

from aetnamem import Memory


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index]


def run(record_count: int, iterations: int, candidate_cap: int) -> dict[str, object]:
    memory = Memory(":memory:", recall_candidate_limit=candidate_cap)
    memory.remember("bench", "My boss is Sarah.")
    target = memory.remember("bench", "Sarah's preferred airport is SEA.")["records"][0]
    for index in range(record_count):
        memory.remember(
            "bench",
            f"My synthetic setting {index} is synthetic-value-{index}.",
        )

    query = "What does my boss use for flights?"
    lexical_times: list[float] = []
    graph_times: list[float] = []
    for _ in range(iterations):
        started = perf_counter()
        memory.recall("bench", query, limit=10, use_graph=False)
        lexical_times.append((perf_counter() - started) * 1000)
        started = perf_counter()
        graph_results = memory.recall("bench", query, limit=10, use_graph=True)
        graph_times.append((perf_counter() - started) * 1000)

    target_rank = next(
        (
            index
            for index, record in enumerate(graph_results, start=1)
            if record["id"] == target["id"]
        ),
        None,
    )
    latest_event = memory.get_retrieval_log("bench")[-1]
    return {
        "records": record_count + 2,
        "iterations": iterations,
        "candidate_cap": candidate_cap,
        "logged_candidates": len(latest_event["candidates"]),
        "graph_visited_edges": latest_event["raw"]["visited_edges"],
        "graph_target_rank": target_rank,
        "lexical_ms": {
            "median": round(median(lexical_times), 3),
            "p95": round(percentile(lexical_times, 0.95), 3),
        },
        "graph_ms": {
            "median": round(median(graph_times), 3),
            "p95": round(percentile(graph_times, 0.95), 3),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=10_000)
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--candidate-cap", type=int, default=200)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.records, args.iterations, args.candidate_cap),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
