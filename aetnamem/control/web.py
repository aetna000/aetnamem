from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

from aetnamem.control import ControlPlaneManager, ControlMode


class ControlDashboardServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        manager: ControlPlaneManager,
        *,
        html: str,
    ) -> None:
        host, _ = address
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("memory control plane dashboard is loopback-only")
        super().__init__(address, ControlDashboardHandler)
        self.manager = manager
        self.html = html
        self.csrf_token = secrets.token_urlsafe(32)


class ControlDashboardHandler(BaseHTTPRequestHandler):
    server: ControlDashboardServer

    def do_GET(self) -> None:  # noqa: N802
        if not self._valid_host():
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid Host header"})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = self.server.html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self._security_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/session":
            self._json(HTTPStatus.OK, {"csrf_token": self.server.csrf_token})
            return
        if parsed.path == "/api/status":
            self._json(HTTPStatus.OK, self.server.manager.status())
            return
        if parsed.path == "/api/blackbox/runs":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["50"])[0])
                self._json(
                    HTTPStatus.OK,
                    self.server.manager.blackbox_runs(limit=limit),
                )
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if parsed.path in {"/api/blackbox/flight", "/api/blackbox/export"}:
            from aetnamem.control.blackbox import format_flight_report

            params = parse_qs(parsed.query)
            run_id = (params.get("run_id") or [""])[0].strip()
            if not run_id:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "run_id is required"})
                return
            try:
                report = self.server.manager.verify_blackbox_flight(run_id)
            except ValueError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            if parsed.path == "/api/blackbox/flight":
                self._json(HTTPStatus.OK, report)
                return
            output_format = (params.get("format") or ["json"])[0]
            if output_format == "text":
                content = format_flight_report(report)
                content_type = "text/plain; charset=utf-8"
                suffix = "txt"
            elif output_format == "json":
                content = json.dumps(report, indent=2, sort_keys=True) + "\n"
                content_type = "application/json; charset=utf-8"
                suffix = "json"
            else:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "format must be json or text"},
                )
                return
            safe_run = "".join(
                char if char.isalnum() or char in {"-", "_"} else "-"
                for char in run_id
            )[:80]
            self._download(
                content,
                filename=f"aetnamem-blackbox-{safe_run}.{suffix}",
                content_type=content_type,
            )
            return
        if parsed.path == "/api/mirror/search":
            from aetnamem.control.openclaw_native import search_mirror

            query = (parse_qs(parsed.query).get("query") or [""])[0].strip()
            if not query:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "query is required"})
                return
            self._json(
                HTTPStatus.OK,
                search_mirror(self.server.manager.state(), query, limit=12),
            )
            return
        if parsed.path == "/api/mirror/reviews":
            from aetnamem.control.openclaw_native import list_mirror_reviews

            self._json(
                HTTPStatus.OK,
                list_mirror_reviews(self.server.manager.state()),
            )
            return
        if parsed.path == "/api/mirror/media-preview":
            from aetnamem.control.openclaw_native import resolve_mirror_review_image

            record_id = (parse_qs(parsed.query).get("record_id") or [""])[0].strip()
            try:
                preview = resolve_mirror_review_image(
                    self.server.manager.state(), record_id
                )
            except ValueError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            path = preview["path"]
            self.send_response(HTTPStatus.OK)
            self._security_headers()
            self.send_header("Content-Type", str(preview["content_type"]))
            self.send_header("Content-Length", str(preview["bytes"]))
            self.send_header("Content-Disposition", "inline")
            self.send_header(
                "X-AetnaMem-Media-SHA256", str(preview["media_sha256"])
            )
            self.end_headers()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    self.wfile.write(chunk)
            return
        if parsed.path == "/api/mirror/trace":
            from aetnamem.control.openclaw_native import trace_mirror

            query = (parse_qs(parsed.query).get("query") or [""])[0].strip()
            if not query:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "query is required"})
                return
            self._json(
                HTTPStatus.OK,
                trace_mirror(self.server.manager.state(), query, limit=100),
            )
            return
        if parsed.path in {"/api/mirror/audit", "/api/mirror/audit-export"}:
            from aetnamem.control.openclaw_native import (
                export_mirror_audit,
                query_mirror_audit,
            )

            params = parse_qs(parsed.query)
            value = lambda name, default="": (params.get(name) or [default])[0].strip()
            filters = {
                "query": value("query"),
                "event_type": value("event_type"),
                "actor": value("actor"),
                "session_id": value("session_id"),
                "record_id": value("record_id"),
                "since": value("since"),
                "until": value("until"),
                "direction": value("direction", "desc"),
            }
            if parsed.path == "/api/mirror/audit-export":
                output_format = value("format", "json")
                try:
                    content, content_type = export_mirror_audit(
                        self.server.manager.state(),
                        output_format=output_format,
                        filters=filters,
                    )
                except ValueError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._download(
                    content,
                    filename=f"aetnamem-audit-investigation.{output_format}",
                    content_type=content_type,
                )
                return
            cursor_text = value("cursor")
            try:
                cursor = int(cursor_text) if cursor_text else None
                limit = int(value("limit", "100"))
                report = query_mirror_audit(
                    self.server.manager.state(),
                    **filters,
                    cursor=cursor,
                    limit=limit,
                    include_facets=value("include_facets", "0") == "1",
                )
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._json(HTTPStatus.OK, report)
            return
        if parsed.path in {
            "/api/mirror/record",
            "/api/mirror/record-report",
            "/api/mirror/deletion-receipt",
        }:
            from aetnamem.control.openclaw_native import (
                format_mirror_record_report,
                inspect_mirror_record,
            )

            params = parse_qs(parsed.query)
            record_id = (params.get("record_id") or [""])[0].strip()
            if not record_id:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "record_id is required"})
                return
            try:
                report = inspect_mirror_record(self.server.manager.state(), record_id)
            except ValueError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            if parsed.path == "/api/mirror/record":
                self._json(HTTPStatus.OK, report)
                return
            if parsed.path == "/api/mirror/deletion-receipt":
                receipt = report.get("deletion_receipt")
                if not receipt:
                    self._json(
                        HTTPStatus.NOT_FOUND,
                        {"error": "this record has no deletion receipt"},
                    )
                    return
                self._download(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    filename=f"aetnamem-deletion-{record_id}.json",
                    content_type="application/json; charset=utf-8",
                )
                return
            output_format = (params.get("format") or ["json"])[0]
            if output_format == "text":
                self._download(
                    format_mirror_record_report(report),
                    filename=f"aetnamem-investigation-{record_id}.txt",
                    content_type="text/plain; charset=utf-8",
                )
                return
            if output_format != "json":
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "format must be json or text"},
                )
                return
            self._download(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                filename=f"aetnamem-investigation-{record_id}.json",
                content_type="application/json; charset=utf-8",
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._same_origin() or not secrets.compare_digest(
            self.headers.get("X-CSRF-Token", ""), self.server.csrf_token
        ):
            self._json(HTTPStatus.FORBIDDEN, {"error": "CSRF check failed"})
            return
        try:
            body = self._body()
            path = urlparse(self.path).path
            if path == "/api/mode":
                mode = ControlMode(str(body["mode"]))
                if mode is not ControlMode.ACTIVE:
                    raise ValueError(
                        "the dashboard supports only Activate AetnaMem or Restore OpenClaw"
                    )
                expected_host = self.server.manager.state().host
                if not secrets.compare_digest(
                    str(body.get("confirm_host") or ""), expected_host
                ):
                    raise ValueError(
                        f"type the host name `{expected_host}` to confirm"
                    )
                if mode is ControlMode.ACTIVE:
                    current = self.server.manager.state()
                    if current.host == "openclaw":
                        from aetnamem.control.openclaw_native import (
                            activate_takeover,
                            restore_takeover,
                        )

                        takeover = activate_takeover(
                            current, self.server.manager.state_path
                        )
                        try:
                            state = self.server.manager.transition(
                                mode, actor="dashboard-reviewer"
                            )
                        except Exception:
                            restore_takeover(current)
                            raise
                    else:
                        state = self.server.manager.transition(
                            mode, actor="dashboard-reviewer"
                        )
                        takeover = {
                            "activated": True,
                            "host": current.host,
                            "native_memory_replaced": False,
                        }
                    value = state.public_status()
                    value["takeover"] = takeover
                    self._json(HTTPStatus.OK, value)
                    return
            if path == "/api/mirror/sync":
                from aetnamem.control.openclaw_native import sync_mirror

                self._json(
                    HTTPStatus.OK,
                    sync_mirror(self.server.manager.state()),
                )
                return
            if path == "/api/mirror/review":
                from aetnamem.control.openclaw_native import review_mirror_record

                record_id = str(body.get("record_id") or "").strip()
                decision = str(body.get("decision") or "").strip()
                if not secrets.compare_digest(
                    str(body.get("confirm_record_id") or ""), record_id
                ):
                    raise ValueError("record confirmation does not match")
                self._json(
                    HTTPStatus.OK,
                    review_mirror_record(
                        self.server.manager.state(),
                        record_id,
                        decision,
                        actor="dashboard-reviewer",
                    ),
                )
                return
            if path == "/api/restore":
                from aetnamem.control.openclaw_native import restore_takeover

                state = self.server.manager.state()
                takeover = restore_takeover(state)
                if state.mode is not ControlMode.OFF:
                    state = self.server.manager.transition(
                        ControlMode.OFF, actor="dashboard-restore"
                    )
                self._json(
                    HTTPStatus.OK,
                    {
                        "restored": bool(takeover.get("valid")),
                        "takeover": takeover,
                        "host": {"host": state.host, "verified": bool(takeover.get("valid"))},
                        "gateway": takeover.get("gateway"),
                    },
                )
                return
            if path == "/api/restore-drill":
                from aetnamem.control.openclaw_native import restore_drill

                self._json(
                    HTTPStatus.OK,
                    restore_drill(self.server.manager.state()),
                )
                return
            if path == "/api/verify":
                from aetnamem.control.verify import run_verification

                self._json(
                    HTTPStatus.OK,
                    run_verification(
                        self.server.manager.state(),
                        probe=bool(body.get("probe", False)),
                    ),
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (KeyError, TypeError, ValueError) as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def _same_origin(self) -> bool:
        host = self.headers.get("Host", "")
        allowed = {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }
        if host not in allowed:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{item}" for item in allowed}

    def _valid_host(self) -> bool:
        return self.headers.get("Host", "") in {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }

    def _body(self) -> dict[str, Any]:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if size < 0 or size > 1_000_000:
            raise ValueError("request body is too large")
        value = json.loads(self.rfile.read(size) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _json(self, status: HTTPStatus, value: Any) -> None:
        body = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _download(self, value: str, *, filename: str, content_type: str) -> None:
        body = value.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")


def dashboard_html() -> str:
    try:
        from aetnamem.control.ui import APP_HTML

        return APP_HTML
    except ImportError:
        return _FALLBACK_HTML


_FALLBACK_HTML = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>AetnaMem memory control plane</title>
<style>
body{font:16px system-ui;max-width:760px;margin:4rem auto;padding:0 1rem;color:#1a2b2f}
pre{background:#f1f4f3;padding:1rem;overflow:auto}button{padding:.6rem 1rem}
</style>
<h1>AetnaMem memory control plane</h1>
<p id="mode" role="status">Loading verified local state…</p>
<pre id="status"></pre>
<script>
let csrf="";
async function load(){
 const s=await fetch("/api/session").then(r=>r.json());csrf=s.csrf_token;
 const v=await fetch("/api/status").then(r=>r.json());
 document.querySelector("#mode").textContent=`Mode: ${v.mode} — context changes: ${v.changes_model_context}`;
 document.querySelector("#status").textContent=JSON.stringify(v,null,2);
} load();
</script></html>"""
