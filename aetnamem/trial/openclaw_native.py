from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable, Iterable

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.memory import Memory
from aetnamem.store.sqlite import utc_now
from aetnamem.trial.models import TrialState
from aetnamem.trial.store import TrialStore

MIRROR_DB_NAME = "openclaw-mirror.db"
MIRROR_MANIFEST_NAME = "openclaw-mirror.json"
CUTOVER_NAME = "openclaw-cutover.json"
NATIVE_SNAPSHOT_MANIFEST_NAME = "openclaw-native-snapshot.json"
NATIVE_BASELINE_NAME = "openclaw-native-baseline"
NATIVE_BASELINE_MANIFEST_NAME = "openclaw-native-baseline.json"
SHADOW_HISTORY_NAME = "openclaw-shadow-history"
DEFAULT_RECALL_CHARS = 1200
NATIVE_MEMORY_ROOTS = (
    "MEMORY.md",
    "memory",
    "USER.md",
    "AGENTS.md",
    "TOOLS.md",
    "SOUL.md",
    "IDENTITY.md",
    "HEARTBEAT.md",
    "skills",
)
SUPPLEMENTAL_MEMORY_ROOTS = ("MEMORY.md", "memory")
ProgressReporter = Callable[[int, int, str], None]


@dataclass(frozen=True)
class NativeSource:
    path: Path
    relative_path: str
    plane: str
    pinned: bool


def discover_workspace(openclaw: str | None = None) -> Path:
    executable = openclaw or shutil.which("openclaw")
    if executable:
        result = subprocess.run(
            [executable, "memory", "status", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
                rows = payload if isinstance(payload, list) else [payload]
                for row in rows:
                    status = row.get("status") if isinstance(row, dict) else None
                    workspace = (
                        status.get("workspaceDir") if isinstance(status, dict) else None
                    )
                    if isinstance(workspace, str) and workspace.strip():
                        return Path(workspace).expanduser().resolve()
            except json.JSONDecodeError:
                pass
    return (Path.home() / ".openclaw" / "workspace").resolve()


def discover_sources(workspace: str | Path) -> list[NativeSource]:
    root = Path(workspace).expanduser().resolve()
    sources: list[NativeSource] = []

    def add(path: Path, plane: str, *, pinned: bool = False) -> None:
        if path.is_file() and not path.is_symlink():
            sources.append(
                NativeSource(
                    path=path,
                    relative_path=path.relative_to(root).as_posix(),
                    plane=plane,
                    pinned=pinned,
                )
            )

    add(root / "MEMORY.md", "semantic")
    add(root / "USER.md", "semantic", pinned=True)
    for path in sorted((root / "memory").glob("**/*.md")):
        add(path, "episodic")
    for name in ("AGENTS.md", "TOOLS.md", "SOUL.md", "IDENTITY.md", "HEARTBEAT.md"):
        add(root / name, "procedural", pinned=True)
    for path in sorted((root / "skills").glob("**/SKILL.md")):
        add(path, "procedural", pinned=True)
    return sources


def sync_mirror(
    state: TrialState,
    *,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    root = (
        Path(workspace).expanduser().resolve()
        if workspace is not None
        else discover_workspace()
    )
    trial_dir = Path(state.trial_dir)
    mirror_path = trial_dir / MIRROR_DB_NAME
    manifest_path = trial_dir / MIRROR_MANIFEST_NAME
    baseline = _ensure_native_baseline(trial_dir, root)
    shadow_history = _record_shadow_version(trial_dir, root, baseline)
    snapshot_root = Path(str(shadow_history["snapshot_root"]))
    sources = discover_sources(snapshot_root)
    source_rows = [_source_row(source) for source in sources]
    for source_row in source_rows:
        relative_path = str(source_row["relative_path"])
        source_row["snapshot_path"] = source_row["path"]
        source_row["path"] = str(root / relative_path)
    manifest_sha256 = sha256_hex(
        canonical_json(
            {
                "format": "aetnamem-openclaw-native-manifest-v1",
                "workspace": str(root),
                "sources": source_rows,
            }
        )
    )
    previous = _read_json(manifest_path)
    if (
        previous
        and previous.get("manifest_sha256") == manifest_sha256
        and mirror_path.is_file()
    ):
        previous["native_baseline"] = _snapshot_summary(baseline)
        previous["shadow_history"] = shadow_history
        _private_json(manifest_path, previous)
        return _mirror_status_from_manifest(previous, mirror_path)

    build_path = trial_dir / f".{MIRROR_DB_NAME}.building"
    _remove_sqlite_files(build_path)
    memory = Memory(build_path)
    imported_records = 0
    imported_chunks = 0
    try:
        for source, source_row in zip(sources, source_rows):
            text = source.path.read_text(encoding="utf-8", errors="replace")
            for chunk in _markdown_chunks(text):
                result = memory.remember(
                    state.subject_id,
                    fact=chunk["text"],
                    force=True,
                    session_id=f"openclaw-native:{source.relative_path}",
                    turn_id=str(source_row["sha256"])[:16],
                    source_type="user_message",
                    actor="openclaw-shadow-import",
                    raw={
                        "format": "aetnamem-openclaw-native-source-v1",
                        "source_path": str(root / source.relative_path),
                        "snapshot_path": str(source.path),
                        "relative_path": source.relative_path,
                        "source_sha256": source_row["sha256"],
                        "line_start": chunk["line_start"],
                        "line_end": chunk["line_end"],
                        "plane": source.plane,
                        "pinned": source.pinned,
                    },
                )
                imported_records += len(result.get("records") or [])
                imported_chunks += 1
        memory.store.append_audit_event(
            subject_id=state.subject_id,
            event_type="host.memory_mirror_synchronized",
            actor="openclaw-shadow-import",
            payload={
                "trial_id": state.trial_id,
                "workspace_sha256": sha256_hex(str(root)),
                "manifest_sha256": manifest_sha256,
                "source_count": len(source_rows),
                "source_bytes": sum(int(row["bytes"]) for row in source_rows),
                "imported_chunks": imported_chunks,
                "record_count": imported_records,
            },
        )
        verification = memory.verify()
        if not verification.get("valid"):
            raise ValueError("AetnaMem mirror audit verification failed")
        memory.store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        memory.close()

    _remove_sqlite_sidecars(build_path)
    os.replace(build_path, mirror_path)
    _remove_sqlite_sidecars(mirror_path)
    native_memory_chars = sum(
        int(row["bytes"]) for row in source_rows if row["relative_path"] == "MEMORY.md"
    )
    manifest = {
        "format": "aetnamem-openclaw-mirror-v1",
        "trial_id": state.trial_id,
        "subject_id": state.subject_id,
        "workspace": str(root),
        "mirror_db": str(mirror_path),
        "manifest_sha256": manifest_sha256,
        "source_count": len(source_rows),
        "source_bytes": sum(int(row["bytes"]) for row in source_rows),
        "native_memory_chars": native_memory_chars,
        "imported_chunks": imported_chunks,
        "record_count": imported_records,
        "sources": source_rows,
        "native_baseline": _snapshot_summary(baseline),
        "shadow_history": shadow_history,
        "synced_at": utc_now(),
    }
    _private_json(manifest_path, manifest)
    return _mirror_status_from_manifest(manifest, mirror_path)


def mirror_status(state: TrialState, *, refresh: bool = True) -> dict[str, Any]:
    trial_dir = Path(state.trial_dir)
    manifest = _read_json(trial_dir / MIRROR_MANIFEST_NAME)
    cutover = _read_json(trial_dir / CUTOVER_NAME)
    takeover_active = bool(
        cutover and cutover.get("status") in {"active", "emergency_off"}
    )
    if refresh and state.host == "openclaw" and not takeover_active:
        try:
            return sync_mirror(
                state,
                workspace=(
                    manifest.get("workspace") if isinstance(manifest, dict) else None
                ),
            )
        except Exception as exc:
            return {
                "status": "error",
                "synced": False,
                "error": str(exc),
                "mirror_db": str(Path(state.trial_dir) / MIRROR_DB_NAME),
            }
    if not manifest:
        return {
            "status": "not_started",
            "synced": False,
            "mirror_db": str(Path(state.trial_dir) / MIRROR_DB_NAME),
        }
    return _mirror_status_from_manifest(
        manifest, Path(state.trial_dir) / MIRROR_DB_NAME
    )


def search_mirror(
    state: TrialState,
    query: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    status = mirror_status(state)
    if not status.get("synced"):
        raise ValueError(status.get("error") or "OpenClaw mirror is not synchronized")
    memory = Memory(status["mirror_db"], retain_query_text=True)
    try:
        records = memory.recall(
            state.subject_id,
            query,
            session_id=f"trial:{state.trial_id}:investigator",
            limit=max(1, min(int(limit), 100)),
            min_score=0.3,
        )
        episodes = {
            str(row["id"]): row for row in memory.store.list_episodes(state.subject_id)
        }
        for record in records:
            record["match_excerpt"] = _focused_excerpt(
                str(record.get("content") or ""), query
            )
            episode = episodes.get(str(record.get("episode_id") or ""))
            raw = episode.get("raw") if isinstance(episode, dict) else None
            if isinstance(raw, dict) and raw.get("format") in {
                "aetnamem-openclaw-native-source-v1",
                "aetnamem-safe-switch-approved-source-v1",
            }:
                record["openclaw_provenance"] = raw
        return {
            "format": "aetnamem-openclaw-mirror-search-v1",
            "query": query,
            "subject_id": state.subject_id,
            "manifest_sha256": status.get("manifest_sha256"),
            "count": len(records),
            "records": records,
        }
    finally:
        memory.close()


def _focused_excerpt(content: str, query: str, *, max_chars: int = 220) -> str:
    """Return the smallest useful sentence or bullet matching the query."""

    compact = " ".join(content.split())
    if not compact:
        return ""
    terms = tuple(
        dict.fromkeys(
            token
            for token in re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
            if token
        )
    )
    fragments = [
        fragment.strip("-*• \t")
        for fragment in re.split(
            r"(?<=[.!?])\s+|\n+|\s+-\s+(?=\S)",
            content,
        )
        if fragment.strip("-*• \t")
    ]
    query_folded = " ".join(query.casefold().split())

    def score(fragment: str) -> tuple[int, int, int]:
        folded = fragment.casefold()
        return (
            int(bool(query_folded and query_folded in folded)),
            sum(term in folded for term in terms),
            -len(fragment),
        )

    matching = [
        fragment
        for fragment in fragments
        if not terms or any(term in fragment.casefold() for term in terms)
    ]
    excerpt = max(matching, key=score) if matching else compact
    if len(excerpt) <= max_chars:
        return excerpt
    shortened = excerpt[: max(1, max_chars - 1)].rsplit(" ", 1)[0].rstrip()
    return (shortened or excerpt[: max_chars - 1]).rstrip() + "…"


def trace_mirror(
    state: TrialState,
    query: str,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    from aetnamem.investigate import trace_evidence

    status = mirror_status(state)
    if not status.get("synced"):
        raise ValueError(status.get("error") or "OpenClaw mirror is not synchronized")
    memory = Memory(status["mirror_db"], retain_query_text=True)
    try:
        return trace_evidence(
            memory,
            state.subject_id,
            query,
            limit=max(1, min(int(limit), 200)),
            audit_access=True,
            access_actor="openclaw-local-operator",
        )
    finally:
        memory.close()


def activate_takeover(
    state: TrialState,
    state_path: str | Path,
    *,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    report = progress or (lambda _step, _total, _label: None)
    total_steps = 8
    report(1, total_steps, "Verifying the OpenClaw memory mirror")
    if state.host != "openclaw":
        raise ValueError("native-memory takeover is currently implemented for OpenClaw")
    status = sync_mirror(state)
    if not status.get("synced") or int(status.get("record_count") or 0) < 1:
        raise ValueError("OpenClaw memory mirror is empty or failed verification")
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError("OpenClaw is not on PATH")
    report(2, total_steps, "Checking OpenClaw memory capabilities")
    capability_report = inspect_native_memory_capabilities(executable)
    if not capability_report["safe_to_switch"]:
        details = "; ".join(capability_report["blocking_reasons"])
        raise ValueError(
            "OpenClaw memory takeover stopped because configured native "
            f"capabilities would be lost: {details}"
        )

    trial_dir = Path(state.trial_dir)
    cutover_path = trial_dir / CUTOVER_NAME
    if cutover_path.exists():
        current = _read_json(cutover_path) or {}
        if current.get("status") == "active":
            return _cutover_public(current)
        if current.get("status") in {"rolled_back", "rolled_back_after_failure"}:
            _archive_completed_cutover(trial_dir, current)
        else:
            status_name = str(current.get("status") or "unknown")
            raise ValueError(
                "AetnaMem found an interrupted OpenClaw switch "
                f"(status: {status_name}). Native memory may already be "
                "frozen. Choose Restore OpenClaw in the dashboard or run "
                "`aetnamem trial rollback`; restoration verifies the saved "
                "files before another activation is allowed."
            )

    workspace = Path(str(status["workspace"]))
    archive = _new_cutover_archive(trial_dir)
    prior_slot = _optional_json(
        [executable, "config", "get", "plugins.slots.memory", "--json"]
    )
    prior_session_hook = _optional_json(
        [
            executable,
            "config",
            "get",
            "hooks.internal.entries.session-memory",
            "--json",
        ]
    )
    prior_plugin_entry = _optional_json(
        [
            executable,
            "config",
            "get",
            "plugins.entries.memory-aetnamem",
            "--json",
        ]
    )
    cutover: dict[str, Any] = {
        "format": "aetnamem-openclaw-cutover-v1",
        "trial_id": state.trial_id,
        "status": "preparing",
        "workspace": str(workspace),
        "mirror_db": status["mirror_db"],
        "manifest_sha256": status["manifest_sha256"],
        "archive": str(archive),
        "prior_memory_slot": prior_slot,
        "prior_session_memory_hook": prior_session_hook,
        "prior_plugin_entry": prior_plugin_entry,
        "relocated": [],
        "approved_candidates_merged": 0,
        "native_capability_report": capability_report,
        "created_at": utc_now(),
    }
    _private_json(cutover_path, cutover)
    try:
        # Quiesce the native writer before the final mirror and snapshot. The
        # gateway is restarted below on success and in the failure path.
        report(3, total_steps, "Pausing OpenClaw memory writes")
        _run([executable, "gateway", "stop"])
        report(4, total_steps, "Taking the final searchable memory snapshot")
        status = sync_mirror(state, workspace=workspace)
        if not status.get("synced") or int(status.get("record_count") or 0) < 1:
            raise ValueError("final OpenClaw memory mirror failed verification")
        promoted_candidates = _merge_approved_trial_candidates(
            state, status["mirror_db"]
        )
        archive.mkdir(mode=0o700, exist_ok=False)
        native_snapshot = _snapshot_native_memory(workspace, archive)
        shadow_history = status.get("shadow_history")
        shadow_history = shadow_history if isinstance(shadow_history, dict) else {}
        if native_snapshot["snapshot_sha256"] != shadow_history.get(
            "latest_observed_sha256"
        ):
            raise ValueError(
                "switch-time snapshot does not match the final searchable mirror"
            )
        _private_json(
            trial_dir / NATIVE_SNAPSHOT_MANIFEST_NAME,
            native_snapshot,
        )
        cutover.update(
            {
                "mirror_db": status["mirror_db"],
                "manifest_sha256": status["manifest_sha256"],
                "native_snapshot": native_snapshot,
                "native_snapshot_verified": True,
                "approved_candidates_merged": promoted_candidates,
            }
        )
        _private_json(cutover_path, cutover)

        if _tree_manifest(workspace, NATIVE_MEMORY_ROOTS) != native_snapshot["entries"]:
            raise ValueError(
                "OpenClaw native memory changed after the switch-time snapshot"
            )
        report(5, total_steps, "Freezing native supplemental memory")
        for relative in SUPPLEMENTAL_MEMORY_ROOTS:
            source = workspace / relative
            if not source.exists():
                continue
            cutover["relocated"].append(relative)
            _private_json(cutover_path, cutover)
            if source.is_dir():
                shutil.rmtree(source)
            else:
                source.unlink()

        report(6, total_steps, "Configuring AetnaMem as the memory provider")
        _run([executable, "hooks", "disable", "session-memory"], allow_missing=True)
        _set_json(executable, "plugins.slots.memory", "none")
        base = "plugins.entries.memory-aetnamem"
        _set_json(executable, f"{base}.config.safeSwitch", {"enabled": False})
        _set_json(executable, f"{base}.config.takeoverActive", True)
        _set_json(executable, f"{base}.config.nativeWorkspace", str(workspace))
        _set_json(executable, f"{base}.config.dbPath", status["mirror_db"])
        _set_json(executable, f"{base}.config.subject", state.subject_id)
        _set_json(executable, f"{base}.hooks.allowConversationAccess", True)
        _set_json(
            executable,
            f"{base}.config.capture",
            {
                "enabled": True,
                "captureAssistant": True,
            },
        )
        _set_json(
            executable,
            f"{base}.config.recall",
            {
                "enabled": True,
                "maxRecords": 3,
                "maxChars": DEFAULT_RECALL_CHARS,
                "minScore": 0.3,
                "timeoutMs": 4000,
            },
        )
        _set_json(executable, f"{base}.enabled", True)
        report(7, total_steps, "Restarting OpenClaw")
        _run([executable, "gateway", "restart"])
        gateway = _json_command(
            [executable, "gateway", "status", "--require-rpc", "--json"]
        )
        rpc = gateway.get("rpc") if isinstance(gateway, dict) else None
        if not isinstance(rpc, dict) or rpc.get("ok") is not True:
            raise ValueError("OpenClaw gateway RPC did not verify after cutover")
        plugin_runtime = _json_command(
            [
                executable,
                "plugins",
                "inspect",
                "memory-aetnamem",
                "--runtime",
                "--json",
            ]
        )
        plugin = (
            plugin_runtime.get("plugin") if isinstance(plugin_runtime, dict) else None
        )
        tool_names = (
            set(plugin.get("toolNames") or []) if isinstance(plugin, dict) else set()
        )
        required_tools = {"memory_search", "memory_get"}
        typed_hooks = {
            str(row.get("name"))
            for row in plugin_runtime.get("typedHooks", [])
            if isinstance(row, dict)
        }
        required_hooks = {
            "before_prompt_build",
            "agent_end",
            "before_message_write",
            "before_tool_call",
        }
        protected_workspace = _optional_json(
            [
                executable,
                "config",
                "get",
                f"{base}.config.nativeWorkspace",
                "--json",
            ]
        )
        if (
            not isinstance(plugin, dict)
            or plugin.get("status") != "loaded"
            or not required_tools.issubset(tool_names)
            or not required_hooks.issubset(typed_hooks)
            or protected_workspace != str(workspace)
        ):
            raise ValueError(
                "AetnaMem OpenClaw runtime did not verify the standard "
                "memory tools, capture/injection hooks, and native-path guard"
            )
        report(8, total_steps, "Verified memory tools, capture, and native write guard")
        cutover.update(
            {
                "status": "active",
                "activated_at": utc_now(),
                "native_memory_frozen": True,
                "native_snapshot_verified": True,
                "native_memory_slot": "none",
                "session_memory_hook": "disabled",
                "gateway_verified": True,
                "compatibility_tools": ["memory_search", "memory_get"],
                "compatibility_tools_verified": True,
                "capture_hooks_verified": True,
                "native_write_guard_verified": True,
            }
        )
        _private_json(cutover_path, cutover)
        return _cutover_public(cutover)
    except Exception:
        _restore_cutover(cutover, executable=executable)
        _run([executable, "gateway", "restart"], allow_missing=True)
        cutover["status"] = "rolled_back_after_failure"
        cutover["rolled_back_at"] = utc_now()
        _private_json(cutover_path, cutover)
        raise


def restore_takeover(
    state: TrialState,
    *,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    report = progress or (lambda _step, _total, _label: None)
    total_steps = 4
    report(1, total_steps, "Checking the frozen OpenClaw snapshot")
    cutover_path = Path(state.trial_dir) / CUTOVER_NAME
    cutover = _read_json(cutover_path)
    if not cutover:
        return {"restored": True, "takeover_present": False}
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError("OpenClaw is not on PATH; native memory was not restored")
    report(2, total_steps, "Preserving any post-switch native files")
    _restore_cutover(cutover, executable=executable)
    report(3, total_steps, "Returning active-period memories to OpenClaw")
    active_export = _export_active_memories_to_native(
        cutover,
        subject_id=state.subject_id,
    )
    cutover["active_memory_export"] = active_export
    cutover["status"] = "rolled_back"
    cutover["rolled_back_at"] = utc_now()
    _private_json(cutover_path, cutover)
    report(4, total_steps, "OpenClaw native memory restored and verified")
    return {
        "restored": True,
        "takeover_present": True,
        "native_memory_restored": True,
        "manifest_sha256": cutover.get("manifest_sha256"),
        "active_memory_export": active_export,
        "post_switch_native_preserved": cutover.get(
            "post_switch_native_preserved", []
        ),
    }


def emergency_off_takeover(state: TrialState) -> dict[str, Any]:
    cutover = _read_json(Path(state.trial_dir) / CUTOVER_NAME)
    if not cutover or cutover.get("status") != "active":
        return {"takeover_present": bool(cutover), "plugin_disabled": False}
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError("OpenClaw is not on PATH; AetnaMem plugin was not disabled")
    _set_json(executable, "plugins.entries.memory-aetnamem.enabled", False)
    _run([executable, "gateway", "restart"])
    cutover["status"] = "emergency_off"
    cutover["emergency_off_at"] = utc_now()
    _private_json(Path(state.trial_dir) / CUTOVER_NAME, cutover)
    return {
        "takeover_present": True,
        "plugin_disabled": True,
        "native_memory_frozen": True,
        "next": "Run `aetnamem trial rollback` to restore native OpenClaw memory.",
    }


def restart_and_verify_gateway() -> dict[str, Any]:
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError("OpenClaw is not on PATH")
    _run([executable, "gateway", "restart"])
    gateway = _json_command(
        [executable, "gateway", "status", "--require-rpc", "--json"]
    )
    rpc = gateway.get("rpc") if isinstance(gateway, dict) else None
    if not isinstance(rpc, dict) or rpc.get("ok") is not True:
        raise ValueError("OpenClaw gateway RPC verification failed")
    return {"restarted": True, "verified": True}


def takeover_status(state: TrialState) -> dict[str, Any]:
    cutover = _read_json(Path(state.trial_dir) / CUTOVER_NAME)
    return (
        _cutover_public(cutover)
        if cutover
        else {
            "status": "shadow",
            "active": False,
            "native_memory_frozen": False,
        }
    )


def inspect_native_memory_capabilities(
    executable: str | None = None,
) -> dict[str, Any]:
    """Find explicitly configured native features a takeover cannot preserve.

    Missing keys mean OpenClaw defaults. Those defaults are covered by the
    AetnaMem mirror, standard memory_search/memory_get aliases, continuous
    capture, and verified rollback. Explicit extra corpora or native
    experimental pipelines must never disappear silently.
    """

    command = executable or shutil.which("openclaw")
    if command is None:
        raise ValueError("OpenClaw is not on PATH")
    checks = {
        "default_memory_search": "agents.defaults.memorySearch",
        "agent_overrides": "agents.list",
        "memory_config": "memory",
        "memory_core": "plugins.entries.memory-core",
        "memory_wiki": "plugins.entries.memory-wiki",
        "active_memory": "plugins.entries.active-memory",
    }
    configured = {
        name: _optional_json([command, "config", "get", key, "--json"])
        for name, key in checks.items()
    }
    reasons: list[str] = []

    def inspect_search(value: Any, label: str) -> None:
        if not isinstance(value, dict):
            return
        sources = value.get("sources")
        if isinstance(sources, list) and any(str(item) != "memory" for item in sources):
            reasons.append(f"{label} indexes non-memory sources: {sources}")
        if value.get("extraPaths"):
            reasons.append(f"{label} uses extraPaths")
        experimental = value.get("experimental")
        if isinstance(experimental, dict) and experimental.get("sessionMemory") is True:
            reasons.append(f"{label} indexes session transcripts")
        if value.get("backend") == "qmd":
            reasons.append(f"{label} uses the qmd backend")
        if value.get("multimodal"):
            reasons.append(f"{label} enables native multimodal indexing")

    inspect_search(configured["default_memory_search"], "agents.defaults.memorySearch")
    agents = configured["agent_overrides"]
    if isinstance(agents, list):
        for agent in agents:
            if isinstance(agent, dict):
                inspect_search(
                    agent.get("memorySearch"),
                    f"agent {agent.get('id') or '<unknown>'} memorySearch",
                )
    memory_config = configured["memory_config"]
    if isinstance(memory_config, dict):
        if memory_config.get("backend") == "qmd":
            reasons.append("memory.backend is qmd")
        if memory_config.get("multimodal"):
            reasons.append("memory.multimodal is configured")
    core = configured["memory_core"]
    if isinstance(core, dict):
        core_config = core.get("config")
        if isinstance(core_config, dict) and core_config.get("dreaming"):
            reasons.append("memory-core dreaming is configured")
    for name, label in (
        ("memory_wiki", "memory-wiki corpus"),
        ("active_memory", "active-memory plugin"),
    ):
        value = configured[name]
        if isinstance(value, dict) and value.get("enabled") is not False:
            reasons.append(f"{label} is enabled")

    return {
        "format": "aetnamem-openclaw-capability-check-v1",
        "safe_to_switch": not reasons,
        "blocking_reasons": reasons,
        "preserved": [
            "MEMORY.md and memory/*.md imported with provenance",
            "standard memory_search tool",
            "standard memory_get tool",
            "continuous authenticated-user capture",
            "pre-switch native files and configuration rollback",
        ],
        "configured": configured,
    }


def _restore_cutover(cutover: dict[str, Any], *, executable: str) -> None:
    workspace = Path(str(cutover["workspace"]))
    archive = Path(str(cutover["archive"]))
    preservation_root: Path | None = None
    preserved: list[dict[str, Any]] = list(
        cutover.get("post_switch_native_preserved") or []
    )
    for relative in reversed(list(cutover.get("relocated") or [])):
        source = archive / relative
        destination = workspace / relative
        if not source.exists():
            continue
        if destination.exists():
            expected = _tree_manifest(archive, (relative,))
            actual = _tree_manifest(workspace, (relative,))
            if actual != expected:
                if preservation_root is None:
                    preservation_root = _new_preservation_root(archive.parent)
                preserved_path = preservation_root / relative
                preserved_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.move(str(destination), str(preserved_path))
                preserved.append(
                    {
                        "relative_path": relative,
                        "preserved_path": str(preserved_path),
                        "entries": actual,
                    }
                )
            else:
                continue
        _copy_native_path(source, destination)
    if preservation_root is not None:
        cutover["post_switch_native_preservation_root"] = str(preservation_root)
        cutover["post_switch_native_preserved"] = preserved
    snapshot = cutover.get("native_snapshot")
    if isinstance(snapshot, dict):
        restored = _tree_manifest(workspace, SUPPLEMENTAL_MEMORY_ROOTS)
        expected = _entries_for_roots(
            list(snapshot.get("entries") or []),
            SUPPLEMENTAL_MEMORY_ROOTS,
        )
        if restored != expected:
            raise ValueError("restored OpenClaw native memory failed hash verification")
    prior_slot = cutover.get("prior_memory_slot")
    if prior_slot is None:
        _run(
            [executable, "config", "unset", "plugins.slots.memory"],
            allow_missing=True,
        )
    else:
        _set_json(executable, "plugins.slots.memory", prior_slot)
    hook = cutover.get("prior_session_memory_hook")
    if isinstance(hook, dict) and hook.get("enabled") is True:
        _run([executable, "hooks", "enable", "session-memory"])
    elif isinstance(hook, dict) and hook.get("enabled") is False:
        _run([executable, "hooks", "disable", "session-memory"])
    prior_plugin = cutover.get("prior_plugin_entry")
    if isinstance(prior_plugin, dict):
        _set_json(executable, "plugins.entries.memory-aetnamem", prior_plugin)


def _new_preservation_root(trial_dir: Path) -> Path:
    base = trial_dir / "openclaw-post-switch-preserved"
    candidate = base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = trial_dir / f"{base.name}-{suffix}"
    candidate.mkdir(mode=0o700)
    return candidate


def _new_cutover_archive(trial_dir: Path) -> Path:
    base = trial_dir / "openclaw-native-frozen"
    candidate = base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = trial_dir / f"{base.name}-{suffix}"
    return candidate


def _archive_completed_cutover(
    trial_dir: Path,
    cutover: dict[str, Any],
) -> None:
    """Preserve terminal cutover evidence before beginning another attempt."""
    history = trial_dir / "openclaw-cutover-history"
    digest = sha256_hex(canonical_json(cutover))
    target = history / f"{cutover.get('status', 'completed')}-{digest[:16]}.json"
    if not target.exists():
        _private_json(target, cutover)


def _export_active_memories_to_native(
    cutover: dict[str, Any],
    *,
    subject_id: str,
) -> dict[str, Any]:
    """Return non-native memories to OpenClaw after its snapshot verifies.

    The mirror starts as an exact import whose source sessions all use the
    ``openclaw-native:`` prefix. Approved shadow candidates and authenticated
    user memories captured after takeover do not. Those records must remain
    available when OpenClaw becomes authoritative again.
    """

    previous = cutover.get("active_memory_export")
    if isinstance(previous, dict):
        previous_path = Path(str(previous.get("path") or ""))
        expected_sha256 = str(previous.get("sha256") or "")
        if (
            previous_path.is_file()
            and expected_sha256
            and sha256_hex(previous_path.read_bytes()) == expected_sha256
        ):
            return previous

    mirror_db = Path(str(cutover["mirror_db"]))
    workspace = Path(str(cutover["workspace"]))
    memory = Memory(mirror_db)
    try:
        records = [
            row
            for row in memory.list(subject_id)
            if row.get("source_type") == "user_message"
            and not str(row.get("source_session_id") or "").startswith(
                "openclaw-native:"
            )
        ]
        records.sort(key=lambda row: (str(row.get("created_at")), str(row["id"])))
        if not records:
            return {
                "format": "aetnamem-openclaw-active-export-v1",
                "record_count": 0,
                "record_ids": [],
                "path": None,
                "sha256": None,
            }

        lines = [
            "# Memories captured while AetnaMem was active",
            "",
            (
                "These memories were returned by AetnaMem during verified "
                "rollback."
            ),
            "",
        ]
        for row in records:
            content = " ".join(str(row["content"]).split())
            lines.append(f"- {content}")
        data = ("\n".join(lines).rstrip() + "\n").encode("utf-8")
        digest = sha256_hex(data)
        export_dir = workspace / "memory"
        export_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        export_path = export_dir / f"aetnamem-active-{digest[:12]}.md"
        if export_path.exists():
            if export_path.is_symlink() or export_path.read_bytes() != data:
                raise ValueError(
                    "cannot export active-period memories because the "
                    f"deterministic path is occupied: {export_path}"
                )
        else:
            temporary = export_path.with_name(f".{export_path.name}.tmp")
            temporary.write_bytes(data)
            os.chmod(temporary, 0o600)
            os.replace(temporary, export_path)
        if sha256_hex(export_path.read_bytes()) != digest:
            raise ValueError("active-period memory export failed hash verification")

        receipt = {
            "format": "aetnamem-openclaw-active-export-v1",
            "record_count": len(records),
            "record_ids": [str(row["id"]) for row in records],
            "path": str(export_path),
            "sha256": digest,
        }
        with memory.store.transaction(immediate=True):
            memory.store.append_audit_event(
                subject_id=subject_id,
                event_type="host.memory_exported_on_rollback",
                actor="safe-switch-rollback",
                payload={
                    "trial_id": cutover.get("trial_id"),
                    "record_ids": receipt["record_ids"],
                    "export_path_sha256": sha256_hex(str(export_path)),
                    "export_sha256": digest,
                },
            )
        return receipt
    finally:
        memory.close()


def _source_row(source: NativeSource) -> dict[str, Any]:
    data = source.path.read_bytes()
    return {
        "relative_path": source.relative_path,
        "path": str(source.path),
        "plane": source.plane,
        "pinned": source.pinned,
        "bytes": len(data),
        "sha256": sha256_hex(data),
        "mtime_ns": source.path.stat().st_mtime_ns,
    }


def _merge_approved_trial_candidates(state: TrialState, mirror_db: str | Path) -> int:
    store = TrialStore(Path(state.trial_dir) / "evidence.db")
    try:
        approved = store.list_candidates(state.trial_id, statuses=("approved",))
    finally:
        store.close()
    if not approved:
        return 0
    memory = Memory(mirror_db)
    created = 0
    try:
        for row in approved:
            result = memory.remember(
                state.subject_id,
                fact=str(row["content"]),
                force=True,
                session_id=str(row.get("source_session_id") or state.trial_id),
                source_type="user_message",
                actor="safe-switch-approved-import",
                raw={
                    "format": "aetnamem-safe-switch-approved-source-v1",
                    "trial_id": state.trial_id,
                    "candidate_id": row["id"],
                    "candidate_content_sha256": row["content_sha256"],
                    "reviewed_at": row.get("reviewed_at"),
                },
            )
            created += len(result.get("records") or [])
        memory.store.append_audit_event(
            subject_id=state.subject_id,
            event_type="trial.approved_candidates_imported",
            actor="safe-switch-activator",
            payload={
                "trial_id": state.trial_id,
                "candidate_ids": [str(row["id"]) for row in approved],
                "created_records": created,
            },
        )
        memory.store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        memory.close()
    return created


def _markdown_chunks(text: str, *, max_chars: int = 1200) -> Iterable[dict[str, Any]]:
    lines = text.splitlines()
    if not lines:
        return []
    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    start = 1
    for index, line in enumerate(lines, start=1):
        candidate = "\n".join([*current, line]).strip()
        boundary = not line.strip() and current
        too_large = len(candidate) > max_chars and current
        if too_large or boundary:
            value = "\n".join(current).strip()
            if value:
                chunks.append(
                    {"text": value, "line_start": start, "line_end": index - 1}
                )
            current = []
            start = index + 1 if boundary else index
            if boundary:
                continue
        current.append(line)
    value = "\n".join(current).strip()
    if value:
        chunks.append({"text": value, "line_start": start, "line_end": len(lines)})
    return chunks


def _mirror_status_from_manifest(
    manifest: dict[str, Any], mirror_path: Path
) -> dict[str, Any]:
    native_chars = int(manifest.get("native_memory_chars") or 0)
    max_chars = DEFAULT_RECALL_CHARS
    record_count = int(manifest.get("record_count") or 0)
    audit_verified = False
    audit_error = None
    if mirror_path.is_file():
        memory = Memory(mirror_path)
        try:
            subject_id = str(manifest.get("subject_id") or "local-user")
            record_count = len(memory.list(subject_id, include_inactive=True))
            audit_verified = bool(memory.verify(subject_id).get("valid"))
        except Exception as exc:
            audit_error = str(exc)
        finally:
            memory.close()
    return {
        **manifest,
        "status": "synced" if mirror_path.is_file() else "missing",
        "synced": mirror_path.is_file(),
        "mirror_db": str(mirror_path),
        "record_count": record_count,
        "audit_verified": audit_verified,
        "audit_error": audit_error,
        "context_budget_chars": max_chars,
        "native_memory_estimated_tokens": (native_chars + 3) // 4,
        "aetnamem_context_budget_estimated_tokens": (max_chars + 3) // 4,
        "token_projection": (
            "potential_reduction"
            if native_chars > max_chars
            else "no_cost_reduction_expected"
        ),
    }


def _cutover_public(value: dict[str, Any]) -> dict[str, Any]:
    status = str(value.get("status") or "unknown")
    terminal = {"rolled_back", "rolled_back_after_failure"}
    public = {
        key: value.get(key)
        for key in (
            "format",
            "status",
            "trial_id",
            "workspace",
            "mirror_db",
            "manifest_sha256",
            "activated_at",
            "rolled_back_at",
            "native_memory_frozen",
            "native_snapshot_verified",
            "native_memory_slot",
            "session_memory_hook",
            "gateway_verified",
            "compatibility_tools",
            "compatibility_tools_verified",
            "capture_hooks_verified",
            "native_write_guard_verified",
            "native_capability_report",
        )
        if key in value
    } | {
        "active": status == "active",
        "requires_restore": status not in terminal | {"active"},
    }
    if public["requires_restore"]:
        public["recovery_message"] = (
            "A previous OpenClaw switch did not reach a verified terminal "
            "state. Restore OpenClaw before trying activation again."
        )
    snapshot = value.get("native_snapshot")
    if isinstance(snapshot, dict):
        public["native_snapshot"] = {
            key: snapshot.get(key)
            for key in (
                "snapshot_sha256",
                "entry_count",
                "file_count",
                "total_bytes",
                "verified_at",
            )
        }
    return public


def _ensure_native_baseline(trial_dir: Path, workspace: Path) -> dict[str, Any]:
    archive = trial_dir / NATIVE_BASELINE_NAME
    manifest_path = trial_dir / NATIVE_BASELINE_MANIFEST_NAME
    existing = _read_json(manifest_path)
    if existing:
        copied = _tree_manifest(archive, NATIVE_MEMORY_ROOTS)
        if copied != existing.get("entries"):
            raise ValueError(
                "the initial OpenClaw native-memory baseline no longer verifies"
            )
        return existing
    if archive.exists():
        copied = _tree_manifest(archive, NATIVE_MEMORY_ROOTS)
        current = _tree_manifest(workspace, NATIVE_MEMORY_ROOTS)
        if copied != current:
            raise ValueError(
                "an incomplete pre-shadow baseline exists and no longer "
                "matches OpenClaw; remove the failed trial before retrying"
            )
        recovered: dict[str, Any] = {
            "format": "aetnamem-openclaw-native-snapshot-v1",
            "workspace": str(workspace),
            "archive": str(archive),
            "entries": copied,
            "entry_count": len(copied),
            "file_count": sum(1 for row in copied if row["type"] == "file"),
            "total_bytes": sum(
                int(row.get("bytes") or 0) for row in copied if row["type"] == "file"
            ),
            "verified_at": utc_now(),
            "purpose": "pre-shadow-baseline",
            "snapshot_sha256": _native_snapshot_digest(copied),
        }
        _private_json(manifest_path, recovered)
        return recovered

    building = trial_dir / f".{NATIVE_BASELINE_NAME}.building"
    shutil.rmtree(building, ignore_errors=True)
    building.mkdir(mode=0o700)
    try:
        baseline = _snapshot_native_memory(workspace, building)
        baseline["purpose"] = "pre-shadow-baseline"
        os.replace(building, archive)
        baseline["archive"] = str(archive)
        _private_json(manifest_path, baseline)
        return baseline
    except Exception:
        shutil.rmtree(building, ignore_errors=True)
        raise


def _record_shadow_version(
    trial_dir: Path,
    workspace: Path,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    entries = _tree_manifest(workspace, NATIVE_MEMORY_ROOTS)
    digest = _native_snapshot_digest(entries)
    history_root = trial_dir / SHADOW_HISTORY_NAME
    history_root.mkdir(mode=0o700, exist_ok=True)
    baseline_digest = str(baseline.get("snapshot_sha256") or "")
    if digest != baseline_digest:
        target = history_root / digest
        if not target.exists():
            building = history_root / f".{digest}.building"
            shutil.rmtree(building, ignore_errors=True)
            building.mkdir(mode=0o700)
            try:
                observed = _snapshot_native_memory(workspace, building)
                if observed["snapshot_sha256"] != digest:
                    raise ValueError(
                        "OpenClaw native memory changed during shadow synchronization"
                    )
                observed["purpose"] = "shadow-observed-version"
                _private_json(building / "snapshot.json", observed)
                os.replace(building, target)
            except Exception:
                shutil.rmtree(building, ignore_errors=True)
                raise
    versions = sorted(
        path.name
        for path in history_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )
    return {
        "initial_baseline_sha256": baseline_digest,
        "latest_observed_sha256": digest,
        "observed_change_versions": len(versions),
        "version_sha256s": versions,
        "snapshot_root": str(
            Path(str(baseline["archive"]))
            if digest == baseline_digest
            else history_root / digest
        ),
    }


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot.get(key)
        for key in (
            "snapshot_sha256",
            "entry_count",
            "file_count",
            "total_bytes",
            "verified_at",
            "purpose",
        )
    }


def _snapshot_native_memory(workspace: Path, archive: Path) -> dict[str, Any]:
    roots = NATIVE_MEMORY_ROOTS
    before = _tree_manifest(workspace, roots)
    for relative in roots:
        source = workspace / relative
        if source.exists():
            _copy_native_path(source, archive / relative)
    after = _tree_manifest(workspace, roots)
    copied = _tree_manifest(archive, roots)
    if before != after:
        raise ValueError(
            "OpenClaw native memory changed while it was being snapshotted; "
            "activation was not attempted"
        )
    if before != copied:
        raise ValueError(
            "OpenClaw native-memory snapshot failed byte-for-byte verification"
        )
    snapshot: dict[str, Any] = {
        "format": "aetnamem-openclaw-native-snapshot-v1",
        "workspace": str(workspace),
        "archive": str(archive),
        "entries": copied,
        "entry_count": len(copied),
        "file_count": sum(1 for row in copied if row["type"] == "file"),
        "total_bytes": sum(
            int(row.get("bytes") or 0) for row in copied if row["type"] == "file"
        ),
        "verified_at": utc_now(),
    }
    snapshot["snapshot_sha256"] = _native_snapshot_digest(copied)
    return snapshot


def _native_snapshot_digest(entries: list[dict[str, Any]]) -> str:
    return sha256_hex(
        canonical_json(
            {
                "format": "aetnamem-openclaw-native-snapshot-v1",
                "entries": entries,
            }
        )
    )


def _copy_native_path(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise ValueError(
            f"cannot guarantee a complete native-memory snapshot through symlink: {source}"
        )
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(
                "cannot guarantee a complete native-memory snapshot through "
                f"symlink: {item}"
            )
        target = destination / item.relative_to(source)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
        else:
            raise ValueError(f"unsupported native-memory filesystem entry: {item}")


def _tree_manifest(base: Path, roots: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in roots:
        root = base / relative
        if not root.exists():
            continue
        if root.is_symlink():
            raise ValueError(
                f"cannot verify a native-memory snapshot through symlink: {root}"
            )
        candidates = [root]
        if root.is_dir():
            candidates.extend(sorted(root.rglob("*")))
        for candidate in candidates:
            if candidate.is_symlink():
                raise ValueError(
                    "cannot verify a native-memory snapshot through symlink: "
                    f"{candidate}"
                )
            path = candidate.relative_to(base).as_posix()
            if candidate.is_dir():
                rows.append({"path": path, "type": "directory"})
            elif candidate.is_file():
                data = candidate.read_bytes()
                rows.append(
                    {
                        "path": path,
                        "type": "file",
                        "bytes": len(data),
                        "sha256": sha256_hex(data),
                    }
                )
            else:
                raise ValueError(
                    f"unsupported native-memory filesystem entry: {candidate}"
                )
    return sorted(rows, key=lambda row: (str(row["path"]), str(row["type"])))


def _entries_for_roots(
    entries: list[dict[str, Any]],
    roots: Iterable[str],
) -> list[dict[str, Any]]:
    prefixes = tuple(str(root).rstrip("/") for root in roots)
    return [
        row
        for row in entries
        if any(
            str(row.get("path") or "") == prefix
            or str(row.get("path") or "").startswith(f"{prefix}/")
            for prefix in prefixes
        )
    ]


def _private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _remove_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _remove_sqlite_sidecars(path: Path) -> None:
    for candidate in (Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _json_command(arguments: list[str]) -> dict[str, Any]:
    result = _run(arguments)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"command returned invalid JSON: {' '.join(arguments)}"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(f"command returned unexpected JSON: {' '.join(arguments)}")
    return value


def _optional_json(arguments: list[str]) -> Any | None:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _set_json(executable: str, key: str, value: Any) -> None:
    _run(
        [
            executable,
            "config",
            "set",
            key,
            json.dumps(value, separators=(",", ":")),
            "--strict-json",
        ]
    )


def _run(
    arguments: list[str], *, allow_missing: bool = False
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode != 0 and not allow_missing:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise ValueError(f"{' '.join(arguments[:3])} failed: {detail}")
    return result
