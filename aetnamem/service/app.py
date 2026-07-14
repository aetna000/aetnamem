"""Loopback HTTP control service (stdlib only).

Routes are role-scoped: ``agent`` may read and dispatch, ``reviewer`` may also
approve/commit/deny. Tokens are compared in constant time. The server binds to
loopback only; it is not a public API and performs no TLS — it is meant to sit
behind a desktop shell on the same machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
from pathlib import Path
import secrets
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from aetnamem.actions import ActionEngine, ActionStateError, ApprovalAuthority, verify_action
from aetnamem.actions.policy import ActionPolicyViolation
from aetnamem.assistant import AssistantLoop, ProviderConfig
from aetnamem.assistant.providers import provider_from_config
from aetnamem.broker import AuthorityRef, BrokerContext, ToolBroker, UnknownToolError
from aetnamem.service.secrets import MacKeychain
from aetnamem.service.ui import APP_HTML


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class ControlService:
    """Holds the governed core and the two role tokens."""

    broker: ToolBroker
    engine: ActionEngine
    agent_token: str
    reviewer_token: str
    authorities: dict[str, AuthorityRef] = field(default_factory=dict)
    provider_config: ProviderConfig = field(default_factory=ProviderConfig)

    @property
    def memory(self):  # noqa: ANN201 - passthrough
        return self.engine.memory

    # -- role checks ----------------------------------------------------------

    def role_of(self, token: str | None) -> str | None:
        if token and hmac.compare_digest(token, self.reviewer_token):
            return "reviewer"
        if token and hmac.compare_digest(token, self.agent_token):
            return "agent"
        return None

    # -- agent operations -----------------------------------------------------

    def dispatch(self, body: dict[str, Any]) -> dict[str, Any]:
        tool = body.get("tool")
        if not tool:
            raise HttpError(400, "missing 'tool'")
        context = _context_from(body.get("context") or {}, self.authorities)
        try:
            result = self.broker.dispatch(tool, body.get("arguments") or {}, context)
        except UnknownToolError:
            raise HttpError(404, f"unknown tool: {tool}")
        except (ActionStateError, ActionPolicyViolation, ValueError) as exc:
            raise HttpError(409, str(exc))
        return result.to_dict()

    def create_authority(self, body: dict[str, Any]) -> dict[str, Any]:
        subject = body.get("subject_id") or "default"
        task_text = body.get("task_text")
        if not task_text:
            raise HttpError(400, "create authority requires task_text")
        ref_id = body.get("ref_id") or f"task_{secrets.token_hex(12)}"
        authority = AuthorityRef.from_task(ref_id, task_text)
        self.authorities[ref_id] = authority
        self.memory.log_action(
            subject,
            "authority.created",
            payload={"ref_id": ref_id, "digest": authority.digest},
            session_id=body.get("session_id"),
            turn_id=body.get("turn_id"),
        )
        return {"ref_id": ref_id, "digest": authority.digest}

    def remember_user_message(self, body: dict[str, Any]) -> dict[str, Any]:
        subject = body.get("subject_id") or "default"
        message = body.get("message")
        if not message:
            raise HttpError(400, "remember requires message")
        return self.memory.remember(
            subject,
            message,
            session_id=body.get("session_id"),
            turn_id=body.get("turn_id"),
            source_type="user_message",
            actor="user",
        )

    def list_actions(self, query: dict[str, list[str]]) -> dict[str, Any]:
        subject = _one(query, "subject")
        state = _one(query, "state")
        rows = self.engine.list(subject)
        if state:
            rows = [r for r in rows if r.get("state") == state]
        return {"actions": rows}

    def get_action(self, transaction_id: str) -> dict[str, Any]:
        try:
            return self.engine.get(transaction_id)
        except KeyError:
            raise HttpError(404, f"unknown action: {transaction_id}")

    def recall(self, body: dict[str, Any]) -> dict[str, Any]:
        subject = body.get("subject_id")
        query = body.get("query")
        if not subject or not query:
            raise HttpError(400, "recall requires subject_id and query")
        return {"records": self.memory.recall(subject, query, limit=int(body.get("limit", 10)))}

    def list_memory(self, query: dict[str, list[str]]) -> dict[str, Any]:
        subject = _one(query, "subject")
        if not subject:
            raise HttpError(400, "missing 'subject'")
        include = _one(query, "include_inactive") in {"1", "true", "yes"}
        return {"records": self.memory.list(subject, include_inactive=include)}

    def audit(self, query: dict[str, list[str]]) -> dict[str, Any]:
        subject = _one(query, "subject")
        if not subject:
            raise HttpError(400, "missing 'subject'")
        return self.memory.audit(subject)

    def verify(self, query: dict[str, list[str]]) -> dict[str, Any]:
        action_id = _one(query, "action")
        if action_id:
            return verify_action(self.memory.store, action_id)
        subject = _one(query, "subject")
        if not subject:
            raise HttpError(400, "verify requires 'subject' or 'action'")
        return {"audit_chain_valid": self.memory.store.verify_audit_chain(subject)}

    def system_check(self) -> dict[str, Any]:
        import platform
        import shutil

        store_path = self.memory.store.path
        disk_path = "." if store_path == ":memory:" else str(Path(store_path).parent)
        free_disk = shutil.disk_usage(disk_path).free
        return {
            "platform": platform.system(),
            "mac_only_supported": platform.system() == "Darwin",
            "python": platform.python_version(),
            "free_disk_bytes": free_disk,
            "has_min_disk_1gb": free_disk >= 1_000_000_000,
        }

    def configure_provider(self, body: dict[str, Any]) -> dict[str, Any]:
        kind = (body.get("kind") or "echo").strip().lower()
        model = (body.get("model") or "local-echo").strip()
        base_url = (body.get("base_url") or "").strip() or None
        api_key = (body.get("api_key") or "").strip() or None
        if kind != "echo":
            keychain = MacKeychain()
            account = f"provider-{kind}"
            if api_key:
                keychain.set(account, api_key)
            else:
                api_key = keychain.get(account)
        config = ProviderConfig(kind=kind, model=model, api_key=api_key, base_url=base_url)
        provider_from_config(config)  # validate early
        self.provider_config = config
        return {
            "kind": config.kind,
            "model": config.model,
            "base_url": config.base_url,
            "api_key_configured": bool(api_key),
        }

    def provider_status(self) -> dict[str, Any]:
        return {
            "kind": self.provider_config.kind,
            "model": self.provider_config.model,
            "base_url": self.provider_config.base_url,
            "api_key_configured": bool(self.provider_config.api_key),
        }

    def chat(self, body: dict[str, Any]) -> dict[str, Any]:
        subject = body.get("subject_id") or "default"
        message = body.get("message")
        if not message:
            raise HttpError(400, "chat requires message")
        try:
            provider = provider_from_config(self.provider_config)
        except ValueError as exc:
            raise HttpError(409, str(exc))
        loop = AssistantLoop(self.memory, self.broker, provider)
        return loop.chat(
            subject_id=subject,
            message=message,
            session_id=body.get("session_id"),
        )

    # -- reviewer operations --------------------------------------------------

    def approve(self, transaction_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.engine.approval_authority is None:
            raise HttpError(500, "no approval authority configured")
        approver = body.get("approver_label") or "reviewer"
        transaction = self.get_action(transaction_id)
        approval = self.engine.approval_authority.issue(
            transaction_id=transaction_id,
            plan_hash=transaction["plan_hash"],
            approver=approver,
        )
        try:
            return self.engine.approve(approval)
        except (ActionStateError, ValueError) as exc:
            raise HttpError(409, str(exc))

    def commit(self, transaction_id: str) -> dict[str, Any]:
        try:
            return self.engine.commit(transaction_id)
        except ActionStateError as exc:
            raise HttpError(409, str(exc))

    def deny(self, transaction_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.engine.abort(transaction_id, actor=body.get("actor") or "reviewer")
        except ActionStateError as exc:
            raise HttpError(409, str(exc))


def _context_from(raw: dict[str, Any], authorities: dict[str, AuthorityRef]) -> BrokerContext:
    authority = None
    if raw.get("authority"):
        raise HttpError(400, "agent dispatch may reference authority_id but cannot create authority")
    authority_id = raw.get("authority_id")
    if authority_id:
        authority = authorities.get(authority_id)
        if authority is None:
            raise HttpError(409, f"unknown authority_id: {authority_id}")
    source_type = raw.get("source_type") or "tool_output"
    if source_type == "user_message":
        raise HttpError(400, "agent dispatch cannot claim user_message provenance")
    return BrokerContext(
        subject_id=raw.get("subject_id") or "default",
        actor_id=raw.get("actor_id") or "assistant",
        session_id=raw.get("session_id"),
        turn_id=raw.get("turn_id"),
        authority=authority,
        source_type=source_type,
        user_attested=False,
    )


def _one(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


# -- HTTP plumbing -----------------------------------------------------------

# (method, path-pattern) -> (required_role, handler). ``{id}`` matches a segment.
Route = tuple[str, Callable[["ControlService", dict[str, str], dict[str, Any], dict[str, list[str]]], dict[str, Any]]]


def _routes() -> dict[tuple[str, str], Route]:
    return {
        ("GET", "/tools"): ("agent", lambda s, p, b, q: {"tools": s.broker.list_tools()}),
        ("GET", "/system-check"): ("agent", lambda s, p, b, q: s.system_check()),
        ("GET", "/provider"): ("agent", lambda s, p, b, q: s.provider_status()),
        ("POST", "/provider"): ("reviewer", lambda s, p, b, q: s.configure_provider(b)),
        ("POST", "/chat"): ("reviewer", lambda s, p, b, q: s.chat(b)),
        ("POST", "/authority"): ("reviewer", lambda s, p, b, q: s.create_authority(b)),
        ("POST", "/memory/remember-user"): ("reviewer", lambda s, p, b, q: s.remember_user_message(b)),
        ("POST", "/dispatch"): ("agent", lambda s, p, b, q: s.dispatch(b)),
        ("GET", "/actions"): ("agent", lambda s, p, b, q: s.list_actions(q)),
        ("GET", "/actions/{id}"): ("agent", lambda s, p, b, q: s.get_action(p["id"])),
        ("POST", "/actions/{id}/approve"): ("reviewer", lambda s, p, b, q: s.approve(p["id"], b)),
        ("POST", "/actions/{id}/commit"): ("reviewer", lambda s, p, b, q: s.commit(p["id"])),
        ("POST", "/actions/{id}/deny"): ("reviewer", lambda s, p, b, q: s.deny(p["id"], b)),
        ("GET", "/memory"): ("agent", lambda s, p, b, q: s.list_memory(q)),
        ("POST", "/memory/recall"): ("agent", lambda s, p, b, q: s.recall(b)),
        ("GET", "/audit"): ("agent", lambda s, p, b, q: s.audit(q)),
        ("GET", "/verify"): ("agent", lambda s, p, b, q: s.verify(q)),
    }


def _match(routes: dict[tuple[str, str], Route], method: str, path: str):
    want = [seg for seg in path.split("/") if seg]
    for (route_method, pattern), route in routes.items():
        if route_method != method:
            continue
        parts = [seg for seg in pattern.split("/") if seg]
        if len(parts) != len(want):
            continue
        params: dict[str, str] = {}
        for tmpl, value in zip(parts, want):
            if tmpl.startswith("{") and tmpl.endswith("}"):
                params[tmpl[1:-1]] = value
            elif tmpl != value:
                break
        else:
            return route, params
    return None, {}


class _Handler(BaseHTTPRequestHandler):
    server_version = "aetnamem-control/0"

    def log_message(self, *args: Any) -> None:  # quiet by default
        pass

    def _reply(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reply_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _token(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[len("Bearer ") :].strip()
        return None

    def _handle(self, method: str) -> None:
        service: ControlService = self.server.service  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        if method == "GET" and parsed.path in {"/app", "/dashboard"}:
            self._reply_html(200, APP_HTML)
            return
        if method == "GET" and parsed.path in {"/health", "/"}:
            self._reply(200, {"ok": True, "service": "aetnamem-control"})
            return
        route, params = _match(service._route_table, method, parsed.path)
        if route is None:
            self._reply(404, {"error": "not found"})
            return
        required_role, handler = route
        role = service.role_of(self._token())
        if role is None:
            self._reply(401, {"error": "unauthorized"})
            return
        if required_role == "reviewer" and role != "reviewer":
            self._reply(403, {"error": "reviewer token required"})
            return
        body: dict[str, Any] = {}
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._reply(400, {"error": "invalid JSON body"})
                return
        query = parse_qs(parsed.query)
        try:
            self._reply(200, handler(service, params, body, query))
        except HttpError as exc:
            self._reply(exc.status, {"error": exc.message})
        except Exception as exc:  # never leak a stack over the wire
            self._reply(500, {"error": f"internal error: {type(exc).__name__}"})

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")


class _Server(HTTPServer):
    # Single-threaded on purpose: the governed core owns one SQLite connection
    # (bound to its creating thread), and serialized requests also avoid
    # concurrent-writer races. A local single-user sidecar does not need more.

    def __init__(self, address, service: ControlService) -> None:
        super().__init__(address, _Handler)
        self.service = service
        service._route_table = _routes()  # type: ignore[attr-defined]


def serve(
    service: ControlService,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> _Server:
    """Create (but do not block on) the loopback server. Call ``serve_forever``."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("control service binds to loopback only")
    return _Server((host, port), service)


def build_service(
    engine: ActionEngine,
    broker: ToolBroker,
    *,
    agent_token: str | None = None,
    reviewer_token: str | None = None,
) -> ControlService:
    agent = agent_token or secrets.token_urlsafe(32)
    reviewer = reviewer_token or secrets.token_urlsafe(32)
    if hmac.compare_digest(agent, reviewer):
        raise ValueError("agent and reviewer tokens must be distinct")
    return ControlService(
        broker=broker,
        engine=engine,
        agent_token=agent,
        reviewer_token=reviewer,
    )
