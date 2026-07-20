from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


_PATH = Path(__file__).parents[1] / "bench" / "openclaw_memory" / "run_benchmark.py"
_SPEC = spec_from_file_location("openclaw_memory_benchmark", _PATH)
assert _SPEC and _SPEC.loader
benchmark = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = benchmark
_SPEC.loader.exec_module(benchmark)


def test_scorer_normalizes_percent_notation_and_case() -> None:
    assert benchmark.score("Rollback after TWO windows at 2.5%.", ["two windows", "2.5 percent"])
    assert not benchmark.score("Rollback after one window at 2.5%.", ["two windows", "2.5 percent"])


def test_generated_memory_is_stable_and_substantive() -> None:
    facts = benchmark.distractor_facts()
    assert len(facts) == 84
    assert facts == benchmark.distractor_facts()
    document = benchmark.memory_document(["The CEDAR threshold is 2.5 percent."], facts)
    assert len(document) > 15_000
    assert "AUX-084" in document


def test_session_discovery_excludes_trajectory_companions(tmp_path: Path) -> None:
    sessions = tmp_path / "agents" / "main" / "sessions"
    sessions.mkdir(parents=True)
    canonical = sessions / "abc.jsonl"
    canonical.touch()
    (sessions / "abc.trajectory.jsonl").touch()
    assert benchmark.session_files(tmp_path) == {canonical}


def test_summary_uses_paired_token_differences() -> None:
    common = dict(
        repetition=1,
        order_in_pair=1,
        session_key="s",
        answer="ok",
        expected=["ok"],
        correct=True,
        latency_seconds=1.0,
        prompt_tokens=100,
        output_tokens=2,
        cache_read_tokens=0,
        cache_write_tokens=0,
        total_tokens=102,
        provider_cost_usd=0.01,
        model="deepseek-v4-flash",
        provider="deepseek",
        retrieval_event_count=1,
        retrieval_candidate_count=1,
        retrieved_record_ids=["rec_1"],
        retrieved_labels=["a"],
        target_record_retrieved=True,
        session_log_sha256="0" * 64,
    )
    trials = [
        benchmark.Trial(case_id="a", arm="baseline", input_tokens=100, **common),
        benchmark.Trial(case_id="a", arm="aetnamem", input_tokens=70, **common),
    ]
    trials[1].prompt_tokens = 70
    result = benchmark.summarize(trials)
    assert result["comparison"]["prompt_tokens_saved_total"] == 30
    assert result["comparison"]["prompt_token_reduction_percent"] == 30.0
