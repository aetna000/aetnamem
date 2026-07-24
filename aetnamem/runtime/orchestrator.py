from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
import uuid

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.memory import Memory
from aetnamem.core.policy import forget_needle
from aetnamem.runtime.compiler import compile_context
from aetnamem.runtime.config import load_config
from aetnamem.runtime.interventions import (
    CandidateContribution,
    assign_contributions,
)
from aetnamem.runtime.models import (
    OutcomeReport,
    PLANE_NAMES,
    RuntimeScope,
    TurnRequest,
)
from aetnamem.runtime.providers import (
    EpisodicProvider,
    ProceduralProvider,
    SemanticProvider,
    WorkingProvider,
)
from aetnamem.runtime.store import RuntimeStore


class MemoryRuntime:
    """One orchestrator for working, semantic, episodic, and procedural memory."""

    def __init__(
        self,
        config: str | Path | dict[str, Any],
        *,
        memory: Memory | None = None,
        providers: dict[str, Any] | None = None,
    ) -> None:
        self.config = load_config(config)
        self.db_path = str(self.config["db_path"])
        self.memory = memory or Memory(self.db_path)
        self._owns_memory = memory is None
        self.store = RuntimeStore(self.db_path)
        self.default_scope = RuntimeScope(**self.config["scope"])
        budgets = self.config["budgets"]
        planes = self.config["planes"]
        self.providers = {}
        if planes.get("working", {}).get("enabled", True):
            self.providers["working"] = WorkingProvider(
                self.store, max_chars=budgets.get("working_chars", 700)
            )
        semantic_cfg = planes.get("semantic", {})
        if semantic_cfg.get("enabled", True):
            self.providers["semantic"] = SemanticProvider(
                self.memory,
                max_chars=budgets.get("semantic_chars", 1800),
                max_records=semantic_cfg.get("max_records", 3),
                min_score=semantic_cfg.get("min_score", 0.3),
            )
        episodic_cfg = planes.get("episodic", {})
        if episodic_cfg.get("enabled", True):
            self.providers["episodic"] = EpisodicProvider(
                self.store,
                max_chars=budgets.get("episodic_chars", 900),
                max_outcomes=episodic_cfg.get("max_outcomes", 3),
            )
        procedural_cfg = planes.get("procedural", {})
        if procedural_cfg.get("enabled", True):
            self.providers["procedural"] = ProceduralProvider(
                self.store,
                skill_paths=list(procedural_cfg.get("skill_paths", [])),
                max_chars=budgets.get("procedural_chars", 800),
                max_skills=procedural_cfg.get("max_skills", 2),
            )
        for plane, provider in (providers or {}).items():
            if plane not in PLANE_NAMES:
                raise ValueError(f"unknown provider plane: {plane}")
            self.providers[plane] = provider

    def close(self) -> None:
        self.store.close()
        if self._owns_memory:
            self.memory.close()

    def prepare_turn(
        self,
        query: str,
        *,
        task_state: dict[str, Any] | None = None,
        scope: RuntimeScope | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("prepare_turn requires a non-empty query")
        resolved_scope = self._scope(scope)
        run_id = resolved_scope.run_id or f"run_{uuid.uuid4().hex}"
        resolved_scope = replace(resolved_scope, run_id=run_id)
        self.store.create_run(
            run_id=run_id,
            subject_id=resolved_scope.subject_id,
            agent_id=resolved_scope.agent_id,
            session_id=resolved_scope.session_id,
            task_id=resolved_scope.task_id,
            turn_id=resolved_scope.turn_id,
            query_sha256=sha256_hex(query),
            preset=str(self.config.get("preset", "custom")),
            scope=resolved_scope.to_dict(),
        )
        request = TurnRequest(
            query=query,
            scope=resolved_scope,
            task_state=dict(task_state or {}),
            max_chars=int(self.config["budgets"]["total_chars"]),
        )
        contributions = []
        candidates: list[CandidateContribution] = []
        degraded: list[str] = []
        failures: dict[str, str] = {}
        for plane in PLANE_NAMES:
            provider = self.providers.get(plane)
            if provider is None:
                continue
            try:
                contribution = provider.prepare(request)
                contributions.append(contribution)
                contribution_id = self.store.save_contribution(
                    run_id=run_id,
                    plane=contribution.plane,
                    content=contribution.content,
                    content_sha256=sha256_hex(contribution.content),
                    item_ids=contribution.item_ids,
                    provenance=contribution.provenance,
                    metadata=contribution.metadata,
                    placement=contribution.placement,
                    trust=contribution.trust,
                )
                candidates.append(
                    CandidateContribution(
                        contribution_id=contribution_id,
                        contribution=contribution,
                    )
                )
            except Exception as exc:
                degraded.append(plane)
                failures[plane] = str(exc)
                if self.config.get("failure_policy") == "fail":
                    raise
        cml_assignment = assign_contributions(
            cml_config=dict(self.config.get("cml") or {"mode": "off"}),
            run_id=run_id,
            candidates=candidates,
            default_stratum=resolved_scope.task_id or "default",
        )
        admitted_contributions = contributions
        cml_manifest = None
        if cml_assignment is not None:
            self.store.save_interventions(
                [item.to_dict() for item in cml_assignment.decisions]
            )
            admitted_contributions = list(cml_assignment.admitted)
            cml_manifest = cml_assignment.manifest
        pack = compile_context(
            run_id=run_id,
            scope=resolved_scope,
            contributions=admitted_contributions,
            degraded_planes=degraded,
            budgets=self.config["budgets"],
            cml_manifest=cml_manifest,
        )
        if failures:
            pack["provider_failures"] = failures
        self.store.finish_run(
            run_id=run_id,
            degraded_planes=degraded,
            manifest_sha256=pack["manifest_sha256"],
            stable_sha256=pack["stable_sha256"],
            dynamic_sha256=pack["dynamic_sha256"],
            total_chars=len(pack["stable_context"]) + len(pack["dynamic_context"]),
            manifest=pack["manifest"],
        )
        self.memory.log_action(
            resolved_scope.subject_id,
            "runtime.prepare_turn",
            {
                "run_id": run_id,
                "manifest_sha256": pack["manifest_sha256"],
                "degraded_planes": degraded,
                "planes": [item.plane for item in contributions],
                "candidate_planes": [item.plane for item in contributions],
                "admitted_planes": [
                    item.plane for item in admitted_contributions
                ],
                "cml_mode": (
                    cml_assignment.mode if cml_assignment is not None else "off"
                ),
                "cml_arm_id": (
                    cml_assignment.manifest["arm_id"]
                    if cml_assignment is not None
                    else None
                ),
            },
            session_id=resolved_scope.session_id,
            turn_id=resolved_scope.turn_id,
        )
        return pack

    def record_outcome(
        self,
        run_id: str,
        *,
        success: bool,
        summary: str = "",
        result_digest: str | None = None,
        feedback: str | None = None,
        tool_receipts: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
        manifest_sha256: str | None = None,
        metrics: dict[str, Any] | None = None,
        outcome_trust: str = "caller_asserted",
        scope: RuntimeScope | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_scope = self._scope(scope)
        if outcome_trust not in {"caller_asserted", "host_attested"}:
            raise ValueError(
                "outcome_trust must be 'caller_asserted' or 'host_attested'"
            )
        if metrics is not None and not isinstance(metrics, dict):
            raise ValueError("outcome metrics must be an object")
        run = self.store.run(run_id)
        if run is None:
            raise ValueError(f"unknown runtime run: {run_id}")
        self._assert_outcome_scope(run, resolved_scope)
        manifest = self.store.manifest_for_run(run_id)
        if manifest is None:
            raise ValueError(f"runtime run has no committed manifest: {run_id}")
        interventions = self.store.interventions_for_run(run_id)
        if interventions and not manifest_sha256:
            raise ValueError(
                "CML outcome requires the committed manifest_sha256"
            )
        if (
            manifest_sha256 is not None
            and manifest_sha256 != manifest["manifest_sha256"]
        ):
            raise ValueError("outcome manifest_sha256 does not match prepared run")
        receipts = tuple(tool_receipts or ())
        key = idempotency_key or sha256_hex(
            canonical_json(
                {
                    "run_id": run_id,
                    "manifest_sha256": manifest_sha256,
                    "success": bool(success),
                    "summary": summary,
                    "result_digest": result_digest,
                }
            )
        )
        receipt_digests = [
            sha256_hex(canonical_json(receipt)) for receipt in receipts
        ]
        stored, created = self.store.record_outcome(
            run_id=run_id,
            success=bool(success),
            summary=summary,
            result_digest=result_digest,
            feedback=feedback,
            receipt_digests=receipt_digests,
            idempotency_key=key,
            manifest_sha256=manifest_sha256,
            metrics=metrics,
            outcome_trust=outcome_trust,
        )
        report = OutcomeReport(
            run_id=run_id,
            scope=resolved_scope,
            success=bool(success),
            summary=summary,
            result_digest=result_digest,
            feedback=feedback,
            tool_receipts=receipts,
            idempotency_key=key,
            manifest_sha256=manifest_sha256,
            metrics=dict(metrics or {}),
            outcome_trust=outcome_trust,
        )
        proposals: list[dict] = []
        if created:
            for provider in self.providers.values():
                proposals.extend(provider.record_outcome(report))
            self.memory.log_action(
                resolved_scope.subject_id,
                "runtime.record_outcome",
                {
                    "run_id": run_id,
                    "outcome_id": stored.get("id"),
                    "success": bool(success),
                    "result_digest": result_digest,
                    "receipt_digests": receipt_digests,
                    "manifest_sha256": manifest_sha256,
                    "metrics_sha256": sha256_hex(canonical_json(metrics or {})),
                    "outcome_trust": outcome_trust,
                    "proposal_ids": [item["id"] for item in proposals],
                },
                session_id=resolved_scope.session_id,
                turn_id=resolved_scope.turn_id,
            )
        return {
            "format": "aetnamem-runtime-outcome-v1",
            "run_id": run_id,
            "outcome_id": stored.get("id"),
            "created": created,
            "success": bool(stored.get("success", success)),
            "manifest_sha256": stored.get("manifest_sha256"),
            "metrics": stored.get("metrics", metrics or {}),
            "outcome_trust": stored.get("outcome_trust", outcome_trust),
            "proposals": proposals,
            "lesson_proposals": [
                item for item in proposals if item.get("kind") == "lesson"
            ],
            "procedure_proposals": [
                item
                for item in proposals
                if item.get("kind") == "procedure_improvement"
            ],
            "idempotency_key": key,
        }

    @staticmethod
    def _assert_outcome_scope(
        run: dict[str, Any], scope: RuntimeScope
    ) -> None:
        if str(run["subject_id"]) != scope.subject_id:
            raise ValueError("outcome subject does not match prepared run")
        if str(run["agent_id"]) != scope.agent_id:
            raise ValueError("outcome agent does not match prepared run")
        for field in ("session_id", "task_id", "turn_id"):
            supplied = getattr(scope, field)
            if supplied is not None and run.get(field) != supplied:
                raise ValueError(f"outcome {field} does not match prepared run")

    def status(self) -> dict[str, Any]:
        value = self.store.status()
        cml = dict(self.config.get("cml") or {"mode": "off"})
        value.update(
            {
                "preset": self.config.get("preset", "custom"),
                "cml": {
                    key: cml[key]
                    for key in (
                        "mode",
                        "experiment_id",
                        "design",
                        "policy_version",
                        "assignment_probability",
                        "eligible_planes",
                        "pinned_planes",
                    )
                    if key in cml
                },
                "planes": {
                    plane: (
                        self.providers[plane].health().to_dict()
                        if plane in self.providers
                        else {
                            "plane": plane,
                            "healthy": True,
                            "detail": "disabled by configuration",
                        }
                    )
                    for plane in PLANE_NAMES
                },
            }
        )
        return value

    def promote_lesson(self, lesson_id: str) -> dict[str, Any]:
        return self.store.promote_lesson(lesson_id)

    def forget(
        self, *, contains: str | None = None, utterance: str | None = None
    ) -> dict[str, Any]:
        needle = (contains or "").strip()
        if utterance:
            needle = needle or forget_needle(utterance)
        if not needle:
            raise ValueError("runtime forget requires a non-empty selector")
        semantic = self.memory.forget(
            self.default_scope.subject_id,
            selector=needle,
            utterance=utterance,
        )
        runtime_purged = self.store.purge_subject_content(
            subject_id=self.default_scope.subject_id,
            contains=needle,
        )
        selector_sha256 = sha256_hex(needle.lower())
        event_id = self.memory.log_action(
            self.default_scope.subject_id,
            "runtime.forget",
            {
                "selector_sha256": selector_sha256,
                "semantic_record_ids": semantic["record_ids"],
                "runtime_purged": runtime_purged,
            },
        )
        event = self.memory.store.get_audit_event(
            self.default_scope.subject_id, event_id
        )
        receipt = {
            "format": "aetnamem-runtime-deletion-receipt-v1",
            "subject_id": self.default_scope.subject_id,
            "selector_sha256": selector_sha256,
            "semantic_receipt_sha256": (
                semantic["receipt"].get("receipt_sha256")
                if semantic.get("receipt")
                else None
            ),
            "runtime_purged": runtime_purged,
            "audit_event_id": event_id,
            "audit_event_hash": event["event_hash"],
        }
        receipt["receipt_sha256"] = sha256_hex(canonical_json(receipt))
        runtime_count = sum(len(value) for value in runtime_purged.values())
        return {
            "deleted": bool(semantic["deleted"] or runtime_count),
            "semantic_record_ids": semantic["record_ids"],
            "runtime_purged": runtime_purged,
            "receipt": receipt,
        }

    def _scope(
        self, scope: RuntimeScope | dict[str, Any] | None
    ) -> RuntimeScope:
        if scope is None:
            return self.default_scope
        candidate = scope if isinstance(scope, RuntimeScope) else RuntimeScope(**scope)
        # Identity comes from the configured host boundary. Callers may refine
        # session/task/turn, but may not impersonate another subject or agent.
        if candidate.subject_id != self.default_scope.subject_id:
            raise ValueError("scope.subject_id is pinned by runtime configuration")
        if candidate.agent_id != self.default_scope.agent_id:
            raise ValueError("scope.agent_id is pinned by runtime configuration")
        return candidate
