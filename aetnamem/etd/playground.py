"""Installed EtD playground exercising a complete multi-principal workflow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import uuid

from aetnamem.decisions import ActorContext, ArtifactLink, ConsensusPolicy, DecisionEngine
from aetnamem.etd.profiles import clinical_etd_template
from aetnamem.etd.report import render_markdown


def run_demo(
    path: str | Path | None,
    *,
    namespace_id: str | None = None,
    engine: DecisionEngine | None = None,
) -> dict[str, object]:
    namespace = namespace_id or f"playground-{uuid.uuid4().hex[:8]}"
    chair = ActorContext(namespace, "dr-chair", "playground-chair")
    voter = ActorContext(namespace, "consumer-representative", "playground-voter")
    approver = ActorContext(namespace, "hospital-executive", "playground-approver")
    owns_engine = engine is None
    if engine is None:
        if path is None:
            raise ValueError("path is required when engine is not supplied")
        engine = DecisionEngine(str(path))
    try:
        case = engine.create_case(
            chair,
            title="Introduce pharmacist-led discharge reconciliation",
            template=clinical_etd_template(),
            content={
                "question": "Should the hospital introduce pharmacist-led medication reconciliation at discharge?",
                "population": "Adults discharged with five or more medicines",
                "intervention": "Pharmacist-led discharge reconciliation",
                "comparator": "Current discharge workflow",
                "outcomes": ["medication discrepancies", "readmissions", "staff workload"],
            },
            idempotency_key="case-create",
        )
        case_id = str(case["id"])
        engine.add_member(
            chair,
            case_id,
            principal_id=voter.principal_id,
            role="voter",
            expected_version=1,
            idempotency_key="member-voter",
        )
        engine.add_member(
            chair,
            case_id,
            principal_id=approver.principal_id,
            role="approver",
            expected_version=2,
            idempotency_key="member-approver",
        )

        evidence = engine.create_artifact(
            chair,
            case_id,
            kind="evidence_bundle",
            status="submitted",
            content={
                "title": "Discharge reconciliation evidence bundle",
                "sources": ["systematic-review-2026", "hospital-baseline-audit"],
                "certainty": "moderate",
                "trust_tier": "reviewed_source",
            },
            idempotency_key="evidence",
        )
        assessment = engine.create_artifact(
            chair,
            case_id,
            kind="criterion_assessment",
            status="submitted",
            content={
                "criterion": "feasibility",
                "judgment": "probably_yes",
                "rationale": "The pharmacy roster can support a staged weekday rollout.",
                "ratings": [],
                "assumptions": ["Training and backfill funding is approved"],
            },
            links=(ArtifactLink(str(evidence["revision_id"]), "supports"),),
            idempotency_key="assessment-feasibility",
        )
        recommendation = engine.create_artifact(
            chair,
            case_id,
            kind="recommendation",
            status="submitted",
            content={
                "text": "Introduce pharmacist-led reconciliation for eligible weekday discharges, with a three-month monitored rollout.",
                "direction": "for_intervention",
                "strength": "conditional",
                "justification": "Expected reduction in discrepancies with manageable implementation requirements.",
            },
            links=(ArtifactLink(str(assessment["revision_id"]), "supports"),),
            idempotency_key="recommendation",
        )
        ballot = engine.open_ballot(
            chair,
            case_id,
            target_revision_id=str(recommendation["revision_id"]),
            choices=("yes", "no", "abstain"),
            policy=ConsensusPolicy(threshold=0.5, quorum=1.0, passing_choices=("yes",)),
            visibility="hidden_until_close",
            idempotency_key="ballot",
        )
        engine.cast_vote(
            chair,
            str(ballot["id"]),
            choice="yes",
            rationale="The staged rollout addresses the main feasibility concern.",
            idempotency_key="chair-vote",
        )
        engine.cast_vote(
            voter,
            str(ballot["id"]),
            choice="yes",
            rationale="The recommendation includes monitoring meaningful to patients.",
            idempotency_key="consumer-vote",
        )
        outcome = engine.close_ballot(
            chair,
            str(ballot["id"]),
            expected_version=1,
            idempotency_key="close-ballot",
        )
        adoption = engine.adopt_recommendation(
            chair,
            case_id,
            recommendation_revision_id=str(recommendation["revision_id"]),
            outcome_id=str(outcome["id"]),
            idempotency_key="adopt",
        )
        plan = engine.create_artifact(
            chair,
            case_id,
            kind="implementation_plan",
            status="final",
            content={
                "rollout": "weekday pilot for three months",
                "owner": "Director of Pharmacy",
                "measures": ["discrepancy rate", "30-day readmission", "staff workload"],
            },
            links=(ArtifactLink(str(recommendation["revision_id"]), "implements"),),
            idempotency_key="implementation-plan",
        )
        approval = engine.approve_change(
            approver,
            case_id,
            plan_revision_id=str(plan["revision_id"]),
            rationale="Resources approved for the monitored pilot.",
            idempotency_key="executive-approval",
        )
        authorization = engine.grant_authorization(
            chair,
            case_id,
            plan_revision_id=str(plan["revision_id"]),
            adoption_id=str(adoption["id"]),
            approval_ids=(str(approval["id"]),),
            scope={
                "subject_ids": ["hospital-change"],
                "adapters": ["filesystem"],
                "operations": ["write_text"],
                "resources": ["approved-change.md"],
            },
            idempotency_key="authorization",
        )
        bundle = engine.export_case(chair, case_id)
        return {
            "namespace_id": namespace,
            "case_id": case_id,
            "authorization_id": authorization["id"],
            "bundle": bundle,
            "report": render_markdown(bundle),
        }
    finally:
        if owns_engine:
            engine.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="aetnamem-etd-playground")
    parser.add_argument("--db", default=None)
    parser.add_argument(
        "--postgres-dsn-env",
        default=None,
        metavar="ENV_VAR",
        help="read a PostgreSQL DSN from this environment variable (never from argv)",
    )
    parser.add_argument("--output", default="./etd-playground-output")
    parser.add_argument("--namespace", default=None)
    args = parser.parse_args(argv)

    selected_db = args.db or "./etd-playground.db"
    engine = None
    backend = "sqlite"
    if args.postgres_dsn_env:
        dsn = os.environ.get(args.postgres_dsn_env)
        if not dsn:
            parser.error(f"environment variable is unset or empty: {args.postgres_dsn_env}")
        engine = DecisionEngine.postgres(dsn)
        backend = "postgresql"
    try:
        result = run_demo(selected_db, namespace_id=args.namespace, engine=engine)
    finally:
        if engine is not None:
            engine.close()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "decision-bundle.json").write_text(
        json.dumps(result["bundle"], indent=2, sort_keys=True) + "\n", "utf-8"
    )
    (output / "etd-report.md").write_text(str(result["report"]), "utf-8")
    print(
        json.dumps(
            {
                "database_backend": backend,
                "database": str(Path(selected_db).resolve()) if backend == "sqlite" else "configured by environment",
                "namespace_id": result["namespace_id"],
                "case_id": result["case_id"],
                "authorization_id": result["authorization_id"],
                "bundle": str((output / "decision-bundle.json").resolve()),
                "report": str((output / "etd-report.md").resolve()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
