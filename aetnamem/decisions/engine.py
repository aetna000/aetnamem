"""Headless, host-embeddable collaborative decision engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import secrets
from typing import Any, Callable
import uuid

from aetnamem.decisions.consensus import calculate_outcome
from aetnamem.decisions.models import (
    ActorContext,
    ArtifactLink,
    ConsensusPolicy,
    DecisionConflict,
    DecisionNotFound,
    DecisionPolicyViolation,
    DecisionStateError,
    DecisionTemplate,
    capabilities_for_role,
    digest_json,
    revision_digest,
)
from aetnamem.decisions.store import SQLiteDecisionStore
from aetnamem.decisions.repository import DecisionRepository
from aetnamem.decisions.signing import (
    DecisionSignatureVerifier,
    DecisionSigner,
    PrincipalAttestation,
    receipt_digest,
    verify_principal_attestation,
)
from aetnamem.memory import Memory
from aetnamem.store.sqlite import SQLiteStore, utc_now


class DecisionEngine:
    """Deterministic decision workflow sharing AetnaMem's audit ledger.

    Instances own no identity or session state.  A server should construct the
    :class:`ActorContext` from its authenticated request and use one engine /
    SQLite connection per request thread.
    """

    def __init__(
        self,
        source: Memory | SQLiteStore | DecisionRepository | str,
        *,
        receipt_signer: DecisionSigner | None = None,
        attestation_verifier: DecisionSignatureVerifier | None = None,
        require_attestations: bool = False,
    ) -> None:
        if isinstance(source, Memory):
            self._owned_store = None
            store = source.store
        elif isinstance(source, SQLiteStore):
            self._owned_store = None
            store = source
        elif isinstance(source, (str, os.PathLike)):
            self._owned_store = SQLiteStore(source)
            store = self._owned_store
        else:
            self._owned_store = None
            self.store = source
            store = None
        if store is not None:
            self.store = SQLiteDecisionStore(store)
        self.receipt_signer = receipt_signer
        self.attestation_verifier = attestation_verifier
        self.require_attestations = require_attestations

    def close(self) -> None:
        if self._owned_store is not None:
            self._owned_store.close()
            self._owned_store = None

    @classmethod
    def postgres(cls, dsn: str, **kwargs: Any) -> "DecisionEngine":
        """Create an engine owning a PostgreSQL repository connection."""
        from aetnamem.decisions.postgres import PostgresDecisionStore

        repository = PostgresDecisionStore(dsn)
        engine = cls(repository, **kwargs)
        engine._owned_store = repository
        return engine

    # -- cases and members ---------------------------------------------------

    def create_case(
        self,
        context: ActorContext,
        *,
        title: str,
        template: DecisionTemplate,
        content: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not title.strip():
            raise ValueError("case title is required")
        request = {"title": title, "template": template.to_dict(), "content": content}

        def create() -> dict[str, Any]:
            existing = self.store.one(
                """
                SELECT digest FROM decision_templates
                WHERE namespace_id = ? AND template_id = ? AND version = ?
                """,
                (context.namespace_id, template.template_id, template.version),
            )
            if existing and existing["digest"] != template.digest:
                raise DecisionConflict("template id/version already exists with different content")
            now = utc_now()
            if existing is None:
                self.store.execute(
                    """
                    INSERT INTO decision_templates(
                      namespace_id, template_id, version, template_json, digest, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        context.namespace_id,
                        template.template_id,
                        template.version,
                        _json(template.to_dict()),
                        template.digest,
                        now,
                    ),
                )
            case_id = _new_id("dec")
            revision_id = _new_id("dcr")
            audit_scope = f"decision:{digest_json(context.namespace_id)[:16]}:{case_id}"
            case_digest = digest_json(
                {
                    "format": "aetnamem-decision-case-v1",
                    "case_id": case_id,
                    "revision": 1,
                    "title": title.strip(),
                    "template_digest": template.digest,
                    "content": content,
                    "author": context.principal_id,
                }
            )
            self.store.execute(
                """
                INSERT INTO decision_cases(
                  namespace_id, id, title, status, template_id, template_version,
                  template_digest, current_revision, version, audit_scope_id,
                  created_by, created_at, updated_at
                ) VALUES (?, ?, ?, 'active', ?, ?, ?, 1, 1, ?, ?, ?, ?)
                """,
                (
                    context.namespace_id,
                    case_id,
                    title.strip(),
                    template.template_id,
                    template.version,
                    template.digest,
                    audit_scope,
                    context.principal_id,
                    now,
                    now,
                ),
            )
            self.store.execute(
                """
                INSERT INTO decision_case_revisions(
                  namespace_id, id, case_id, revision, content_json, digest,
                  created_by, created_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    context.namespace_id,
                    revision_id,
                    case_id,
                    _json(content),
                    case_digest,
                    context.principal_id,
                    now,
                ),
            )
            capabilities = capabilities_for_role("chair")
            self.store.execute(
                """
                INSERT INTO decision_memberships(
                  namespace_id, case_id, principal_id, role, capabilities_json,
                  status, version, created_at, updated_at
                ) VALUES (?, ?, ?, 'chair', ?, 'active', 1, ?, ?)
                """,
                (context.namespace_id, case_id, context.principal_id, _json(capabilities), now, now),
            )
            case = self._case(context.namespace_id, case_id)
            event_id = self.store.append_audit(
                case,
                "decision.case.created",
                context.principal_id,
                {
                    "case_id": case_id,
                    "revision_id": revision_id,
                    "case_digest": case_digest,
                    "template_id": template.template_id,
                    "template_version": template.version,
                    "template_digest": template.digest,
                },
            )
            return {**case, "revision_id": revision_id, "case_digest": case_digest, "audit_event_id": event_id}

        return self._mutate(context, idempotency_key, "create_case", request, create)

    def get_case(self, context: ActorContext, case_id: str) -> dict[str, Any]:
        case = self._case(context.namespace_id, case_id)
        self._membership(context, case_id)
        revision = self.store.one(
            """
            SELECT * FROM decision_case_revisions
            WHERE namespace_id = ? AND case_id = ? AND revision = ?
            """,
            (context.namespace_id, case_id, case["current_revision"]),
        )
        assert revision is not None
        return {
            **case,
            "content": json.loads(revision["content_json"]),
            "content_purged_at": revision.get("purged_at"),
            "case_digest": revision["digest"],
            "members": self.store.list_memberships(context.namespace_id, case_id),
        }

    def add_member(
        self,
        context: ActorContext,
        case_id: str,
        *,
        principal_id: str,
        role: str,
        expected_version: int,
        idempotency_key: str,
        capabilities: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        selected = tuple(sorted(set(capabilities or capabilities_for_role(role))))
        request = {
            "case_id": case_id,
            "principal_id": principal_id,
            "role": role,
            "capabilities": selected,
            "expected_version": expected_version,
        }

        def add() -> dict[str, Any]:
            case = self._case(context.namespace_id, case_id)
            self._require(context, case_id, "manage_members")
            self._bump_case(case, expected_version)
            now = utc_now()
            current = self.store.get_membership(context.namespace_id, case_id, principal_id)
            version = int(current["version"]) + 1 if current else 1
            self.store.execute(
                """
                INSERT INTO decision_memberships(
                  namespace_id, case_id, principal_id, role, capabilities_json,
                  status, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(namespace_id, case_id, principal_id) DO UPDATE SET
                  role=excluded.role, capabilities_json=excluded.capabilities_json,
                  status='active', version=excluded.version, updated_at=excluded.updated_at
                """,
                (
                    context.namespace_id,
                    case_id,
                    principal_id,
                    role,
                    _json(selected),
                    version,
                    current["created_at"] if current else now,
                    now,
                ),
            )
            updated = self.store.get_membership(context.namespace_id, case_id, principal_id)
            assert updated is not None
            self.store.append_audit(
                case,
                "decision.member.changed",
                context.principal_id,
                {
                    "case_id": case_id,
                    "principal_id": principal_id,
                    "role": role,
                    "capabilities": list(selected),
                    "membership_version": version,
                },
            )
            return updated

        return self._mutate(context, idempotency_key, "add_member", request, add)

    # -- conflicts and recusals ---------------------------------------------

    def declare_conflict(
        self,
        context: ActorContext,
        case_id: str,
        *,
        scope: str,
        details: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {"case_id": case_id, "scope": scope, "details": details}

        def declare() -> dict[str, Any]:
            case = self._case(context.namespace_id, case_id)
            self._membership(context, case_id)
            conflict_id = _new_id("coi")
            now = utc_now()
            details_digest = digest_json(details)
            self.store.execute(
                """
                INSERT INTO decision_conflicts(
                  namespace_id, id, case_id, principal_id, scope, details_json,
                  details_digest, status, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'declared', 1, ?, ?)
                """,
                (
                    context.namespace_id,
                    conflict_id,
                    case_id,
                    context.principal_id,
                    scope,
                    _json(details),
                    details_digest,
                    now,
                    now,
                ),
            )
            self.store.append_audit(
                case,
                "decision.conflict.declared",
                context.principal_id,
                {"case_id": case_id, "conflict_id": conflict_id, "scope": scope, "details_digest": details_digest},
            )
            return {
                "id": conflict_id,
                "case_id": case_id,
                "principal_id": context.principal_id,
                "scope": scope,
                "status": "declared",
                "details_digest": details_digest,
                "version": 1,
            }

        return self._mutate(context, idempotency_key, "declare_conflict", request, declare)

    def rule_conflict(
        self,
        context: ActorContext,
        case_id: str,
        conflict_id: str,
        *,
        status: str,
        rationale: str,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if status not in {"cleared", "managed", "recused"}:
            raise ValueError("conflict ruling must be cleared, managed, or recused")
        request = {
            "case_id": case_id,
            "conflict_id": conflict_id,
            "status": status,
            "rationale": rationale,
            "expected_version": expected_version,
        }

        def rule() -> dict[str, Any]:
            case = self._case(context.namespace_id, case_id)
            self._require(context, case_id, "manage_conflicts")
            conflict = self.store.one(
                """
                SELECT * FROM decision_conflicts
                WHERE namespace_id = ? AND case_id = ? AND id = ?
                """,
                (context.namespace_id, case_id, conflict_id),
            )
            if conflict is None:
                raise DecisionNotFound(conflict_id)
            ruling_digest = digest_json({"status": status, "rationale": rationale})
            cursor = self.store.execute(
                """
                UPDATE decision_conflicts
                SET status = ?, ruled_by = ?, ruling_digest = ?,
                    version = version + 1, updated_at = ?
                WHERE namespace_id = ? AND id = ? AND version = ?
                """,
                (
                    status,
                    context.principal_id,
                    ruling_digest,
                    utc_now(),
                    context.namespace_id,
                    conflict_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise DecisionConflict("stale conflict version")
            self.store.append_audit(
                case,
                "decision.conflict.ruled",
                context.principal_id,
                {"case_id": case_id, "conflict_id": conflict_id, "status": status, "ruling_digest": ruling_digest},
            )
            return {
                "id": conflict_id,
                "status": status,
                "version": expected_version + 1,
                "ruling_digest": ruling_digest,
            }

        return self._mutate(context, idempotency_key, "rule_conflict", request, rule)

    # -- versioned artifacts -------------------------------------------------

    def create_artifact(
        self,
        context: ActorContext,
        case_id: str,
        *,
        kind: str,
        content: dict[str, Any],
        links: tuple[ArtifactLink, ...] = (),
        status: str = "draft",
        idempotency_key: str,
    ) -> dict[str, Any]:
        if status not in {"draft", "submitted", "final"}:
            raise ValueError("invalid initial artifact status")
        request = {
            "case_id": case_id,
            "kind": kind,
            "content": content,
            "links": [link.__dict__ for link in links],
            "status": status,
        }

        def create() -> dict[str, Any]:
            case = self._case(context.namespace_id, case_id)
            member = self._membership(context, case_id)
            caps = set(member["capabilities"])
            if "create_artifact" not in caps:
                if "create_draft" not in caps or status != "draft":
                    raise DecisionPolicyViolation("principal cannot create this artifact")
            self._validate_artifact(case, kind, content)
            artifact_id = _new_id("dar")
            revision_id = _new_id("drv")
            now = utc_now()
            digest = revision_digest(
                artifact_id=artifact_id,
                revision=1,
                kind=kind,
                content=content,
                author=context.principal_id,
            )
            sources = self._validated_links(context.namespace_id, case_id, links)
            self.store.execute(
                """
                INSERT INTO decision_artifacts(
                  namespace_id, id, case_id, kind, status, current_revision,
                  version, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?, ?)
                """,
                (context.namespace_id, artifact_id, case_id, kind, status, context.principal_id, now, now),
            )
            self.store.execute(
                """
                INSERT INTO decision_artifact_revisions(
                  namespace_id, id, artifact_id, case_id, revision, kind,
                  content_json, digest, author, created_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    context.namespace_id,
                    revision_id,
                    artifact_id,
                    case_id,
                    kind,
                    _json(content),
                    digest,
                    context.principal_id,
                    now,
                ),
            )
            self._insert_links(context.namespace_id, case_id, revision_id, sources, now)
            self.store.append_audit(
                case,
                "decision.artifact.created",
                context.principal_id,
                {
                    "case_id": case_id,
                    "artifact_id": artifact_id,
                    "revision_id": revision_id,
                    "kind": kind,
                    "status": status,
                    "digest": digest,
                    "links": [{"source_revision_id": row["id"], "source_digest": row["digest"], "role": role} for row, role in sources],
                },
            )
            return {
                "id": artifact_id,
                "case_id": case_id,
                "kind": kind,
                "status": status,
                "version": 1,
                "revision": 1,
                "revision_id": revision_id,
                "digest": digest,
                "content": content,
            }

        return self._mutate(context, idempotency_key, "create_artifact", request, create)

    def revise_artifact(
        self,
        context: ActorContext,
        artifact_id: str,
        *,
        content: dict[str, Any],
        links: tuple[ArtifactLink, ...] = (),
        status: str = "draft",
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {
            "artifact_id": artifact_id,
            "content": content,
            "links": [link.__dict__ for link in links],
            "status": status,
            "expected_version": expected_version,
        }

        def revise() -> dict[str, Any]:
            artifact = self._artifact(context.namespace_id, artifact_id)
            case = self._case(context.namespace_id, artifact["case_id"])
            self._require(context, artifact["case_id"], "create_artifact")
            if artifact["status"] in {"superseded", "withdrawn"}:
                raise DecisionStateError("artifact cannot be revised")
            self._validate_artifact(case, artifact["kind"], content)
            revision_number = int(artifact["current_revision"]) + 1
            revision_id = _new_id("drv")
            digest = revision_digest(
                artifact_id=artifact_id,
                revision=revision_number,
                kind=artifact["kind"],
                content=content,
                author=context.principal_id,
            )
            sources = self._validated_links(context.namespace_id, artifact["case_id"], links)
            now = utc_now()
            cursor = self.store.execute(
                """
                UPDATE decision_artifacts
                SET current_revision = ?, version = version + 1, status = ?, updated_at = ?
                WHERE namespace_id = ? AND id = ? AND version = ?
                """,
                (revision_number, status, now, context.namespace_id, artifact_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise DecisionConflict("stale artifact version")
            self.store.execute(
                """
                INSERT INTO decision_artifact_revisions(
                  namespace_id, id, artifact_id, case_id, revision, kind,
                  content_json, digest, author, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context.namespace_id,
                    revision_id,
                    artifact_id,
                    artifact["case_id"],
                    revision_number,
                    artifact["kind"],
                    _json(content),
                    digest,
                    context.principal_id,
                    now,
                ),
            )
            self._insert_links(context.namespace_id, artifact["case_id"], revision_id, sources, now)
            self.store.append_audit(
                case,
                "decision.artifact.revised",
                context.principal_id,
                {
                    "case_id": artifact["case_id"],
                    "artifact_id": artifact_id,
                    "revision_id": revision_id,
                    "revision": revision_number,
                    "status": status,
                    "digest": digest,
                },
            )
            return {
                "id": artifact_id,
                "case_id": artifact["case_id"],
                "kind": artifact["kind"],
                "status": status,
                "version": expected_version + 1,
                "revision": revision_number,
                "revision_id": revision_id,
                "digest": digest,
                "content": content,
            }

        return self._mutate(context, idempotency_key, "revise_artifact", request, revise)

    # -- ballots -------------------------------------------------------------

    def open_ballot(
        self,
        context: ActorContext,
        case_id: str,
        *,
        target_revision_id: str,
        choices: tuple[str, ...],
        policy: ConsensusPolicy,
        visibility: str = "open",
        closes_at: str | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if visibility not in {"open", "hidden_until_close"}:
            raise ValueError("invalid ballot visibility")
        if not choices or len(set(choices)) != len(choices):
            raise ValueError("ballot choices must be non-empty and unique")
        if policy.method != "manual" and not set(policy.passing_choices).issubset(choices):
            raise ValueError("passing choices must be ballot choices")
        if closes_at is not None:
            _parse_time(closes_at)
        request = {
            "case_id": case_id,
            "target_revision_id": target_revision_id,
            "choices": choices,
            "policy": policy.to_dict(),
            "visibility": visibility,
            "closes_at": closes_at,
        }

        def open_round() -> dict[str, Any]:
            case = self._case(context.namespace_id, case_id)
            self._require(context, case_id, "manage_ballot")
            target = self._revision(context.namespace_id, target_revision_id)
            if target["case_id"] != case_id:
                raise DecisionNotFound(target_revision_id)
            ballot_id = _new_id("bal")
            now = utc_now()
            self.store.execute(
                """
                INSERT INTO decision_ballots(
                  namespace_id, id, case_id, target_revision_id, target_digest,
                  state, choices_json, policy_json, policy_digest, visibility,
                  closes_at, version, opened_by, opened_at
                ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    context.namespace_id,
                    ballot_id,
                    case_id,
                    target_revision_id,
                    target["digest"],
                    _json(choices),
                    _json(policy.to_dict()),
                    policy.digest,
                    visibility,
                    closes_at,
                    context.principal_id,
                    now,
                ),
            )
            eligibility: list[dict[str, Any]] = []
            for member in self.store.list_memberships(context.namespace_id, case_id):
                eligible = member["status"] == "active" and "vote" in member["capabilities"]
                reason = None if eligible else "membership_not_eligible"
                if eligible and self._is_recused(
                    context.namespace_id,
                    case_id,
                    member["principal_id"],
                    artifact_id=target["artifact_id"],
                    revision_id=target_revision_id,
                ):
                    eligible = False
                    reason = "recused"
                self.store.execute(
                    """
                    INSERT INTO decision_ballot_eligibility(
                      namespace_id, ballot_id, principal_id, eligible, reason, membership_version
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        context.namespace_id,
                        ballot_id,
                        member["principal_id"],
                        int(eligible),
                        reason,
                        member["version"],
                    ),
                )
                eligibility.append({"principal_id": member["principal_id"], "eligible": eligible, "reason": reason})
            self.store.append_audit(
                case,
                "decision.ballot.opened",
                context.principal_id,
                {
                    "case_id": case_id,
                    "ballot_id": ballot_id,
                    "target_revision_id": target_revision_id,
                    "target_digest": target["digest"],
                    "policy_digest": policy.digest,
                    "eligible_principals": sorted(item["principal_id"] for item in eligibility if item["eligible"]),
                    "excluded": sorted(item["principal_id"] for item in eligibility if not item["eligible"]),
                },
            )
            return {
                "id": ballot_id,
                "case_id": case_id,
                "state": "open",
                "version": 1,
                "target_revision_id": target_revision_id,
                "target_digest": target["digest"],
                "choices": list(choices),
                "policy": policy.to_dict(),
                "policy_digest": policy.digest,
                "visibility": visibility,
                "eligibility": eligibility,
            }

        return self._mutate(context, idempotency_key, "open_ballot", request, open_round)

    def cast_vote(
        self,
        context: ActorContext,
        ballot_id: str,
        *,
        choice: str,
        rationale: str = "",
        expected_vote_id: str | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {
            "ballot_id": ballot_id,
            "choice": choice,
            "rationale": rationale,
            "expected_vote_id": expected_vote_id,
        }

        def cast() -> dict[str, Any]:
            ballot = self._ballot(context.namespace_id, ballot_id)
            case = self._case(context.namespace_id, ballot["case_id"])
            self._require(context, ballot["case_id"], "vote")
            if ballot["state"] != "open":
                raise DecisionStateError("ballot is not open")
            if ballot["closes_at"] and _parse_time(ballot["closes_at"]) <= datetime.now(timezone.utc):
                raise DecisionStateError("ballot deadline has passed")
            if choice not in ballot["choices"]:
                raise DecisionPolicyViolation("choice is not permitted by this ballot")
            eligible = self.store.one(
                """
                SELECT * FROM decision_ballot_eligibility
                WHERE namespace_id = ? AND ballot_id = ? AND principal_id = ?
                """,
                (context.namespace_id, ballot_id, context.principal_id),
            )
            if eligible is None or not eligible["eligible"]:
                raise DecisionPolicyViolation("principal is not eligible for this ballot")
            current = self.store.one(
                """
                SELECT * FROM decision_vote_revisions
                WHERE namespace_id = ? AND ballot_id = ? AND principal_id = ?
                  AND status = 'current'
                """,
                (context.namespace_id, ballot_id, context.principal_id),
            )
            if current is None and expected_vote_id is not None:
                raise DecisionConflict("expected vote does not exist")
            if current is not None and current["id"] != expected_vote_id:
                raise DecisionConflict("current vote changed; supply its id to supersede it")
            revision = int(current["revision"]) + 1 if current else 1
            vote_id = _new_id("vot")
            salt = secrets.token_hex(16)
            commitment = digest_json(
                {
                    "format": "aetnamem-decision-vote-v1",
                    "ballot_id": ballot_id,
                    "principal_id": context.principal_id,
                    "revision": revision,
                    "choice": choice,
                    "rationale": rationale,
                    "salt": salt,
                }
            )
            now = utc_now()
            if current:
                self.store.execute(
                    """
                    UPDATE decision_vote_revisions SET status = 'superseded'
                    WHERE namespace_id = ? AND id = ? AND status = 'current'
                    """,
                    (context.namespace_id, current["id"]),
                )
            self.store.execute(
                """
                INSERT INTO decision_vote_revisions(
                  namespace_id, id, ballot_id, case_id, principal_id, revision,
                  choice, rationale_json, salt, commitment, status, supersedes_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'current', ?, ?)
                """,
                (
                    context.namespace_id,
                    vote_id,
                    ballot_id,
                    ballot["case_id"],
                    context.principal_id,
                    revision,
                    choice,
                    _json({"text": rationale}),
                    salt,
                    commitment,
                    current["id"] if current else None,
                    now,
                ),
            )
            self.store.append_audit(
                case,
                "decision.vote.cast",
                context.principal_id,
                {
                    "case_id": ballot["case_id"],
                    "ballot_id": ballot_id,
                    "vote_id": vote_id,
                    "revision": revision,
                    "commitment": commitment,
                    "supersedes_vote_id": current["id"] if current else None,
                },
            )
            return {
                "id": vote_id,
                "ballot_id": ballot_id,
                "revision": revision,
                "commitment": commitment,
                "supersedes_vote_id": current["id"] if current else None,
            }

        return self._mutate(context, idempotency_key, "cast_vote", request, cast)

    def close_ballot(
        self,
        context: ActorContext,
        ballot_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        manual_passed: bool | None = None,
        manual_rationale: str = "",
    ) -> dict[str, Any]:
        request = {
            "ballot_id": ballot_id,
            "expected_version": expected_version,
            "manual_passed": manual_passed,
            "manual_rationale": manual_rationale,
        }

        def close_round() -> dict[str, Any]:
            ballot = self._ballot(context.namespace_id, ballot_id)
            case = self._case(context.namespace_id, ballot["case_id"])
            self._require(context, ballot["case_id"], "manage_ballot")
            if ballot["state"] != "open":
                raise DecisionStateError("ballot is not open")
            eligibility = self.store.eligible_voters(context.namespace_id, ballot_id)
            eligible = [row["principal_id"] for row in eligibility if row["eligible"]]
            votes = self.store.current_votes(context.namespace_id, ballot_id)
            policy = ConsensusPolicy.from_dict(ballot["policy"])
            rationale_digest = digest_json(manual_rationale) if manual_rationale else None
            outcome = calculate_outcome(
                ballot_id=ballot_id,
                target_revision_id=ballot["target_revision_id"],
                target_digest=ballot["target_digest"],
                eligible=eligible,
                votes=votes,
                policy=policy,
                manual_passed=manual_passed,
                manual_rationale_digest=rationale_digest,
            )
            now = utc_now()
            cursor = self.store.execute(
                """
                UPDATE decision_ballots
                SET state = 'closed', version = version + 1, closed_at = ?
                WHERE namespace_id = ? AND id = ? AND state = 'open' AND version = ?
                """,
                (now, context.namespace_id, ballot_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise DecisionConflict("ballot changed while it was being closed")
            outcome_id = _new_id("out")
            self.store.execute(
                """
                INSERT INTO decision_ballot_outcomes(
                  namespace_id, id, ballot_id, case_id, outcome_json, digest,
                  created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context.namespace_id,
                    outcome_id,
                    ballot_id,
                    ballot["case_id"],
                    _json(outcome),
                    outcome["digest"],
                    context.principal_id,
                    now,
                ),
            )
            self.store.append_audit(
                case,
                "decision.ballot.closed",
                context.principal_id,
                {
                    "case_id": ballot["case_id"],
                    "ballot_id": ballot_id,
                    "outcome_id": outcome_id,
                    "outcome_digest": outcome["digest"],
                    "passed": outcome["passed"],
                    "quorum_met": outcome["quorum_met"],
                    "counted_vote_ids": outcome["counted_vote_ids"],
                },
            )
            signed_receipt = self._sign_receipt(case, "ballot_outcome", outcome_id, outcome["digest"])
            return {"id": outcome_id, "case_id": ballot["case_id"], **outcome, "signed_receipt": signed_receipt}

        return self._mutate(context, idempotency_key, "close_ballot", request, close_round)

    def get_ballot(self, context: ActorContext, ballot_id: str) -> dict[str, Any]:
        ballot = self._ballot(context.namespace_id, ballot_id)
        self._membership(context, ballot["case_id"])
        votes = self.store.current_votes(context.namespace_id, ballot_id)
        if ballot["visibility"] == "hidden_until_close" and ballot["state"] == "open":
            visible_votes: list[dict[str, Any]] = []
        else:
            visible_votes = [
                {
                    "id": vote["id"],
                    "principal_id": vote["principal_id"],
                    "revision": vote["revision"],
                    "choice": vote["choice"],
                    "rationale": vote["rationale"],
                    "commitment": vote["commitment"],
                }
                for vote in votes
            ]
        outcome = self.store.one(
            """
            SELECT * FROM decision_ballot_outcomes
            WHERE namespace_id = ? AND ballot_id = ?
            """,
            (context.namespace_id, ballot_id),
        )
        return {
            **ballot,
            "eligibility": self.store.eligible_voters(context.namespace_id, ballot_id),
            "votes": visible_votes,
            "outcome": json.loads(outcome["outcome_json"]) if outcome else None,
        }

    # -- adoption and authorization -----------------------------------------

    def adopt_recommendation(
        self,
        context: ActorContext,
        case_id: str,
        *,
        recommendation_revision_id: str,
        outcome_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {
            "case_id": case_id,
            "recommendation_revision_id": recommendation_revision_id,
            "outcome_id": outcome_id,
        }

        def adopt() -> dict[str, Any]:
            case = self._case(context.namespace_id, case_id)
            self._require(context, case_id, "adopt")
            revision = self._revision(context.namespace_id, recommendation_revision_id)
            if revision["case_id"] != case_id or revision["kind"] != "recommendation":
                raise DecisionPolicyViolation("only a recommendation revision in this case can be adopted")
            outcome = self.store.get_outcome(context.namespace_id, outcome_id)
            if outcome is None or outcome["case_id"] != case_id:
                raise DecisionNotFound(outcome_id)
            if outcome["outcome"]["target_revision_id"] != recommendation_revision_id:
                raise DecisionPolicyViolation("ballot outcome targets a different revision")
            if not outcome["outcome"]["passed"]:
                raise DecisionPolicyViolation("a failed ballot cannot adopt a recommendation")
            adoption_id = _new_id("adp")
            now = utc_now()
            body = {
                "format": "aetnamem-decision-adoption-v1",
                "adoption_id": adoption_id,
                "case_id": case_id,
                "target_revision_id": recommendation_revision_id,
                "target_digest": revision["digest"],
                "outcome_id": outcome_id,
                "outcome_digest": outcome["digest"],
                "adopted_by": context.principal_id,
            }
            digest = digest_json(body)
            try:
                self.store.execute(
                    """
                    INSERT INTO decision_adoptions(
                      namespace_id, id, case_id, target_revision_id, target_digest,
                      outcome_id, digest, adopted_by, adopted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        context.namespace_id,
                        adoption_id,
                        case_id,
                        recommendation_revision_id,
                        revision["digest"],
                        outcome_id,
                        digest,
                        context.principal_id,
                        now,
                    ),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc):
                    raise DecisionConflict("recommendation revision is already adopted") from exc
                raise
            self.store.append_audit(
                case,
                "decision.recommendation.adopted",
                context.principal_id,
                {"case_id": case_id, "adoption_id": adoption_id, "target_revision_id": recommendation_revision_id, "digest": digest},
            )
            signed_receipt = self._sign_receipt(case, "adoption", adoption_id, digest)
            return {"id": adoption_id, **body, "digest": digest, "created_at": now, "signed_receipt": signed_receipt}

        return self._mutate(context, idempotency_key, "adopt_recommendation", request, adopt)

    def approve_change(
        self,
        context: ActorContext,
        case_id: str,
        *,
        plan_revision_id: str,
        decision: str = "approve",
        rationale: str = "",
        idempotency_key: str,
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise ValueError("approval decision must be approve or reject")
        request = {
            "case_id": case_id,
            "plan_revision_id": plan_revision_id,
            "decision": decision,
            "rationale": rationale,
        }

        def approve() -> dict[str, Any]:
            case = self._case(context.namespace_id, case_id)
            self._require(context, case_id, "approve")
            revision = self._revision(context.namespace_id, plan_revision_id)
            if revision["case_id"] != case_id or revision["kind"] != "implementation_plan":
                raise DecisionPolicyViolation("approval must target an implementation plan")
            approval_id = _new_id("apr")
            body = {
                "format": "aetnamem-decision-approval-v1",
                "approval_id": approval_id,
                "case_id": case_id,
                "target_revision_id": plan_revision_id,
                "target_digest": revision["digest"],
                "principal_id": context.principal_id,
                "decision": decision,
                "rationale_digest": digest_json(rationale),
            }
            digest = digest_json(body)
            now = utc_now()
            try:
                self.store.execute(
                    """
                    INSERT INTO decision_approval_records(
                      namespace_id, id, case_id, target_revision_id, target_digest,
                      principal_id, decision, rationale_json, digest, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        context.namespace_id,
                        approval_id,
                        case_id,
                        plan_revision_id,
                        revision["digest"],
                        context.principal_id,
                        decision,
                        _json({"text": rationale}),
                        digest,
                        now,
                    ),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc):
                    raise DecisionConflict("principal already decided this plan revision") from exc
                raise
            self.store.append_audit(
                case,
                "decision.change.approved" if decision == "approve" else "decision.change.rejected",
                context.principal_id,
                {"case_id": case_id, "approval_id": approval_id, "target_revision_id": plan_revision_id, "digest": digest},
            )
            signed_receipt = self._sign_receipt(case, "approval", approval_id, digest)
            return {"id": approval_id, **body, "digest": digest, "created_at": now, "signed_receipt": signed_receipt}

        return self._mutate(context, idempotency_key, "approve_change", request, approve)

    def grant_authorization(
        self,
        context: ActorContext,
        case_id: str,
        *,
        plan_revision_id: str,
        adoption_id: str,
        approval_ids: tuple[str, ...],
        scope: dict[str, Any],
        required_approvals: int = 1,
        expires_at: str | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if required_approvals < 1:
            raise ValueError("required_approvals must be positive")
        if expires_at is not None and _parse_time(expires_at) <= datetime.now(timezone.utc):
            raise ValueError("authorization expiry must be in the future")
        request = {
            "case_id": case_id,
            "plan_revision_id": plan_revision_id,
            "adoption_id": adoption_id,
            "approval_ids": approval_ids,
            "scope": scope,
            "required_approvals": required_approvals,
            "expires_at": expires_at,
        }

        def grant() -> dict[str, Any]:
            case = self._case(context.namespace_id, case_id)
            self._require(context, case_id, "authorize")
            plan = self._revision(context.namespace_id, plan_revision_id)
            if plan["case_id"] != case_id or plan["kind"] != "implementation_plan":
                raise DecisionPolicyViolation("authorization must target an implementation plan")
            adoption = self.store.get_adoption(context.namespace_id, adoption_id)
            if adoption is None or adoption["case_id"] != case_id:
                raise DecisionNotFound(adoption_id)
            links = self.store.list_links(context.namespace_id, plan_revision_id)
            if not any(
                link["source_revision_id"] == adoption["target_revision_id"]
                and link["source_digest"] == adoption["target_digest"]
                and link["role"] in {"implements", "derived_from"}
                for link in links
            ):
                raise DecisionPolicyViolation("implementation plan is not linked to the adopted recommendation")
            approvals: list[dict[str, Any]] = []
            for approval_id in sorted(set(approval_ids)):
                approval = self.store.one(
                    """
                    SELECT * FROM decision_approval_records
                    WHERE namespace_id = ? AND case_id = ? AND id = ?
                    """,
                    (context.namespace_id, case_id, approval_id),
                )
                if (
                    approval is None
                    or approval["target_revision_id"] != plan_revision_id
                    or approval["target_digest"] != plan["digest"]
                    or approval["decision"] != "approve"
                ):
                    raise DecisionPolicyViolation(f"invalid approval for this plan: {approval_id}")
                approvals.append(approval)
            if len({row["principal_id"] for row in approvals}) < required_approvals:
                raise DecisionPolicyViolation("approval policy has not been satisfied")
            authorization_id = _new_id("aut")
            body = {
                "format": "aetnamem-decision-authorization-v1",
                "authorization_id": authorization_id,
                "case_id": case_id,
                "plan_revision_id": plan_revision_id,
                "plan_digest": plan["digest"],
                "adoption_id": adoption_id,
                "adoption_digest": adoption["digest"],
                "approval_digests": sorted(row["digest"] for row in approvals),
                "scope": scope,
                "expires_at": expires_at,
                "granted_by": context.principal_id,
            }
            digest = digest_json(body)
            now = utc_now()
            self.store.execute(
                """
                INSERT INTO decision_authorizations(
                  namespace_id, id, case_id, plan_revision_id, plan_digest,
                  adoption_id, approval_ids_json, scope_json, status, expires_at,
                  digest, granted_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    context.namespace_id,
                    authorization_id,
                    case_id,
                    plan_revision_id,
                    plan["digest"],
                    adoption_id,
                    _json([row["id"] for row in approvals]),
                    _json(scope),
                    expires_at,
                    digest,
                    context.principal_id,
                    now,
                ),
            )
            self.store.append_audit(
                case,
                "decision.authorization.granted",
                context.principal_id,
                {
                    "case_id": case_id,
                    "authorization_id": authorization_id,
                    "plan_revision_id": plan_revision_id,
                    "plan_digest": plan["digest"],
                    "adoption_id": adoption_id,
                    "approval_ids": [row["id"] for row in approvals],
                    "authorization_digest": digest,
                    "expires_at": expires_at,
                },
            )
            signed_receipt = self._sign_receipt(case, "authorization", authorization_id, digest)
            return {"id": authorization_id, **body, "digest": digest, "status": "active", "created_at": now, "signed_receipt": signed_receipt}

        return self._mutate(context, idempotency_key, "grant_authorization", request, grant)

    def revoke_authorization(
        self,
        context: ActorContext,
        authorization_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {"authorization_id": authorization_id, "reason": reason}

        def revoke() -> dict[str, Any]:
            authorization = self.store.get_authorization(context.namespace_id, authorization_id)
            if authorization is None:
                raise DecisionNotFound(authorization_id)
            case = self._case(context.namespace_id, authorization["case_id"])
            self._require(context, authorization["case_id"], "authorize")
            if authorization["status"] != "active":
                raise DecisionStateError("authorization is not active")
            reason_digest = digest_json(reason)
            now = utc_now()
            self.store.execute(
                """
                UPDATE decision_authorizations
                SET status = 'revoked', revoked_at = ?
                WHERE namespace_id = ? AND id = ? AND status = 'active'
                """,
                (now, context.namespace_id, authorization_id),
            )
            self.store.append_audit(
                case,
                "decision.authorization.revoked",
                context.principal_id,
                {"case_id": authorization["case_id"], "authorization_id": authorization_id, "reason_digest": reason_digest},
            )
            return {"id": authorization_id, "status": "revoked", "revoked_at": now, "reason_digest": reason_digest}

        return self._mutate(context, idempotency_key, "revoke_authorization", request, revoke)

    # -- retention and logical purge ---------------------------------------

    def set_retention_policy(
        self,
        context: ActorContext,
        case_id: str,
        *,
        payload_days: int | None,
        coi_days: int | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if payload_days is not None and payload_days < 0:
            raise ValueError("payload_days must be non-negative or None")
        if coi_days is not None and coi_days < 0:
            raise ValueError("coi_days must be non-negative or None")
        request = {"case_id": case_id, "payload_days": payload_days, "coi_days": coi_days}

        def configure() -> dict[str, Any]:
            case = self._case(context.namespace_id, case_id)
            self._require(context, case_id, "manage_retention")
            now = utc_now()
            self.store.execute(
                """INSERT INTO decision_retention_policies(
                     namespace_id, case_id, payload_days, coi_days, updated_by, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(namespace_id, case_id) DO UPDATE SET
                     payload_days=excluded.payload_days, coi_days=excluded.coi_days,
                     updated_by=excluded.updated_by, updated_at=excluded.updated_at""",
                (context.namespace_id, case_id, payload_days, coi_days, context.principal_id, now),
            )
            policy_digest = digest_json(request)
            self.store.append_audit(
                case,
                "decision.retention.configured",
                context.principal_id,
                {"case_id": case_id, "policy_digest": policy_digest},
            )
            return {**request, "updated_by": context.principal_id, "updated_at": now, "digest": policy_digest}

        return self._mutate(context, idempotency_key, "set_retention_policy", request, configure)

    def purge_due_payloads(
        self,
        context: ActorContext,
        case_id: str,
        *,
        categories: tuple[str, ...] = ("payload", "coi"),
        as_of: str | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        selected = tuple(sorted(set(categories)))
        if not selected or not set(selected).issubset({"payload", "coi"}):
            raise ValueError("categories must contain payload and/or coi")
        if as_of is not None:
            _parse_time(as_of)
        request = {"case_id": case_id, "categories": selected, "as_of": as_of}

        def purge() -> dict[str, Any]:
            case = self._case(context.namespace_id, case_id)
            self._require(context, case_id, "manage_retention")
            policy = self.store.one(
                """SELECT * FROM decision_retention_policies
                   WHERE namespace_id = ? AND case_id = ?""",
                (context.namespace_id, case_id),
            )
            if policy is None:
                raise DecisionPolicyViolation("configure retention before purging decision payloads")
            moment = _parse_time(as_of) if as_of else datetime.now(timezone.utc)
            now = moment.isoformat()
            cutoffs: dict[str, str] = {}
            items: list[dict[str, str]] = []
            if "payload" in selected and policy["payload_days"] is not None:
                cutoff = (moment - timedelta(days=int(policy["payload_days"]))).isoformat()
                cutoffs["payload"] = cutoff
                items.extend(self._purge_payload_rows(context.namespace_id, case_id, cutoff, now))
            if "coi" in selected and policy["coi_days"] is not None:
                cutoff = (moment - timedelta(days=int(policy["coi_days"]))).isoformat()
                cutoffs["coi"] = cutoff
                items.extend(self._purge_coi_rows(context.namespace_id, case_id, cutoff, now))
            receipt_id = _new_id("pur")
            body = {
                "format": "aetnamem-decision-purge-receipt-v1",
                "receipt_id": receipt_id,
                "case_id": case_id,
                "categories": list(selected),
                "cutoffs": cutoffs,
                "items": sorted(items, key=lambda row: (row["kind"], row["id"])),
                "purged_by": context.principal_id,
                "created_at": now,
            }
            digest = digest_json(body)
            self.store.execute(
                """INSERT INTO decision_purge_receipts(
                     namespace_id, id, case_id, categories_json, items_json,
                     cutoff_at, digest, purged_by, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    context.namespace_id,
                    receipt_id,
                    case_id,
                    _json(selected),
                    _json(body["items"]),
                    _json(cutoffs),
                    digest,
                    context.principal_id,
                    now,
                ),
            )
            self.store.append_audit(
                case,
                "decision.payloads.purged",
                context.principal_id,
                {
                    "case_id": case_id,
                    "purge_receipt_id": receipt_id,
                    "purge_digest": digest,
                    "categories": list(selected),
                    "purged_count": len(items),
                },
            )
            signed_receipt = self._sign_receipt(case, "purge", receipt_id, digest)
            return {**body, "digest": digest, "signed_receipt": signed_receipt}

        return self._mutate(context, idempotency_key, "purge_due_payloads", request, purge)

    def _purge_payload_rows(
        self, namespace_id: str, case_id: str, cutoff: str, purged_at: str
    ) -> list[dict[str, str]]:
        specifications = (
            ("case_revision", "decision_case_revisions", "digest", "content_json = '{}'", "created_at", "purged_at"),
            ("artifact_revision", "decision_artifact_revisions", "digest", "content_json = '{}'", "created_at", "purged_at"),
            ("vote", "decision_vote_revisions", "commitment", "choice = '[purged]', rationale_json = '{}', salt = '[purged]'", "created_at", "purged_at"),
            ("approval", "decision_approval_records", "digest", "rationale_json = '{}'", "created_at", "purged_at"),
        )
        items: list[dict[str, str]] = []
        for kind, table, digest_column, assignments, time_column, purge_column in specifications:
            rows = self.store.all(
                f"""SELECT id, {digest_column} AS prior_digest FROM {table}
                    WHERE namespace_id = ? AND case_id = ? AND {time_column} <= ?
                      AND {purge_column} IS NULL ORDER BY id""",
                (namespace_id, case_id, cutoff),
            )
            if rows:
                self.store.execute(
                    f"""UPDATE {table} SET {assignments}, {purge_column} = ?
                        WHERE namespace_id = ? AND case_id = ? AND {time_column} <= ?
                          AND {purge_column} IS NULL""",
                    (purged_at, namespace_id, case_id, cutoff),
                )
                items.extend({"kind": kind, "id": str(row["id"]), "prior_digest": str(row["prior_digest"])} for row in rows)
        idempotency_rows = self.store.all(
            """SELECT principal_id, idempotency_key, response_json
               FROM decision_idempotency
               WHERE namespace_id = ? AND case_id = ? AND created_at <= ?
                 AND purged_at IS NULL ORDER BY principal_id, idempotency_key""",
            (namespace_id, case_id, cutoff),
        )
        if idempotency_rows:
            self.store.execute(
                """UPDATE decision_idempotency SET response_json = '{}', purged_at = ?
                   WHERE namespace_id = ? AND case_id = ? AND created_at <= ?
                     AND purged_at IS NULL""",
                (purged_at, namespace_id, case_id, cutoff),
            )
            items.extend(
                {
                    "kind": "idempotency_response",
                    "id": f"{row['principal_id']}:{row['idempotency_key']}",
                    "prior_digest": digest_json(json.loads(row["response_json"])),
                }
                for row in idempotency_rows
            )
        if case := self.store.one(
            """SELECT id, title FROM decision_cases WHERE namespace_id = ? AND id = ?
               AND created_at <= ? AND payload_purged_at IS NULL""",
            (namespace_id, case_id, cutoff),
        ):
            items.append({"kind": "case_title", "id": str(case["id"]), "prior_digest": digest_json(case["title"])})
            self.store.execute(
                """UPDATE decision_cases SET title = '[purged]', payload_purged_at = ?
                   WHERE namespace_id = ? AND id = ? AND payload_purged_at IS NULL""",
                (purged_at, namespace_id, case_id),
            )
        return items

    def _purge_coi_rows(
        self, namespace_id: str, case_id: str, cutoff: str, purged_at: str
    ) -> list[dict[str, str]]:
        rows = self.store.all(
            """SELECT id, details_digest AS prior_digest FROM decision_conflicts
               WHERE namespace_id = ? AND case_id = ? AND created_at <= ?
                 AND purged_at IS NULL ORDER BY id""",
            (namespace_id, case_id, cutoff),
        )
        if rows:
            self.store.execute(
                """UPDATE decision_conflicts SET details_json = '{}', purged_at = ?
                   WHERE namespace_id = ? AND case_id = ? AND created_at <= ?
                     AND purged_at IS NULL""",
                (purged_at, namespace_id, case_id, cutoff),
            )
        return [
            {"kind": "conflict", "id": str(row["id"]), "prior_digest": str(row["prior_digest"])}
            for row in rows
        ]

    # -- query/export --------------------------------------------------------

    def list_events(
        self, context: ActorContext, case_id: str, *, after_sequence: int = 0
    ) -> list[dict[str, Any]]:
        self._membership(context, case_id)
        return self.store.list_events(context.namespace_id, case_id, after_sequence=after_sequence)

    def export_case(self, context: ActorContext, case_id: str) -> dict[str, Any]:
        case = self.get_case(context, case_id)
        namespace = context.namespace_id
        artifacts = self.store.all(
            "SELECT * FROM decision_artifacts WHERE namespace_id = ? AND case_id = ? ORDER BY created_at, id",
            (namespace, case_id),
        )
        revisions = self.store.all(
            "SELECT * FROM decision_artifact_revisions WHERE namespace_id = ? AND case_id = ? ORDER BY artifact_id, revision",
            (namespace, case_id),
        )
        for row in revisions:
            row["content"] = json.loads(row.pop("content_json"))
            row["links"] = self.store.list_links(namespace, row["id"])
        ballots = self.store.all(
            "SELECT * FROM decision_ballots WHERE namespace_id = ? AND case_id = ? ORDER BY opened_at, id",
            (namespace, case_id),
        )
        for ballot in ballots:
            ballot["choices"] = json.loads(ballot.pop("choices_json"))
            ballot["policy"] = json.loads(ballot.pop("policy_json"))
            ballot["eligibility"] = self.store.eligible_voters(namespace, ballot["id"])
            ballot["votes"] = (
                []
                if ballot["visibility"] == "hidden_until_close" and ballot["state"] == "open"
                else self.store.current_votes(namespace, ballot["id"])
            )
            outcome = self.store.one(
                "SELECT * FROM decision_ballot_outcomes WHERE namespace_id = ? AND ballot_id = ?",
                (namespace, ballot["id"]),
            )
            if outcome:
                outcome["outcome"] = json.loads(outcome.pop("outcome_json"))
            ballot["outcome"] = outcome
        adoptions = self.store.all(
            "SELECT * FROM decision_adoptions WHERE namespace_id = ? AND case_id = ? ORDER BY adopted_at",
            (namespace, case_id),
        )
        approvals = self.store.all(
            "SELECT * FROM decision_approval_records WHERE namespace_id = ? AND case_id = ? ORDER BY created_at",
            (namespace, case_id),
        )
        for approval in approvals:
            approval["rationale"] = json.loads(approval.pop("rationale_json"))
        authorizations = self.store.all(
            "SELECT * FROM decision_authorizations WHERE namespace_id = ? AND case_id = ? ORDER BY created_at",
            (namespace, case_id),
        )
        for authorization in authorizations:
            authorization["approval_ids"] = json.loads(authorization.pop("approval_ids_json"))
            authorization["scope"] = json.loads(authorization.pop("scope_json"))
        retention_policy = self.store.one(
            """SELECT * FROM decision_retention_policies
               WHERE namespace_id = ? AND case_id = ?""",
            (namespace, case_id),
        )
        purge_receipts = self.store.all(
            """SELECT * FROM decision_purge_receipts
               WHERE namespace_id = ? AND case_id = ? ORDER BY created_at, id""",
            (namespace, case_id),
        )
        for receipt in purge_receipts:
            receipt["categories"] = json.loads(receipt.pop("categories_json"))
            receipt["items"] = json.loads(receipt.pop("items_json"))
            receipt["cutoffs"] = json.loads(receipt.pop("cutoff_at"))
        signatures = self.store.list_signatures(namespace, case_id)
        body = {
            "format": "aetnamem-decision-bundle-v1",
            "case": case,
            "template": self.store.get_template(case)["template"],
            "artifacts": artifacts,
            "revisions": revisions,
            "ballots": ballots,
            "adoptions": adoptions,
            "approvals": approvals,
            "authorizations": authorizations,
            "retention_policy": retention_policy,
            "purge_receipts": purge_receipts,
            "signatures": signatures,
            "audit_head": _audit_head(self.store, case["audit_scope_id"]),
        }
        return {**body, "bundle_digest": digest_json(body)}

    # -- internals -----------------------------------------------------------

    def _mutate(
        self,
        context: ActorContext,
        key: str,
        command: str,
        request: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        if not key:
            raise ValueError("idempotency_key is required for every mutation")
        self._verify_actor(context)
        request_digest = digest_json({"command": command, "request": request})
        with self.store.transaction():
            prior = self.store.find_idempotent(context.namespace_id, context.principal_id, key)
            if prior:
                if prior["command"] != command or prior["request_digest"] != request_digest:
                    raise DecisionConflict("idempotency key was reused with a different request")
                if prior.get("purged_at"):
                    raise DecisionStateError("the retained idempotency response has been purged")
                return prior["response"]
            response = operation()
            self.store.record_idempotent(
                context.namespace_id,
                context.principal_id,
                key,
                command,
                request_digest,
                response,
                utc_now(),
                str(response.get("case_id") or request.get("case_id") or response.get("id"))
                if command == "create_case" or response.get("case_id") or request.get("case_id")
                else None,
            )
            return response

    def _verify_actor(self, context: ActorContext) -> None:
        if context.attestation is None:
            if self.require_attestations:
                raise DecisionPolicyViolation("a signed principal attestation is required")
            return
        if self.attestation_verifier is None:
            if self.require_attestations:
                raise DecisionPolicyViolation("no principal attestation verifier is configured")
            return
        try:
            attestation = PrincipalAttestation.from_dict(context.attestation)
        except (KeyError, TypeError, ValueError) as exc:
            raise DecisionPolicyViolation("principal attestation is malformed") from exc
        if not verify_principal_attestation(
            attestation,
            self.attestation_verifier,
            namespace_id=context.namespace_id,
            principal_id=context.principal_id,
            assurance=context.assurance,
        ):
            raise DecisionPolicyViolation("principal attestation is invalid or expired")

    def _sign_receipt(
        self,
        case: dict[str, Any],
        kind: str,
        object_id: str,
        object_digest: str,
    ) -> dict[str, Any] | None:
        if self.receipt_signer is None:
            return None
        signed = receipt_digest(kind, object_id, object_digest)
        envelope = self.receipt_signer.sign_digest(signed)
        now = utc_now()
        self.store.execute(
            """INSERT INTO decision_signatures(
                 namespace_id, id, case_id, object_kind, object_id, object_digest,
                 receipt_digest, signature_json, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                case["namespace_id"],
                _new_id("sig"),
                case["id"],
                kind,
                object_id,
                object_digest,
                signed,
                _json(envelope.to_dict()),
                now,
            ),
        )
        return {
            "format": "aetnamem-decision-receipt-v1",
            "kind": kind,
            "object_id": object_id,
            "object_digest": object_digest,
            "receipt_digest": signed,
            "signature": envelope.to_dict(),
        }

    def _case(self, namespace_id: str, case_id: str) -> dict[str, Any]:
        case = self.store.get_case(namespace_id, case_id)
        if case is None:
            raise DecisionNotFound(case_id)
        return case

    def _artifact(self, namespace_id: str, artifact_id: str) -> dict[str, Any]:
        artifact = self.store.get_artifact(namespace_id, artifact_id)
        if artifact is None:
            raise DecisionNotFound(artifact_id)
        return artifact

    def _revision(self, namespace_id: str, revision_id: str) -> dict[str, Any]:
        revision = self.store.get_revision(namespace_id, revision_id)
        if revision is None:
            raise DecisionNotFound(revision_id)
        return revision

    def _ballot(self, namespace_id: str, ballot_id: str) -> dict[str, Any]:
        ballot = self.store.get_ballot(namespace_id, ballot_id)
        if ballot is None:
            raise DecisionNotFound(ballot_id)
        return ballot

    def _membership(self, context: ActorContext, case_id: str) -> dict[str, Any]:
        self._case(context.namespace_id, case_id)
        member = self.store.get_membership(context.namespace_id, case_id, context.principal_id)
        if member is None or member["status"] != "active":
            raise DecisionPolicyViolation("principal is not an active case member")
        return member

    def _require(self, context: ActorContext, case_id: str, capability: str) -> dict[str, Any]:
        member = self._membership(context, case_id)
        if capability not in member["capabilities"]:
            raise DecisionPolicyViolation(f"principal lacks capability: {capability}")
        return member

    def _bump_case(self, case: dict[str, Any], expected_version: int) -> None:
        cursor = self.store.execute(
            """
            UPDATE decision_cases SET version = version + 1, updated_at = ?
            WHERE namespace_id = ? AND id = ? AND version = ?
            """,
            (utc_now(), case["namespace_id"], case["id"], expected_version),
        )
        if cursor.rowcount != 1:
            raise DecisionConflict("stale case version")

    def _validate_artifact(self, case: dict[str, Any], kind: str, content: dict[str, Any]) -> None:
        if not kind or not isinstance(content, dict):
            raise ValueError("artifact kind and object content are required")
        if kind == "criterion_assessment":
            template = DecisionTemplate.from_dict(self.store.get_template(case)["template"])
            criterion_key = str(content.get("criterion", ""))
            judgment = str(content.get("judgment", ""))
            criterion = template.criterion(criterion_key)
            if judgment not in criterion.choices:
                raise ValueError(f"invalid judgment for {criterion_key}: {judgment}")
            for rating in content.get("ratings", ()):
                scheme = str(rating.get("scheme", ""))
                if criterion.rating_schemes and scheme not in criterion.rating_schemes:
                    raise ValueError(f"rating scheme is not allowed for {criterion_key}: {scheme}")

    def _validated_links(
        self, namespace_id: str, case_id: str, links: tuple[ArtifactLink, ...]
    ) -> list[tuple[dict[str, Any], str]]:
        validated: list[tuple[dict[str, Any], str]] = []
        for link in links:
            source = self._revision(namespace_id, link.source_revision_id)
            if source["case_id"] != case_id:
                raise DecisionNotFound(link.source_revision_id)
            validated.append((source, link.role))
        return validated

    def _insert_links(
        self,
        namespace_id: str,
        case_id: str,
        target_revision_id: str,
        sources: list[tuple[dict[str, Any], str]],
        now: str,
    ) -> None:
        for source, role in sources:
            self.store.execute(
                """
                INSERT INTO decision_artifact_links(
                  namespace_id, case_id, target_revision_id, source_revision_id,
                  source_digest, role, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (namespace_id, case_id, target_revision_id, source["id"], source["digest"], role, now),
            )

    def _is_recused(
        self,
        namespace_id: str,
        case_id: str,
        principal_id: str,
        *,
        artifact_id: str,
        revision_id: str,
    ) -> bool:
        scopes = {"case", f"artifact:{artifact_id}", f"revision:{revision_id}"}
        placeholders = ",".join("?" for _ in scopes)
        row = self.store.one(
            f"""
            SELECT id FROM decision_conflicts
            WHERE namespace_id = ? AND case_id = ? AND principal_id = ?
              AND status = 'recused' AND scope IN ({placeholders}) LIMIT 1
            """,
            (namespace_id, case_id, principal_id, *sorted(scopes)),
        )
        return row is not None


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _audit_head(store: SQLiteDecisionStore, audit_scope_id: str) -> dict[str, Any] | None:
    row = store.one(
        """
        SELECT sequence, event_hash FROM audit_log
        WHERE subject_id = ? ORDER BY sequence DESC LIMIT 1
        """,
        (audit_scope_id,),
    )
    return row
