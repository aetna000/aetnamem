"""Tamper-evident, content-minimizing flight records for agent runs.

The black box records host-observable boundaries.  It deliberately stores
digests and bounded metadata rather than prompts, responses, tool parameters,
or tool results.  A verified flight proves that the retained timeline was not
rewritten and that observed tool requests reached terminal hook events; it does
not prove an external business outcome unless a system-of-record verifier is
also present.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json
import re
from typing import Any, Mapping

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.store.sqlite import utc_now


EVENT_FORMAT = "aetnamem-agent-blackbox-event-v1"
REPORT_FORMAT = "aetnamem-agent-blackbox-report-v1"
EVIDENCE_KIND = "agent_blackbox"

_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_DIGEST_KEYS = {
    "prompt_sha256",
    "system_sha256",
    "history_sha256",
    "context_sha256",
    "params_sha256",
    "result_sha256",
    "response_sha256",
    "messages_sha256",
}
_TEXT_KEYS = {
    "provider",
    "model",
    "resolved_ref",
    "harness_id",
    "reasoning_effort",
    "mode",
    "exposure_id",
    "tool_name",
    "tool_kind",
    "outcome",
    "error_category",
    "failure_kind",
    "reason",
}
_COUNT_KEYS = {
    "prompt_chars",
    "system_chars",
    "history_count",
    "images_count",
    "tools_count",
    "context_chars",
    "response_chars",
    "response_count",
    "messages_count",
    "duration_ms",
    "request_payload_bytes",
    "response_stream_bytes",
    "time_to_first_byte_ms",
}
_BOOL_KEYS = {"fast_mode", "cancelled", "success"}
_LIST_KEYS = {"candidate_ids", "param_keys", "derived_path_sha256"}


def normalize_event(
    *,
    migration_id: str,
    host: str,
    event_type: str,
    run_id: str,
    session_id: str | None,
    tool_call_id: str | None,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate a host event and return the canonical stored envelope."""

    event_name = event_type.strip()
    if not _EVENT_TYPE.fullmatch(event_name):
        raise ValueError("blackbox event_type is invalid")
    run = run_id.strip()
    if not run or len(run) > 512:
        raise ValueError("blackbox run_id is required and must be at most 512 characters")
    return {
        "format": EVENT_FORMAT,
        "migration_id": migration_id,
        "host": host,
        "event_type": event_name,
        "run_id": run,
        "session_id": _bounded_optional(session_id, 512),
        "tool_call_id": _bounded_optional(tool_call_id, 512),
        "recorded_at": utc_now(),
        "payload": _normalize_payload(payload or {}),
        "content_storage": "digests-and-bounded-metadata-only",
    }


def flight_runs(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        body = entry.get("body") or {}
        run_id = str(body.get("run_id") or "")
        if run_id:
            grouped[run_id].append(entry)
    rows: list[dict[str, Any]] = []
    for run_id, values in grouped.items():
        values.sort(key=lambda item: int(item.get("sequence") or 0))
        bodies = [item["body"] for item in values]
        event_types = [str(body.get("event_type") or "") for body in bodies]
        rows.append(
            {
                "run_id": run_id,
                "session_id": next(
                    (body.get("session_id") for body in bodies if body.get("session_id")),
                    None,
                ),
                "started_at": bodies[0].get("recorded_at"),
                "ended_at": bodies[-1].get("recorded_at"),
                "events": len(values),
                "tool_requests": event_types.count("tool.requested"),
                "tool_completions": event_types.count("tool.completed"),
                "terminal": "turn.ended" in event_types,
                "last_sequence": int(values[-1].get("sequence") or 0),
            }
        )
    rows.sort(key=lambda row: (str(row["ended_at"] or ""), row["run_id"]), reverse=True)
    return rows


def verify_flight(
    *,
    run_id: str,
    entries: list[dict[str, Any]],
    chain: Mapping[str, Any],
) -> dict[str, Any]:
    selected = [
        entry
        for entry in entries
        if str((entry.get("body") or {}).get("run_id") or "") == run_id
    ]
    selected.sort(key=lambda item: int(item.get("sequence") or 0))
    if not selected:
        raise ValueError(f"no blackbox flight found for run {run_id}")

    requested: dict[str, dict[str, Any]] = {}
    completed: dict[str, dict[str, Any]] = {}
    uncorrelated_requests = 0
    uncorrelated_completions = 0
    tool_errors: list[dict[str, Any]] = []
    for entry in selected:
        body = entry["body"]
        event_type = str(body.get("event_type") or "")
        call_id = str(body.get("tool_call_id") or "")
        if event_type == "tool.requested":
            if call_id:
                requested[call_id] = entry
            else:
                uncorrelated_requests += 1
        elif event_type == "tool.completed":
            if call_id:
                completed[call_id] = entry
            else:
                uncorrelated_completions += 1
            payload = body.get("payload") or {}
            if payload.get("outcome") == "error":
                tool_errors.append(
                    {
                        "tool_call_id": call_id or None,
                        "tool_name": payload.get("tool_name"),
                        "error_category": payload.get("error_category"),
                    }
                )

    missing_completions = sorted(set(requested) - set(completed))
    orphan_completions = sorted(set(completed) - set(requested))
    event_types = [str(entry["body"].get("event_type") or "") for entry in selected]
    terminal = "turn.ended" in event_types
    model_input = "model.input" in event_types
    model_output = "model.output" in event_types
    response_bound = any(
        (entry["body"].get("payload") or {}).get("response_sha256")
        for entry in selected
        if entry["body"].get("event_type") == "model.output"
    )
    structurally_complete = bool(
        chain.get("valid")
        and terminal
        and not missing_completions
        and not orphan_completions
        and not uncorrelated_requests
        and not uncorrelated_completions
    )
    if not chain.get("valid"):
        verdict = "tampered_or_invalid_chain"
    elif not structurally_complete:
        verdict = "incomplete_evidence"
    elif tool_errors:
        verdict = "completed_with_tool_errors"
    elif requested:
        verdict = "observed_tools_reached_terminal_events"
    else:
        verdict = "no_tool_actions_observed"

    timeline = [
        {
            "sequence": int(entry.get("sequence") or 0),
            "entry_sha256": entry.get("entry_sha256"),
            **deepcopy(entry["body"]),
        }
        for entry in selected
    ]
    report_body = {
        "format": REPORT_FORMAT,
        "generated_at": utc_now(),
        "run_id": run_id,
        "session_id": next(
            (
                entry["body"].get("session_id")
                for entry in selected
                if entry["body"].get("session_id")
            ),
            None,
        ),
        "verdict": verdict,
        "timeline_chain_valid": bool(chain.get("valid")),
        "structurally_complete": structurally_complete,
        "coverage": {
            "model_input_observed": model_input,
            "model_output_observed": model_output,
            "response_digest_bound": bool(response_bound),
            "terminal_event_observed": terminal,
        },
        "tools": {
            "requested": len(requested) + uncorrelated_requests,
            "completed": len(completed) + uncorrelated_completions,
            "errors": tool_errors,
            "missing_completions": missing_completions,
            "orphan_completions": orphan_completions,
            "uncorrelated_requests": uncorrelated_requests,
            "uncorrelated_completions": uncorrelated_completions,
        },
        "events": len(selected),
        "first_sequence": int(selected[0].get("sequence") or 0),
        "last_sequence": int(selected[-1].get("sequence") or 0),
        "timeline": timeline,
        "claim_boundary": (
            "This report verifies retained timeline integrity and observed hook closure. "
            "It does not prove that an external real-world outcome occurred, and it does "
            "not semantically validate claims in the agent response."
        ),
        "raw_content_stored": False,
    }
    return {
        **report_body,
        "report_sha256": sha256_hex(canonical_json(report_body)),
    }


def format_flight_report(report: Mapping[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    tools = report.get("tools") or {}
    lines = [
        "AetnaMem Agent Black Box",
        "",
        f"Run: {report.get('run_id')}",
        f"Verdict: {str(report.get('verdict') or '').replace('_', ' ')}",
        f"Evidence chain: {'VALID' if report.get('timeline_chain_valid') else 'INVALID'}",
        f"Events: {report.get('events', 0)}",
        f"Tool requests: {tools.get('requested', 0)}",
        f"Tool completions: {tools.get('completed', 0)}",
        f"Tool errors: {len(tools.get('errors') or [])}",
        f"Model input observed: {'yes' if coverage.get('model_input_observed') else 'no'}",
        f"Model output observed: {'yes' if coverage.get('model_output_observed') else 'no'}",
        f"Final response digest bound: {'yes' if coverage.get('response_digest_bound') else 'no'}",
        "",
        "Timeline",
    ]
    for event in report.get("timeline") or []:
        payload = event.get("payload") or {}
        detail = payload.get("tool_name") or payload.get("model") or ""
        outcome = payload.get("outcome") or ""
        suffix = " · ".join(value for value in (str(detail), str(outcome)) if value)
        lines.append(
            f"{event.get('sequence'):>5}  {event.get('recorded_at')}  "
            f"{event.get('event_type')}" + (f"  {suffix}" if suffix else "")
        )
    lines.extend(["", str(report.get("claim_boundary") or "")])
    return "\n".join(lines) + "\n"


def _normalize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(
        set(payload)
        - _DIGEST_KEYS
        - _TEXT_KEYS
        - _COUNT_KEYS
        - _BOOL_KEYS
        - _LIST_KEYS
        - {"usage"}
    )
    if unknown:
        raise ValueError(f"unsupported blackbox payload field(s): {', '.join(unknown)}")
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if key in _DIGEST_KEYS:
            text = str(value).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", text):
                raise ValueError(f"{key} must be a SHA-256 digest")
            normalized[key] = text
        elif key in _TEXT_KEYS:
            normalized[key] = str(value)[:512]
        elif key in _COUNT_KEYS:
            normalized[key] = max(0, int(value))
        elif key in _BOOL_KEYS:
            normalized[key] = bool(value)
        elif key in _LIST_KEYS:
            if not isinstance(value, list):
                raise ValueError(f"{key} must be an array")
            normalized[key] = [str(item)[:1024] for item in value[:100]]
        elif key == "usage":
            if not isinstance(value, Mapping):
                raise ValueError("usage must be an object")
            normalized[key] = {
                name: max(0, int(amount))
                for name, amount in value.items()
                if name in {"input", "output", "cacheRead", "cacheWrite", "total"}
                and amount is not None
            }
    return normalized


def _bounded_optional(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None
