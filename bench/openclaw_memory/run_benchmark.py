#!/usr/bin/env python3
"""Paired OpenClaw durable-memory benchmark using DeepSeek V4 Flash.

The control replays a mature MEMORY.md on every fresh session. The treatment
stores the same facts in AetnaMem and leaves only bootstrap instructions in
MEMORY.md. Both arms use the same OpenClaw release, DeepSeek provider, model,
workspace files, prompts, fresh-session policy, and exact-match scorer.
"""

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
from typing import Any, Iterable

from aetnamem import Memory


OPENCLAW_VERSION = "2026.7.1-2"
DEEPSEEK_PROVIDER = "@openclaw/deepseek-provider@2026.7.1"
MODEL = "deepseek/deepseek-v4-flash"
SUBJECT = "openclaw-benchmark"
SEED = 20260721
ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("cases.json")
PLUGIN_PATH = ROOT / "integrations" / "openclaw"


@dataclass
class Trial:
    case_id: str
    repetition: int
    arm: str
    order_in_pair: int
    session_key: str
    answer: str
    expected: list[str]
    correct: bool
    latency_seconds: float
    prompt_tokens: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    provider_cost_usd: float | None
    model: str
    provider: str
    retrieval_event_count: int
    retrieval_candidate_count: int
    retrieved_record_ids: list[str]
    retrieved_labels: list[str]
    target_record_retrieved: bool | None
    session_log_sha256: str


def run(command: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        safe = " ".join(command[:4])
        raise RuntimeError(f"command failed ({result.returncode}): {safe}\n{result.stderr[-4000:]}")
    return result


def openclaw(*args: str) -> list[str]:
    return ["npx", "--yes", f"openclaw@{OPENCLAW_VERSION}", *args]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize(value: str) -> str:
    return " ".join(value.casefold().replace("%", " percent ").split())


def score(answer: str, expected: Iterable[str]) -> bool:
    normalized = normalize(answer)
    return all(normalize(fragment) in normalized for fragment in expected)


def distractor_facts(count: int = 84) -> list[str]:
    """Create a stable, realistic mature-memory workload without hidden randomness."""
    services = ["pharmacy", "radiology", "pathology", "outpatients", "theatre", "emergency", "oncology"]
    controls = ["availability", "privacy", "safety", "capacity", "latency", "interface", "access"]
    facts: list[str] = []
    for index in range(1, count + 1):
        code = f"AUX-{index:03d}"
        service = services[(index - 1) % len(services)]
        control = controls[(index * 3) % len(controls)]
        facts.append(
            f"The {code} {service} workstream reviews its {control} control every "
            f"{(index % 9) + 1} weeks; evidence is filed in register REG-{4100 + index}, "
            f"the accountable forum is board B-{(index % 13) + 1:02d}, and unresolved "
            f"exceptions escalate after {(index % 5) + 1} business days."
        )
    return facts


def memory_document(targets: list[str], distractors: list[str]) -> str:
    lines = [
        "# Durable operating memory",
        "",
        "These are synthetic but realistic hospital deployment facts used by the benchmark.",
        "Use an applicable fact when its project code appears in the question.",
        "",
        "## Active programme facts",
        "",
    ]
    lines.extend(f"- {fact}" for fact in targets)
    lines.extend(["", "## Portfolio operating details", ""])
    lines.extend(f"- {fact}" for fact in distractors)
    return "\n".join(lines) + "\n"


def minimal_memory_document() -> str:
    return (
        "# Durable operating memory\n\n"
        "Durable programme facts are supplied by the AetnaMem plugin when relevant. "
        "Do not invent a value when no matching evidence is present.\n"
    )


def configure_profile(
    root: Path,
    *,
    arm: str,
    full_memory: str,
    labeled_facts: list[tuple[str, str]],
    base_env: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    state = root / "state"
    workspace = root / "workspace"
    state.mkdir(parents=True)
    env = dict(base_env)
    env["OPENCLAW_STATE_DIR"] = str(state)
    env["OPENCLAW_CONFIG_PATH"] = str(state / "openclaw.json")

    run(openclaw("setup", "--baseline", "--workspace", str(workspace)), env=env)
    (workspace / "MEMORY.md").write_text(
        full_memory if arm == "baseline" else minimal_memory_document(), encoding="utf-8"
    )
    run(openclaw("plugins", "install", DEEPSEEK_PROVIDER), env=env)
    run(
        openclaw("config", "set", "agents.defaults.model.primary", json.dumps(MODEL), "--strict-json"),
        env=env,
    )

    record_labels: dict[str, str] = {}
    if arm == "aetnamem":
        database = root / "aetnamem.db"
        run(openclaw("plugins", "install", str(PLUGIN_PATH)), env=env)
        plugin_config = {
            "command": sys.executable,
            "commandArgs": ["-m", "aetnamem.cli", "mcp", "--db", str(database), "--subject", SUBJECT],
            "dbPath": str(database),
            "subject": SUBJECT,
            "recall": {"enabled": True, "maxRecords": 3, "maxChars": 1200, "minScore": 0.3, "timeoutMs": 5000},
            "persona": {"enabled": True, "maxChars": 600, "ttlSeconds": 300},
            "capture": {"enabled": False, "captureAssistant": False},
        }
        settings = [
            ("plugins.entries.memory-aetnamem.enabled", True),
            ("plugins.entries.memory-aetnamem.hooks.allowConversationAccess", True),
            ("plugins.entries.memory-aetnamem.config", plugin_config),
        ]
        for key, value in settings:
            run(openclaw("config", "set", key, json.dumps(value), "--strict-json"), env=env)
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

    run(openclaw("config", "validate"), env=env)
    return env, record_labels


def session_files(state_dir: Path) -> set[Path]:
    sessions = state_dir / "agents" / "main" / "sessions"
    if not sessions.exists():
        return set()
    return {path for path in sessions.glob("*.jsonl") if not path.name.endswith(".trajectory.jsonl")}


def parse_session(path: Path) -> dict[str, Any]:
    assistants: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        message = value.get("message") if isinstance(value, dict) else None
        if isinstance(message, dict) and message.get("role") == "assistant" and message.get("usage"):
            assistants.append(message)
    if not assistants:
        raise RuntimeError(f"no assistant usage record in {path.name}")
    message = assistants[-1]
    text_parts = [part.get("text", "") for part in message.get("content", []) if part.get("type") == "text"]
    usage = message.get("usage", {})
    cost = usage.get("cost", {})
    provider_cost = None
    if isinstance(cost, dict) and cost:
        provider_cost = float(cost.get("total", sum(float(v) for v in cost.values() if isinstance(v, (int, float)))))
    return {
        "answer": "".join(text_parts).strip(),
        "usage": usage,
        "provider_cost_usd": provider_cost,
        "provider": str(message.get("provider", "")),
        "model": str(message.get("model", "")),
    }


def new_retrieval_evidence(database: Path, before: int) -> tuple[int, list[str], int]:
    memory = Memory(database)
    try:
        events = memory.store.list_retrieval_events(SUBJECT)
    finally:
        memory.close()
    fresh = events[before:]
    returned: list[str] = []
    candidate_count = 0
    for event in fresh:
        returned.extend(str(item) for item in event.get("returned_ids", []))
        candidate_count += len(event.get("candidates", []))
    return len(events), returned, candidate_count


def execute_trial(
    *,
    case: dict[str, Any],
    repetition: int,
    arm: str,
    order_in_pair: int,
    profile: Path,
    env: dict[str, str],
    retrieval_count: int,
    record_labels: dict[str, str],
) -> tuple[Trial, int]:
    session_key = f"bench-{case['id']}-r{repetition}-{arm}"
    state = Path(env["OPENCLAW_STATE_DIR"])
    before_files = session_files(state)
    prompt = (
        "This is a cross-session memory check. Do not call tools. Answer in one concise sentence. "
        "If the information is unavailable, answer exactly: UNKNOWN.\n\n"
        f"Question: {case['question']}"
    )
    started = time.perf_counter()
    result = run(
        openclaw(
            "agent", "--local", "--agent", "main", "--session-key", session_key,
            "--message", prompt, "--model", MODEL, "--thinking", "off", "--timeout", "180", "--json",
        ),
        env=env,
    )
    latency = time.perf_counter() - started
    after_files = session_files(state)
    candidates = list(after_files - before_files)
    if not candidates:
        candidates = sorted(after_files, key=lambda item: item.stat().st_mtime, reverse=True)[:1]
    if not candidates:
        raise RuntimeError(f"OpenClaw produced no session log; stderr={result.stderr[-2000:]}")
    session_path = max(candidates, key=lambda item: item.stat().st_mtime)
    parsed = parse_session(session_path)
    usage = parsed["usage"]

    retrieved_ids: list[str] = []
    retrieved_labels: list[str] = []
    retrieval_candidate_count = 0
    new_count = retrieval_count
    if arm == "aetnamem":
        new_count, retrieved_ids, retrieval_candidate_count = new_retrieval_evidence(
            profile / "aetnamem.db", retrieval_count
        )
        retrieved_labels = [record_labels.get(record_id, "unknown") for record_id in retrieved_ids]

    trial = Trial(
        case_id=case["id"],
        repetition=repetition,
        arm=arm,
        order_in_pair=order_in_pair,
        session_key=session_key,
        answer=parsed["answer"],
        expected=list(case["expected"]),
        correct=score(parsed["answer"], case["expected"]),
        latency_seconds=round(latency, 6),
        prompt_tokens=int(usage.get("input", 0)) + int(usage.get("cacheRead", 0)),
        input_tokens=int(usage.get("input", 0)),
        output_tokens=int(usage.get("output", 0)),
        cache_read_tokens=int(usage.get("cacheRead", 0)),
        cache_write_tokens=int(usage.get("cacheWrite", 0)),
        total_tokens=int(usage.get("totalTokens", 0)),
        provider_cost_usd=parsed["provider_cost_usd"],
        model=parsed["model"],
        provider=parsed["provider"],
        retrieval_event_count=max(0, new_count - retrieval_count),
        retrieval_candidate_count=retrieval_candidate_count,
        retrieved_record_ids=retrieved_ids,
        retrieved_labels=retrieved_labels,
        target_record_retrieved=case["id"] in retrieved_labels if arm == "aetnamem" else None,
        session_log_sha256=sha256_bytes(session_path.read_bytes()),
    )
    return trial, new_count


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def bootstrap_paired_ci(pairs: list[float], seed: int = SEED, draws: int = 10000) -> list[float]:
    rng = random.Random(seed)
    if not pairs:
        return [math.nan, math.nan]
    estimates = [statistics.mean(rng.choice(pairs) for _ in pairs) for _ in range(draws)]
    return [round(percentile(estimates, 0.025), 3), round(percentile(estimates, 0.975), 3)]


def summarize(trials: list[Trial]) -> dict[str, Any]:
    by_arm = {arm: [trial for trial in trials if trial.arm == arm] for arm in ("baseline", "aetnamem")}
    summary: dict[str, Any] = {"arms": {}}
    for arm, rows in by_arm.items():
        prompts = [row.prompt_tokens for row in rows]
        inputs = [row.input_tokens for row in rows]
        latencies = [row.latency_seconds for row in rows]
        costs = [row.provider_cost_usd for row in rows if row.provider_cost_usd is not None]
        summary["arms"][arm] = {
            "trials": len(rows),
            "correct": sum(row.correct for row in rows),
            "accuracy": round(sum(row.correct for row in rows) / len(rows), 4),
            "prompt_tokens_total": sum(prompts),
            "prompt_tokens_mean": round(statistics.mean(prompts), 3),
            "prompt_tokens_median": round(statistics.median(prompts), 3),
            "input_tokens_total": sum(inputs),
            "input_tokens_mean": round(statistics.mean(inputs), 3),
            "input_tokens_median": round(statistics.median(inputs), 3),
            "output_tokens_total": sum(row.output_tokens for row in rows),
            "cache_read_tokens_total": sum(row.cache_read_tokens for row in rows),
            "cache_hit_fraction": round(
                sum(row.cache_read_tokens for row in rows) / sum(prompts), 6
            ),
            "latency_seconds_mean": round(statistics.mean(latencies), 3),
            "latency_seconds_median": round(statistics.median(latencies), 3),
            "provider_cost_usd_total": round(sum(costs), 8) if costs else None,
        }

    indexed = {(row.case_id, row.repetition, row.arm): row for row in trials}
    pair_keys = sorted({(row.case_id, row.repetition) for row in trials})
    prompt_deltas = [
        indexed[key + ("baseline",)].prompt_tokens - indexed[key + ("aetnamem",)].prompt_tokens
        for key in pair_keys
    ]
    latency_deltas = [
        indexed[key + ("baseline",)].latency_seconds
        - indexed[key + ("aetnamem",)].latency_seconds
        for key in pair_keys
    ]
    baseline_total = summary["arms"]["baseline"]["prompt_tokens_total"]
    treatment_total = summary["arms"]["aetnamem"]["prompt_tokens_total"]
    baseline_cost = summary["arms"]["baseline"]["provider_cost_usd_total"]
    treatment_cost = summary["arms"]["aetnamem"]["provider_cost_usd_total"]
    summary["comparison"] = {
        "paired_trials": len(prompt_deltas),
        "prompt_tokens_saved_total": baseline_total - treatment_total,
        "prompt_token_reduction_percent": round(
            100 * (baseline_total - treatment_total) / baseline_total, 3
        ),
        "paired_prompt_tokens_saved_mean": round(statistics.mean(prompt_deltas), 3),
        "paired_prompt_tokens_saved_median": round(statistics.median(prompt_deltas), 3),
        "paired_mean_savings_95pct_bootstrap_ci_tokens": bootstrap_paired_ci(prompt_deltas),
        "uncached_input_tokens_change": (
            summary["arms"]["aetnamem"]["input_tokens_total"]
            - summary["arms"]["baseline"]["input_tokens_total"]
        ),
        "provider_cost_reduction_percent": round(
            100 * (baseline_cost - treatment_cost) / baseline_cost, 3
        ),
        "paired_latency_seconds_baseline_minus_aetnamem_mean": round(
            statistics.mean(latency_deltas), 3
        ),
        "paired_latency_mean_95pct_bootstrap_ci_seconds": bootstrap_paired_ci(
            latency_deltas, seed=SEED + 1
        ),
        "all_treatment_trials_retrieved_memory": all(
            row.retrieval_event_count > 0 and row.retrieved_record_ids for row in by_arm["aetnamem"]
        ),
        "all_treatment_trials_retrieved_target": all(
            row.target_record_retrieved for row in by_arm["aetnamem"]
        ),
    }
    return summary


def metadata(full_memory: str, minimal_memory: str, repetitions: int) -> dict[str, Any]:
    def version(command: list[str]) -> str:
        return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.strip()

    git_commit = version(["git", "rev-parse", "HEAD"])
    return {
        "benchmark_version": 1,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "random_seed": SEED,
        "repetitions_per_case": repetitions,
        "cases": len(json.loads(CASES_PATH.read_text(encoding="utf-8"))),
        "fresh_session_per_trial": True,
        "counterbalanced_pair_order": True,
        "model": MODEL,
        "thinking": "off",
        "openclaw_version": OPENCLAW_VERSION,
        "deepseek_provider_package": DEEPSEEK_PROVIDER,
        "aetnamem_version": importlib.metadata.version("aetnamem"),
        "aetnamem_git_commit": git_commit,
        "openclaw_plugin_version": json.loads((PLUGIN_PATH / "package.json").read_text())["version"],
        "python": sys.version.split()[0],
        "node": version(["node", "--version"]),
        "platform": platform.platform(),
        "baseline_memory_chars": len(full_memory),
        "baseline_memory_sha256": sha256_bytes(full_memory.encode()),
        "treatment_memory_chars": len(minimal_memory),
        "treatment_memory_sha256": sha256_bytes(minimal_memory.encode()),
        "case_file_sha256": sha256_bytes(CASES_PATH.read_bytes()),
        "harness_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "scoring": "case-insensitive containment of every pre-registered expected fragment",
    }


def markdown_report(payload: dict[str, Any]) -> str:
    meta = payload["metadata"]
    summary = payload["summary"]
    baseline = summary["arms"]["baseline"]
    treatment = summary["arms"]["aetnamem"]
    comparison = summary["comparison"]
    evidence = payload["aetnamem_evidence"]
    return f"""# OpenClaw × AetnaMem DeepSeek benchmark

Run completed: `{meta['completed_at_utc']}`  
Git commit: `{meta['aetnamem_git_commit']}`  
Model: `{meta['model']}` with thinking off  
OpenClaw: `{meta['openclaw_version']}`  
Trials: {comparison['paired_trials']} paired fresh-session tasks ({meta['cases']} cases × {meta['repetitions_per_case']} repetitions)

## Result

| Metric | Native `MEMORY.md` | AetnaMem | Change |
|---|---:|---:|---:|
| Prompt tokens, total | {baseline['prompt_tokens_total']:,} | {treatment['prompt_tokens_total']:,} | **-{comparison['prompt_tokens_saved_total']:,} ({comparison['prompt_token_reduction_percent']:.3f}%)** |
| Prompt tokens, median/trial | {baseline['prompt_tokens_median']:,.1f} | {treatment['prompt_tokens_median']:,.1f} | {comparison['paired_prompt_tokens_saved_median']:,.1f} paired median saved |
| Uncached input tokens, total | {baseline['input_tokens_total']:,} | {treatment['input_tokens_total']:,} | {comparison['uncached_input_tokens_change']:+,} |
| Cache-read tokens, total | {baseline['cache_read_tokens_total']:,} | {treatment['cache_read_tokens_total']:,} | — |
| Correct answers | {baseline['correct']}/{baseline['trials']} | {treatment['correct']}/{treatment['trials']} | — |
| Provider-reported cost | ${baseline['provider_cost_usd_total']:.6f} | ${treatment['provider_cost_usd_total']:.6f} | **-{comparison['provider_cost_reduction_percent']:.3f}%** |
| Median wall latency | {baseline['latency_seconds_median']:.3f}s | {treatment['latency_seconds_median']:.3f}s | — |

The paired mean prompt-token saving was {comparison['paired_prompt_tokens_saved_mean']:,.1f} tokens per turn; the deterministic
10,000-resample paired bootstrap 95% interval was [{comparison['paired_mean_savings_95pct_bootstrap_ci_tokens'][0]:,.1f},
{comparison['paired_mean_savings_95pct_bootstrap_ci_tokens'][1]:,.1f}] tokens. Every treatment trial produced an audited
retrieval event with at least one returned record: `{str(comparison['all_treatment_trials_retrieved_memory']).lower()}`.
Every treatment trial retrieved its pre-registered target record: `{str(comparison['all_treatment_trials_retrieved_target']).lower()}`.
The AetnaMem evidence chain verified after the run: `{str(evidence['audit_chain_valid']).lower()}`
({evidence['audit_events']} audit events, {evidence['retrieval_events']} retrieval events, {evidence['seeded_records']} seeded records).

## Method

The control arm stored the complete {meta['baseline_memory_chars']:,}-character synthetic hospital programme memory in
OpenClaw's always-loaded `MEMORY.md`. The treatment stored the identical facts in AetnaMem and used a
{meta['treatment_memory_chars']:,}-character bootstrap `MEMORY.md`. Both arms used the same OpenClaw release, DeepSeek V4
Flash model, non-thinking mode, workspace scaffold, prompt, scorer, and one fresh session per trial. Pair order alternated
by case and repetition. The scorer required every pre-registered answer fragment in `cases.json`; it was not changed after
responses were observed.

Provider token and cost fields came from each OpenClaw session JSONL. Prompt tokens are the sum of uncached input and
cache-read tokens; reporting only uncached input would incorrectly count a cache hit as removed context. Wall latency surrounds the complete local OpenClaw
process, so it includes plugin/process startup as well as model latency. AetnaMem record IDs and retrieval-event counts are
included in the machine-readable result; full session files remain hash-addressed rather than committed because they include
large OpenClaw system/tool prompts.

## Interpretation and limits

This is an integration benchmark, not a universal savings claim. It measures cross-session factual recall with one model,
one OpenClaw release, a synthetic mature memory, and {comparison['paired_trials']} paired trials. Results will vary with native-memory size,
tool schemas, caching, language, prompt length, and retrieval selectivity. The AetnaMem arm still pays OpenClaw's system/tool
overhead plus bounded persona/recall context. Prompt caching was not credited (`cacheRead` is reported separately), and no
claim is made about long conversations, procedural skill selection, or clinical outcome quality. Independent replication,
additional models, larger task sets, and repeated runs on controlled hardware are required before inferential generalization.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=2, help="paired repetitions per case")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("results"))
    parser.add_argument("--keep-runtime", action="store_true", help="retain isolated OpenClaw profiles for inspection")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        parser.error("DEEPSEEK_API_KEY is required (the value is never written to results)")

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    targets = [case["fact"] for case in cases]
    distractors = distractor_facts()
    labeled_facts = [(case["id"], case["fact"]) for case in cases] + [
        ("distractor", fact) for fact in distractors
    ]
    full_memory = memory_document(targets, distractors)
    minimal_memory = minimal_memory_document()
    base_env = dict(os.environ)

    runtime_parent = Path(tempfile.mkdtemp(prefix="aetnamem-openclaw-bench-"))
    profiles = {arm: runtime_parent / arm for arm in ("baseline", "aetnamem")}
    trials: list[Trial] = []
    retrieval_count = 0
    try:
        configured = {
            arm: configure_profile(
                profiles[arm],
                arm=arm,
                full_memory=full_memory,
                labeled_facts=labeled_facts,
                base_env=base_env,
            )
            for arm in ("baseline", "aetnamem")
        }
        environments = {arm: value[0] for arm, value in configured.items()}
        record_labels = configured["aetnamem"][1]
        for repetition in range(1, args.repetitions + 1):
            for case_index, case in enumerate(cases):
                order = ("baseline", "aetnamem") if (case_index + repetition) % 2 else ("aetnamem", "baseline")
                for order_index, arm in enumerate(order, start=1):
                    trial, retrieval_count = execute_trial(
                        case=case,
                        repetition=repetition,
                        arm=arm,
                        order_in_pair=order_index,
                        profile=profiles[arm],
                        env=environments[arm],
                        retrieval_count=retrieval_count,
                        record_labels=record_labels,
                    )
                    trials.append(trial)
                    print(
                        f"[{len(trials):02d}/{len(cases) * args.repetitions * 2}] "
                        f"{trial.case_id} {trial.arm}: prompt={trial.prompt_tokens} "
                        f"uncached={trial.input_tokens} correct={trial.correct}",
                        flush=True,
                    )

        evidence_memory = Memory(profiles["aetnamem"] / "aetnamem.db")
        try:
            audit = evidence_memory.audit(SUBJECT)
            aetnamem_evidence = {
                "audit_chain_valid": bool(audit["audit_chain_valid"]),
                "audit_events": len(audit["audit_log"]),
                "retrieval_events": len(audit["retrieval_events"]),
                "seeded_records": len(record_labels),
            }
        finally:
            evidence_memory.close()
        payload = {
            "metadata": metadata(full_memory, minimal_memory, args.repetitions),
            "summary": summarize(trials),
            "aetnamem_evidence": aetnamem_evidence,
            "trials": [asdict(trial) for trial in trials],
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        json_path = args.output_dir / f"deepseek-v4-flash-{stamp}.json"
        report_path = args.output_dir / f"deepseek-v4-flash-{stamp}.md"
        json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report_path.write_text(markdown_report(payload), encoding="utf-8")
        print(f"Result: {json_path}")
        print(f"Report: {report_path}")
    finally:
        if args.keep_runtime:
            print(f"Runtime retained: {runtime_parent}")
        else:
            shutil.rmtree(runtime_parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
