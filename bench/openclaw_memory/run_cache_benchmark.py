#!/usr/bin/env python3
"""Three-arm cache-aware OpenClaw/AetnaMem benchmark on DeepSeek V4 Flash."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aetnamem import Memory

import run_benchmark as original


ARMS = ("native", "aetnamem_current", "aetnamem_cache_aware")
SEED = 20260722
SUBJECT = "openclaw-cache-benchmark"
ROOT = original.ROOT
PLUGIN_PATH = original.PLUGIN_PATH
MODEL = original.MODEL


@dataclass
class CacheTrial:
    phase: str
    case_id: str
    repetition: int
    arm: str
    order_in_block: int
    session_key: str
    answer: str
    expected: list[str]
    correct: bool
    latency_seconds: float
    prompt_tokens: int
    uncached_input_tokens: int
    cache_read_tokens: int
    output_tokens: int
    total_tokens: int
    provider_cost_usd: float
    cache_hit_fraction: float
    retrieval_event_count: int
    retrieval_candidate_count: int
    retrieved_record_ids: list[str]
    retrieved_labels: list[str]
    target_record_retrieved: bool | None
    session_log_sha256: str


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def configure_profile(
    profile: Path,
    *,
    arm: str,
    full_memory: str,
    labeled_facts: list[tuple[str, str]],
    base_env: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    state = profile / "state"
    workspace = profile / "workspace"
    state.mkdir(parents=True)
    env = dict(base_env)
    env["OPENCLAW_STATE_DIR"] = str(state)
    env["OPENCLAW_CONFIG_PATH"] = str(state / "openclaw.json")

    original.run(original.openclaw("setup", "--baseline", "--workspace", str(workspace)), env=env)
    (workspace / "MEMORY.md").write_text(
        full_memory if arm == "native" else original.minimal_memory_document(),
        encoding="utf-8",
    )
    original.run(original.openclaw("plugins", "install", original.DEEPSEEK_PROVIDER), env=env)
    original.run(
        original.openclaw(
            "config", "set", "agents.defaults.model.primary", json.dumps(MODEL), "--strict-json"
        ),
        env=env,
    )

    record_labels: dict[str, str] = {}
    if arm != "native":
        database = profile / "aetnamem.db"
        original.run(original.openclaw("plugins", "install", str(PLUGIN_PATH)), env=env)
        cache_aware = arm == "aetnamem_cache_aware"
        plugin_config = {
            "command": sys.executable,
            "commandArgs": [
                "-m", "aetnamem.cli", "mcp", "--db", str(database), "--subject", SUBJECT
            ],
            "dbPath": str(database),
            "subject": SUBJECT,
            "recall": {
                "enabled": True,
                "maxRecords": 3,
                "maxChars": 1200,
                "minScore": 0.3,
                "timeoutMs": 5000,
            },
            "persona": {"enabled": True, "maxChars": 600, "ttlSeconds": 300},
            "capture": {"enabled": False, "captureAssistant": False},
            "cacheAware": {"enabled": cache_aware, "compactReferences": True},
            "tools": {"enabled": not cache_aware},
        }
        settings = [
            ("plugins.entries.memory-aetnamem.enabled", True),
            ("plugins.entries.memory-aetnamem.hooks.allowConversationAccess", True),
            ("plugins.entries.memory-aetnamem.config", plugin_config),
        ]
        for key, value in settings:
            original.run(
                original.openclaw("config", "set", key, json.dumps(value), "--strict-json"),
                env=env,
            )

        memory = Memory(database)
        try:
            for index, (label, fact) in enumerate(labeled_facts):
                result = memory.remember(
                    SUBJECT, f"Remember that {fact}", session_id="seed", turn_id=index
                )
                for record in result["records"]:
                    record_labels[str(record["id"])] = label
        finally:
            memory.close()

    original.run(original.openclaw("config", "validate"), env=env)
    return env, record_labels


def retrieval_evidence(
    database: Path, before: int, labels: dict[str, str]
) -> tuple[int, list[str], list[str], int]:
    memory = Memory(database)
    try:
        events = memory.store.list_retrieval_events(SUBJECT)
    finally:
        memory.close()
    fresh = events[before:]
    record_ids: list[str] = []
    candidate_count = 0
    for event in fresh:
        record_ids.extend(str(item) for item in event.get("returned_ids", []))
        candidate_count += len(event.get("candidates", []))
    return (
        len(events),
        record_ids,
        [labels.get(record_id, "unknown") for record_id in record_ids],
        candidate_count,
    )


def execute(
    *,
    phase: str,
    case_id: str,
    repetition: int,
    arm: str,
    order_in_block: int,
    prompt: str,
    expected: list[str],
    profile: Path,
    env: dict[str, str],
    retrieval_count: int,
    record_labels: dict[str, str],
) -> tuple[CacheTrial, int]:
    session_key = f"cache-{phase}-{case_id}-r{repetition}-{arm}"
    state = Path(env["OPENCLAW_STATE_DIR"])
    before_files = original.session_files(state)
    started = time.perf_counter()
    result = original.run(
        original.openclaw(
            "agent", "--local", "--agent", "main", "--session-key", session_key,
            "--message", prompt, "--model", MODEL, "--thinking", "off", "--timeout", "180", "--json",
        ),
        env=env,
    )
    latency = time.perf_counter() - started
    files = list(original.session_files(state) - before_files)
    if not files:
        files = sorted(
            original.session_files(state), key=lambda item: item.stat().st_mtime, reverse=True
        )[:1]
    if not files:
        raise RuntimeError(f"no canonical session log; stderr={result.stderr[-2000:]}")
    session_path = max(files, key=lambda item: item.stat().st_mtime)
    parsed = original.parse_session(session_path)
    usage = parsed["usage"]
    uncached = int(usage.get("input", 0))
    cached = int(usage.get("cacheRead", 0))
    prompt_tokens = uncached + cached

    new_count = retrieval_count
    record_ids: list[str] = []
    retrieved_labels: list[str] = []
    candidate_count = 0
    if arm != "native":
        new_count, record_ids, retrieved_labels, candidate_count = retrieval_evidence(
            profile / "aetnamem.db", retrieval_count, record_labels
        )

    target_retrieved = None
    if phase == "task" and arm != "native":
        target_retrieved = case_id in retrieved_labels

    trial = CacheTrial(
        phase=phase,
        case_id=case_id,
        repetition=repetition,
        arm=arm,
        order_in_block=order_in_block,
        session_key=session_key,
        answer=parsed["answer"],
        expected=expected,
        correct=original.score(parsed["answer"], expected),
        latency_seconds=round(latency, 6),
        prompt_tokens=prompt_tokens,
        uncached_input_tokens=uncached,
        cache_read_tokens=cached,
        output_tokens=int(usage.get("output", 0)),
        total_tokens=int(usage.get("totalTokens", 0)),
        provider_cost_usd=float(parsed["provider_cost_usd"] or 0.0),
        cache_hit_fraction=round(cached / prompt_tokens, 8) if prompt_tokens else 0.0,
        retrieval_event_count=max(0, new_count - retrieval_count),
        retrieval_candidate_count=candidate_count,
        retrieved_record_ids=record_ids,
        retrieved_labels=retrieved_labels,
        target_record_retrieved=target_retrieved,
        session_log_sha256=sha256_bytes(session_path.read_bytes()),
    )
    return trial, new_count


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def bootstrap_ci(values: list[float], seed: int, draws: int = 10000) -> list[float]:
    rng = random.Random(seed)
    estimates = [statistics.mean(rng.choice(values) for _ in values) for _ in range(draws)]
    return [round(percentile(estimates, 0.025), 3), round(percentile(estimates, 0.975), 3)]


def arm_summary(rows: list[CacheTrial]) -> dict[str, Any]:
    prompts = [row.prompt_tokens for row in rows]
    uncached = [row.uncached_input_tokens for row in rows]
    cached = [row.cache_read_tokens for row in rows]
    latencies = [row.latency_seconds for row in rows]
    return {
        "trials": len(rows),
        "correct": sum(row.correct for row in rows),
        "accuracy": round(sum(row.correct for row in rows) / len(rows), 4),
        "prompt_tokens_total": sum(prompts),
        "prompt_tokens_mean": round(statistics.mean(prompts), 3),
        "prompt_tokens_median": round(statistics.median(prompts), 3),
        "uncached_input_tokens_total": sum(uncached),
        "cache_read_tokens_total": sum(cached),
        "cache_hit_fraction": round(sum(cached) / sum(prompts), 6),
        "output_tokens_total": sum(row.output_tokens for row in rows),
        "provider_cost_usd_total": round(sum(row.provider_cost_usd for row in rows), 8),
        "latency_seconds_mean": round(statistics.mean(latencies), 3),
        "latency_seconds_median": round(statistics.median(latencies), 3),
        "target_retrievals": sum(row.target_record_retrieved is True for row in rows),
    }


def comparison(
    rows: list[CacheTrial], left: str, right: str, *, seed_offset: int
) -> dict[str, Any]:
    indexed = {(row.case_id, row.repetition, row.arm): row for row in rows}
    keys = sorted({(row.case_id, row.repetition) for row in rows})
    prompt_deltas = [
        indexed[key + (left,)].prompt_tokens - indexed[key + (right,)].prompt_tokens
        for key in keys
    ]
    cost_left = sum(indexed[key + (left,)].provider_cost_usd for key in keys)
    cost_right = sum(indexed[key + (right,)].provider_cost_usd for key in keys)
    prompt_left = sum(indexed[key + (left,)].prompt_tokens for key in keys)
    prompt_right = sum(indexed[key + (right,)].prompt_tokens for key in keys)
    return {
        "left": left,
        "right": right,
        "paired_trials": len(keys),
        "prompt_tokens_saved_total": prompt_left - prompt_right,
        "prompt_token_reduction_percent": round(
            100 * (prompt_left - prompt_right) / prompt_left, 3
        ),
        "paired_prompt_tokens_saved_mean": round(statistics.mean(prompt_deltas), 3),
        "paired_prompt_tokens_saved_median": round(statistics.median(prompt_deltas), 3),
        "paired_mean_savings_95pct_bootstrap_ci_tokens": bootstrap_ci(
            prompt_deltas, SEED + seed_offset
        ),
        "provider_cost_change_percent": round(100 * (cost_right - cost_left) / cost_left, 3),
    }


def summarize(trials: list[CacheTrial]) -> dict[str, Any]:
    tasks = [trial for trial in trials if trial.phase == "task"]
    probes = [trial for trial in trials if trial.phase.startswith("cache_probe")]
    task_arms = {arm: arm_summary([row for row in tasks if row.arm == arm]) for arm in ARMS}
    probe_rows: dict[str, Any] = {}
    for arm in ARMS:
        cold = next(row for row in probes if row.arm == arm and row.phase == "cache_probe_cold")
        warm = next(row for row in probes if row.arm == arm and row.phase == "cache_probe_warm")
        probe_rows[arm] = {
            "cold_prompt_tokens": cold.prompt_tokens,
            "cold_cache_read_tokens": cold.cache_read_tokens,
            "cold_cache_hit_fraction": cold.cache_hit_fraction,
            "cold_cost_usd": cold.provider_cost_usd,
            "warm_prompt_tokens": warm.prompt_tokens,
            "warm_cache_read_tokens": warm.cache_read_tokens,
            "warm_cache_hit_fraction": warm.cache_hit_fraction,
            "warm_cost_usd": warm.provider_cost_usd,
        }
    return {
        "task_arms": task_arms,
        "cache_probes": probe_rows,
        "comparisons": {
            "native_to_current": comparison(tasks, "native", "aetnamem_current", seed_offset=1),
            "native_to_cache_aware": comparison(
                tasks, "native", "aetnamem_cache_aware", seed_offset=2
            ),
            "current_to_cache_aware": comparison(
                tasks, "aetnamem_current", "aetnamem_cache_aware", seed_offset=3
            ),
        },
    }


def metadata(full_memory: str, repetitions: int) -> dict[str, Any]:
    def version(command: list[str]) -> str:
        return subprocess.run(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        ).stdout.strip()

    return {
        "benchmark_version": 1,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "random_seed": SEED,
        "repetitions_per_case": repetitions,
        "cases": len(json.loads(original.CASES_PATH.read_text(encoding="utf-8"))),
        "arms": list(ARMS),
        "cache_probes_per_arm": 2,
        "model": MODEL,
        "thinking": "off",
        "openclaw_version": original.OPENCLAW_VERSION,
        "deepseek_provider_package": original.DEEPSEEK_PROVIDER,
        "aetnamem_distribution_version": importlib.metadata.version("aetnamem"),
        "aetnamem_git_commit": version(["git", "rev-parse", "HEAD"]),
        "openclaw_plugin_version": json.loads((PLUGIN_PATH / "package.json").read_text())["version"],
        "python": sys.version.split()[0],
        "node": version(["node", "--version"]),
        "platform": platform.platform(),
        "baseline_memory_chars": len(full_memory),
        "baseline_memory_sha256": sha256_bytes(full_memory.encode()),
        "minimal_memory_chars": len(original.minimal_memory_document()),
        "case_file_sha256": sha256_bytes(original.CASES_PATH.read_bytes()),
        "harness_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "no_trial_exclusions": True,
        "task_order": "three-arm rotating Latin order by case and repetition",
        "scoring": "case-insensitive containment of every pre-registered expected fragment",
    }


def markdown_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    arms = summary["task_arms"]
    comp = summary["comparisons"]
    evidence = payload["aetnamem_evidence"]
    return f"""# Cache-aware OpenClaw × AetnaMem benchmark

Run completed: `{payload['metadata']['completed_at_utc']}`  
Harness commit: `{payload['metadata']['aetnamem_git_commit']}`  
Model: `{MODEL}` with thinking off  
Measured task calls: {sum(item['trials'] for item in arms.values())}; cache-probe calls: 6

## Task result

| Metric | Native `MEMORY.md` | Current AetnaMem | Cache-aware AetnaMem |
|---|---:|---:|---:|
| Prompt tokens, total | {arms['native']['prompt_tokens_total']:,} | {arms['aetnamem_current']['prompt_tokens_total']:,} | {arms['aetnamem_cache_aware']['prompt_tokens_total']:,} |
| Prompt tokens, median/task | {arms['native']['prompt_tokens_median']:,.1f} | {arms['aetnamem_current']['prompt_tokens_median']:,.1f} | {arms['aetnamem_cache_aware']['prompt_tokens_median']:,.1f} |
| Cache-hit fraction | {arms['native']['cache_hit_fraction']:.1%} | {arms['aetnamem_current']['cache_hit_fraction']:.1%} | {arms['aetnamem_cache_aware']['cache_hit_fraction']:.1%} |
| Provider cost | ${arms['native']['provider_cost_usd_total']:.6f} | ${arms['aetnamem_current']['provider_cost_usd_total']:.6f} | ${arms['aetnamem_cache_aware']['provider_cost_usd_total']:.6f} |
| Correct | {arms['native']['correct']}/{arms['native']['trials']} | {arms['aetnamem_current']['correct']}/{arms['aetnamem_current']['trials']} | {arms['aetnamem_cache_aware']['correct']}/{arms['aetnamem_cache_aware']['trials']} |
| Target retrieved | — | {arms['aetnamem_current']['target_retrievals']}/{arms['aetnamem_current']['trials']} | {arms['aetnamem_cache_aware']['target_retrievals']}/{arms['aetnamem_cache_aware']['trials']} |

Native → cache-aware saved **{comp['native_to_cache_aware']['prompt_tokens_saved_total']:,} prompt tokens
({comp['native_to_cache_aware']['prompt_token_reduction_percent']:.3f}%)**; provider cost changed
{comp['native_to_cache_aware']['provider_cost_change_percent']:+.3f}%. Current → cache-aware saved
**{comp['current_to_cache_aware']['prompt_tokens_saved_total']:,} prompt tokens
({comp['current_to_cache_aware']['prompt_token_reduction_percent']:.3f}%)**; provider cost changed
{comp['current_to_cache_aware']['provider_cost_change_percent']:+.3f}%.

## Cache probes

Two identical, unrelated fresh-session prompts ran consecutively per arm. The first is the cold observation and the second
the immediate warm observation. DeepSeek caching is best-effort, so these six calls are descriptive rather than a controlled
cache-disable experiment.

| Arm | Cold cache hit | Warm cache hit | Cold cost | Warm cost |
|---|---:|---:|---:|---:|
| Native | {summary['cache_probes']['native']['cold_cache_hit_fraction']:.1%} | {summary['cache_probes']['native']['warm_cache_hit_fraction']:.1%} | ${summary['cache_probes']['native']['cold_cost_usd']:.6f} | ${summary['cache_probes']['native']['warm_cost_usd']:.6f} |
| Current AetnaMem | {summary['cache_probes']['aetnamem_current']['cold_cache_hit_fraction']:.1%} | {summary['cache_probes']['aetnamem_current']['warm_cache_hit_fraction']:.1%} | ${summary['cache_probes']['aetnamem_current']['cold_cost_usd']:.6f} | ${summary['cache_probes']['aetnamem_current']['warm_cost_usd']:.6f} |
| Cache-aware AetnaMem | {summary['cache_probes']['aetnamem_cache_aware']['cold_cache_hit_fraction']:.1%} | {summary['cache_probes']['aetnamem_cache_aware']['warm_cache_hit_fraction']:.1%} | ${summary['cache_probes']['aetnamem_cache_aware']['cold_cost_usd']:.6f} | ${summary['cache_probes']['aetnamem_cache_aware']['warm_cost_usd']:.6f} |

## Evidence and limits

The cache-aware bundle changes three things together: stable persona placement (`appendSystemContext`), dynamic recall
placement (`appendContext`) with compact references, and omission of explicit search/forget schemas. This measures the
deployable optimized configuration, not the isolated causal effect of each change. The workload is synthetic, uses one
provider/model and one host, repeats 10 cases twice, and cannot establish a universal savings or clinical claim.

Current audit valid: `{str(evidence['aetnamem_current']['audit_chain_valid']).lower()}`; cache-aware audit valid:
`{str(evidence['aetnamem_cache_aware']['audit_chain_valid']).lower()}`. Raw per-call usage, answers, retrieval labels,
session hashes, input hashes, software versions, and paired bootstrap summaries are in the adjacent JSON artifact.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("results"))
    parser.add_argument("--keep-runtime", action="store_true")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        parser.error("DEEPSEEK_API_KEY is required and is never persisted")

    cases = json.loads(original.CASES_PATH.read_text(encoding="utf-8"))
    targets = [case["fact"] for case in cases]
    distractors = original.distractor_facts()
    full_memory = original.memory_document(targets, distractors)
    labeled_facts = [(case["id"], case["fact"]) for case in cases] + [
        ("distractor", fact) for fact in distractors
    ]
    runtime = Path(tempfile.mkdtemp(prefix="aetnamem-openclaw-cache-bench-"))
    profiles = {arm: runtime / arm for arm in ARMS}
    trials: list[CacheTrial] = []
    retrieval_counts = {arm: 0 for arm in ARMS}

    try:
        configured = {
            arm: configure_profile(
                profiles[arm],
                arm=arm,
                full_memory=full_memory,
                labeled_facts=labeled_facts,
                base_env=dict(os.environ),
            )
            for arm in ARMS
        }
        envs = {arm: configured[arm][0] for arm in ARMS}
        labels = {arm: configured[arm][1] for arm in ARMS}

        probe_prompt = (
            "This is a cache-layout probe. Do not call tools. Reply with exactly CACHE_READY "
            "and nothing else. No durable memory is relevant to this request."
        )
        for arm_index, arm in enumerate(ARMS, start=1):
            for repetition, phase in ((1, "cache_probe_cold"), (2, "cache_probe_warm")):
                trial, retrieval_counts[arm] = execute(
                    phase=phase,
                    case_id="cache-ready",
                    repetition=repetition,
                    arm=arm,
                    order_in_block=arm_index,
                    prompt=probe_prompt,
                    expected=["CACHE_READY"],
                    profile=profiles[arm],
                    env=envs[arm],
                    retrieval_count=retrieval_counts[arm],
                    record_labels=labels[arm],
                )
                trials.append(trial)
                print(
                    f"[probe {arm} {phase}] prompt={trial.prompt_tokens} "
                    f"cache={trial.cache_read_tokens} correct={trial.correct}",
                    flush=True,
                )

        total_tasks = len(cases) * args.repetitions * len(ARMS)
        completed = 0
        for repetition in range(1, args.repetitions + 1):
            for case_index, case in enumerate(cases):
                offset = (case_index + repetition - 1) % len(ARMS)
                order = ARMS[offset:] + ARMS[:offset]
                prompt = (
                    "This is a cross-session memory check. Do not call tools. Answer in one concise sentence. "
                    "If the information is unavailable, answer exactly: UNKNOWN.\n\n"
                    f"Question: {case['question']}"
                )
                for order_index, arm in enumerate(order, start=1):
                    trial, retrieval_counts[arm] = execute(
                        phase="task",
                        case_id=case["id"],
                        repetition=repetition,
                        arm=arm,
                        order_in_block=order_index,
                        prompt=prompt,
                        expected=list(case["expected"]),
                        profile=profiles[arm],
                        env=envs[arm],
                        retrieval_count=retrieval_counts[arm],
                        record_labels=labels[arm],
                    )
                    trials.append(trial)
                    completed += 1
                    print(
                        f"[{completed:02d}/{total_tasks}] {trial.case_id} {arm}: "
                        f"prompt={trial.prompt_tokens} cache={trial.cache_read_tokens} "
                        f"correct={trial.correct}",
                        flush=True,
                    )

        evidence: dict[str, Any] = {}
        for arm in ARMS[1:]:
            memory = Memory(profiles[arm] / "aetnamem.db")
            try:
                audit = memory.audit(SUBJECT)
                evidence[arm] = {
                    "audit_chain_valid": bool(audit["audit_chain_valid"]),
                    "audit_events": len(audit["audit_log"]),
                    "retrieval_events": len(audit["retrieval_events"]),
                    "seeded_records": len(labels[arm]),
                }
            finally:
                memory.close()

        payload = {
            "metadata": metadata(full_memory, args.repetitions),
            "summary": summarize(trials),
            "aetnamem_evidence": evidence,
            "trials": [asdict(trial) for trial in trials],
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        json_path = args.output_dir / f"deepseek-v4-flash-cache-aware-{stamp}.json"
        report_path = args.output_dir / f"deepseek-v4-flash-cache-aware-{stamp}.md"
        json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report_path.write_text(markdown_report(payload), encoding="utf-8")
        print(f"Result: {json_path}")
        print(f"Report: {report_path}")
    finally:
        if args.keep_runtime:
            print(f"Runtime retained: {runtime}")
        else:
            shutil.rmtree(runtime, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
