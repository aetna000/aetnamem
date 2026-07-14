"""The scoped capability broker: the single tool dispatcher.

Every tool an assistant can reach is registered here. Read-only tools execute
and are audited; memory tools run through the already-governed memory engine;
external-effect (guarded) tools are staged as WorldPatches and cannot execute
until a separate reviewer approves the exact plan. Nothing an assistant calls
bypasses this dispatcher, so "protection of every tool" holds by construction.
"""

from aetnamem.broker.broker import (
    AuthorityRef,
    BrokerContext,
    ToolBroker,
    ToolKind,
    ToolResult,
    ToolSpec,
    UnknownToolError,
)

__all__ = [
    "AuthorityRef",
    "BrokerContext",
    "ToolBroker",
    "ToolKind",
    "ToolResult",
    "ToolSpec",
    "UnknownToolError",
]
