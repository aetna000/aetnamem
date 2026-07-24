#!/usr/bin/env python3
"""Run a small labeled lexical/semantic/hybrid retrieval comparison."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import tempfile
import time

from aetnamem import Memory
from aetnamem.investigate import search_evidence
from aetnamem.semantic import SemanticIndex, create_embedder


HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--embedder",
        choices=("ollama", "openai-compatible", "sentence-transformers", "hashing"),
        default="ollama",
    )
    parser.add_argument("--model", default="nomic-embed-text")
    parser.add_argument("--model-version", default="unverified")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    golden = json.loads((HERE / "golden.json").read_text(encoding="utf-8"))
    embedder = create_embedder(
        args.embedder,
        args.model,
        endpoint=args.endpoint,
        api_key_env=args.api_key_env,
        model_version=args.model_version,
    )
    with tempfile.TemporaryDirectory(prefix="aetnamem-semantic-bench-") as directory:
        memory = Memory(Path(directory) / "memories.db")
        index = SemanticIndex(Path(directory) / "vectors.db")
        try:
            record_keys: dict[str, str] = {}
            for item in golden["records"]:
                result = memory.remember("benchmark", item["text"], force=True)
                record_keys[str(result["records"][0]["id"])] = item["key"]
            build_started = time.perf_counter()
            build = index.build(memory, "benchmark", embedder)
            build_ms = (time.perf_counter() - build_started) * 1000

            modes: dict[str, dict] = {}
            for mode in ("lexical", "semantic", "hybrid"):
                ranks: list[int | None] = []
                latencies: list[float] = []
                cases: list[dict] = []
                for query in golden["queries"]:
                    started = time.perf_counter()
                    report = search_evidence(
                        memory,
                        "benchmark",
                        query["query"],
                        scope="memories",
                        mode=mode,
                        semantic_index=index if mode != "lexical" else None,
                        embedder=embedder if mode != "lexical" else None,
                        limit=10,
                    )
                    latencies.append((time.perf_counter() - started) * 1000)
                    returned = [
                        record_keys[item["id"]]
                        for item in report["results"]
                        if item["id"] in record_keys
                    ]
                    relevant = set(query["relevant"])
                    rank = next(
                        (
                            position
                            for position, key in enumerate(returned, start=1)
                            if key in relevant
                        ),
                        None,
                    )
                    ranks.append(rank)
                    cases.append(
                        {
                            "query": query["query"],
                            "relevant": sorted(relevant),
                            "returned": returned,
                            "first_relevant_rank": rank,
                        }
                    )
                modes[mode] = {
                    "recall_at_5": sum(rank is not None and rank <= 5 for rank in ranks)
                    / len(ranks),
                    "recall_at_10": sum(rank is not None and rank <= 10 for rank in ranks)
                    / len(ranks),
                    "mrr": sum(1.0 / rank if rank else 0.0 for rank in ranks)
                    / len(ranks),
                    "ndcg_at_10": sum(
                        1.0 / math.log2(rank + 1) if rank and rank <= 10 else 0.0
                        for rank in ranks
                    )
                    / len(ranks),
                    "latency_ms_mean": sum(latencies) / len(latencies),
                    "cases": cases,
                }
            output = {
                "format": "aetnamem-semantic-search-benchmark-v1",
                "dataset": golden["format"],
                "embedder": dict(embedder.identity),
                "index_epoch": build["epoch_id"],
                "build_ms": build_ms,
                "modes": modes,
                "claims_boundary": (
                    "Small repository fixture; use a larger independently labeled "
                    "held-out set before making retrieval-quality claims."
                ),
            }
        finally:
            index.close()
            memory.close()
    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
