"""Tool broker: the single choke point through which tools execute.

The broker sorts every registered tool into one of three kinds:

* ``READ_ONLY`` — pure observation. Executed directly; the call and a digest of
  its result join the audit chain as a ``tool.read`` event.
* ``MEMORY`` — memory mutations (remember/forget/promote). Executed through the
  already-governed :class:`~aetnamem.memory.Memory` engine, which quarantines
  untrusted content and audits every transition. No approval gate: memory is
  governed by provenance and quarantine, not by human sign-off.
* ``GUARDED`` — external-world effects (filesystem, and later messaging APIs).
  A call only *stages* a canonical :class:`WorldPatch`; it never executes. A
  separate reviewer holding the approval key must sign the exact plan before
  :class:`~aetnamem.actions.ActionEngine` will commit it.

The host attaches an :class:`AuthorityRef` for the current user task. In
``enforce`` mode a guarded operation needs ``authorized_by`` authority carrying
a trusted tier, so a tool call that traces only to untrusted content (a
summarized webpage, a tool result) cannot even be staged. The reviewer's
before/after approval is the second, independent gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from aetnamem.actions import ActionEngine, EvidenceRef, OperationProposal
from aetnamem.actions.policy import ActionPolicyViolation
from aetnamem.core.canonical import canonical_json, sha256_hex


class ToolKind(str, Enum):
    READ_ONLY = "read_only"
    MEMORY = "memory"
    GUARDED = "guarded"


class UnknownToolError(KeyError):
    """Raised when an assistant calls a tool that is not registered."""


def digest_text(value: str) -> str:
    """SHA-256 hex of a string — e.g. to bind a user task as authority."""
    return sha256_hex(value.encode("utf-8"))


@dataclass(frozen=True)
class AuthorityRef:
    """A host-attested authority for the current task.

    The host (the app hosting the assistant loop) is responsible for setting
    ``attested=True`` and a trusted ``trust_tier`` only for genuine user
    instructions. The engine validates the label but does not authenticate the
    host — protect the staging boundary at deployment.
    """

    ref_id: str
    digest: str
    kind: str = "user_task"
    trust_tier: str = "trusted_user"
    attested: bool = True

    @classmethod
    def from_task(cls, ref_id: str, task_text: str, **kwargs: Any) -> "AuthorityRef":
        return cls(ref_id=ref_id, digest=digest_text(task_text), **kwargs)

    def as_evidence(self) -> EvidenceRef:
        return EvidenceRef(
            kind=self.kind,
            ref_id=self.ref_id,
            digest=self.digest,
            relation="authorized_by",
            trust_tier=self.trust_tier,
            attested=self.attested,
        )


@dataclass(frozen=True)
class BrokerContext:
    """Per-call context supplied by the host, never by the model."""

    subject_id: str
    actor_id: str
    session_id: str | None = None
    turn_id: str | int | None = None
    authority: AuthorityRef | None = None
    source_type: str = "tool_output"
    user_attested: bool = False
    # Additional evidence the model or host cited as *informing* the action
    # (e.g. a recalled memory record). Never upgraded to authority.
    informed_by: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    """What the broker hands back to the assistant loop.

    ``ok`` is True when the tool ran (read-only/memory) or when a guarded action
    was successfully staged for review. ``status`` distinguishes the guarded
    ``awaiting_approval`` case from ``executed``. ``data`` is model-safe.
    """

    ok: bool
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "status": self.status, "data": self.data, "message": self.message}


@dataclass
class ToolSpec:
    name: str
    kind: ToolKind
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any] | None = None  # READ_ONLY / MEMORY
    adapter: str | None = None                 # GUARDED
    operation: str | None = None               # GUARDED
    arg_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolBroker:
    """Registry + dispatcher. The only object an assistant loop talks to."""

    def __init__(self, engine: ActionEngine) -> None:
        self.engine = engine
        self.memory = engine.memory
        self._tools: dict[str, ToolSpec] = {}

    # -- registration ---------------------------------------------------------

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        if spec.kind is ToolKind.GUARDED:
            if not spec.adapter or not spec.operation:
                raise ValueError("guarded tools require adapter and operation")
            if spec.adapter not in self.engine.adapters:
                raise ValueError(f"no adapter registered on the engine: {spec.adapter}")
        elif spec.handler is None:
            raise ValueError("read-only and memory tools require a handler")
        self._tools[spec.name] = spec

    def register_read_only(
        self, name: str, description: str, input_schema: dict[str, Any], handler: Callable[..., Any]
    ) -> None:
        self.register(ToolSpec(name, ToolKind.READ_ONLY, description, input_schema, handler=handler))

    def register_memory(
        self, name: str, description: str, input_schema: dict[str, Any], handler: Callable[..., Any]
    ) -> None:
        self.register(ToolSpec(name, ToolKind.MEMORY, description, input_schema, handler=handler))

    def register_guarded(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        *,
        adapter: str,
        operation: str,
        arg_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.register(
            ToolSpec(
                name,
                ToolKind.GUARDED,
                description,
                input_schema,
                adapter=adapter,
                operation=operation,
                arg_mapper=arg_mapper,
            )
        )

    def register_default_memory_tools(self, *, include_promote: bool = False) -> None:
        """Register the standard memory verbs as broker tools.

        ``promote`` is a trust transition; expose it only where the assistant is
        permitted to request quarantine release (usually reviewer-only).
        """
        m = self.memory

        def remember(ctx: BrokerContext, message: str) -> Any:
            return m.remember(
                ctx.subject_id,
                message,
                force=ctx.user_attested,
                session_id=ctx.session_id,
                turn_id=ctx.turn_id,
                source_type=ctx.source_type,
                actor=ctx.actor_id,
            )

        def forget(ctx: BrokerContext, utterance=None, selector=None) -> Any:
            if not ctx.user_attested:
                raise ActionPolicyViolation(
                    "memory deletion requires a host-attested user request"
                )
            return m.forget(
                ctx.subject_id,
                selector,
                utterance=utterance,
                session_id=ctx.session_id,
                turn_id=ctx.turn_id,
            )

        def promote(ctx: BrokerContext, record_id: str) -> Any:
            if not ctx.user_attested:
                raise ActionPolicyViolation(
                    "memory promotion requires host-attested human confirmation"
                )
            return m.promote(ctx.subject_id, record_id)

        self.register_read_only(
            "memory_recall",
            "Search durable memory for facts relevant to a query.",
            {
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query"],
            },
            lambda ctx, query, limit=10: m.recall(
                ctx.subject_id, query, session_id=ctx.session_id, limit=limit
            ),
        )
        self.register_read_only(
            "memory_list",
            "List stored memory records (optionally including inactive ones).",
            {
                "type": "object",
                "properties": {"include_inactive": {"type": "boolean"}},
            },
            lambda ctx, include_inactive=False: m.list(
                ctx.subject_id, include_inactive=include_inactive
            ),
        )
        self.register_memory(
            "memory_remember",
            "Record a durable fact the user explicitly stated.",
            {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
            remember,
        )
        self.register_memory(
            "memory_forget",
            "Logically purge matching memory and return a deletion receipt.",
            {
                "type": "object",
                "properties": {"utterance": {"type": "string"}, "selector": {"type": "string"}},
            },
            forget,
        )
        if include_promote:
            self.register_memory(
                "memory_promote",
                "Release a quarantined record after human confirmation.",
                {
                    "type": "object",
                    "properties": {"record_id": {"type": "string"}},
                    "required": ["record_id"],
                },
                promote,
            )

    # -- introspection --------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        return [spec.public() for spec in self._tools.values()]

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(name) from exc

    # -- dispatch -------------------------------------------------------------

    def dispatch(
        self, name: str, arguments: dict[str, Any], context: BrokerContext
    ) -> ToolResult:
        """Execute (read-only/memory) or stage (guarded) a single tool call."""
        spec = self.get(name)
        arguments = dict(arguments or {})
        if spec.kind is ToolKind.GUARDED:
            return self._stage_guarded(spec, arguments, context)
        try:
            return self._run_local(spec, arguments, context)
        except ActionPolicyViolation as exc:
            return ToolResult(
                ok=False,
                status="refused",
                data={"tool": spec.name, "reason": str(exc)},
                message=f"Refused: {exc}.",
            )

    def _run_local(
        self, spec: ToolSpec, arguments: dict[str, Any], context: BrokerContext
    ) -> ToolResult:
        assert spec.handler is not None
        result = spec.handler(context, **arguments)
        if spec.kind is ToolKind.READ_ONLY:
            # Memory verbs already audit themselves; a bare read-only tool
            # (e.g. an external lookup) records a digest-only tool.read event.
            self.memory.store.append_audit_event(
                subject_id=context.subject_id,
                event_type="tool.read",
                actor=context.actor_id,
                session_id=context.session_id,
                turn_id=_turn(context.turn_id),
                payload={
                    "tool": spec.name,
                    "arguments_digest": _digest(arguments),
                    "result_digest": _digest(result),
                },
            )
        return ToolResult(ok=True, status="executed", data={"result": result})

    def _stage_guarded(
        self, spec: ToolSpec, arguments: dict[str, Any], context: BrokerContext
    ) -> ToolResult:
        op_arguments = spec.arg_mapper(arguments) if spec.arg_mapper else arguments
        evidence: list[EvidenceRef] = list(context.informed_by)
        if context.authority is not None:
            evidence.append(context.authority.as_evidence())
        proposal = OperationProposal(
            key="operation-1",
            adapter=spec.adapter or "",
            operation=spec.operation or "",
            arguments=op_arguments,
            evidence=tuple(evidence),
        )
        try:
            patch = self.engine.propose(
                context.subject_id,
                [proposal],
                actor_id=context.actor_id,
                session_id=context.session_id,
                turn_id=context.turn_id,
            )
        except ActionPolicyViolation as exc:
            return ToolResult(
                ok=False,
                status="refused",
                data={"tool": spec.name, "reason": str(exc)},
                message=(
                    f"Refused: {exc}. This effect needs a genuine, host-attested "
                    "user task as its authority — untrusted content cannot authorize it."
                ),
            )
        operation = patch.operations[0] if patch.operations else {}
        return ToolResult(
            ok=True,
            status="awaiting_approval",
            data={
                "tool": spec.name,
                "transaction_id": patch.transaction_id,
                "plan_hash": patch.plan_hash,
                "state": patch.state.value,
                "effect_class": operation.get("effect_class"),
                "preview": operation.get("preview"),
            },
            message=(
                "Staged for review. A human must approve this exact plan before it "
                f"can run (transaction {patch.transaction_id})."
            ),
        )


def _digest(value: Any) -> str:
    return sha256_hex(canonical_json(value))


def _turn(turn_id: str | int | None) -> str | None:
    return None if turn_id is None else str(turn_id)
