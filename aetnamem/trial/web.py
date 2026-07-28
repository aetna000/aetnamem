from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

from aetnamem.trial import TrialManager, TrialMode


class TrialDashboardServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        manager: TrialManager,
        *,
        html: str,
    ) -> None:
        host, _ = address
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Safe Switch dashboard is loopback-only")
        super().__init__(address, TrialDashboardHandler)
        self.manager = manager
        self.html = html
        self.login_code = secrets.token_urlsafe(24)
        self.session_token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)


class TrialDashboardHandler(BaseHTTPRequestHandler):
    server: TrialDashboardServer

    def do_GET(self) -> None:  # noqa: N802
        if not self._valid_host():
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid Host header"})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/auth":
            code = (parse_qs(parsed.query).get("code") or [""])[0]
            if not secrets.compare_digest(code, self.server.login_code):
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid login code"})
                return
            self.server.login_code = secrets.token_urlsafe(24)
            self.send_response(HTTPStatus.SEE_OTHER)
            self._security_headers()
            self.send_header(
                "Set-Cookie",
                "aetnamem_trial="
                + self.server.session_token
                + "; HttpOnly; SameSite=Strict; Path=/",
            )
            self.send_header("Location", "/")
            self.end_headers()
            return
        if not self._authenticated():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication required"})
            return
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
        if parsed.path == "/api/candidates":
            self._json(
                HTTPStatus.OK,
                {"candidates": self.server.manager.candidates(include_reviewed=True)},
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authenticated():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication required"})
            return
        if not self._same_origin() or not secrets.compare_digest(
            self.headers.get("X-CSRF-Token", ""), self.server.csrf_token
        ):
            self._json(HTTPStatus.FORBIDDEN, {"error": "CSRF check failed"})
            return
        try:
            body = self._body()
            path = urlparse(self.path).path
            if path == "/api/review":
                ids = body.get("candidate_ids")
                if not isinstance(ids, list) or not all(
                    isinstance(item, str) for item in ids
                ):
                    raise ValueError("candidate_ids must be a list of strings")
                result = self.server.manager.review(
                    ids, approve=bool(body.get("approve"))
                )
                self._json(HTTPStatus.OK, {"candidates": result})
                return
            if path == "/api/mode":
                mode = TrialMode(str(body["mode"]))
                if mode in {TrialMode.CANARY, TrialMode.ACTIVE}:
                    expected_host = self.server.manager.state().host
                    if not secrets.compare_digest(
                        str(body.get("confirm_host") or ""), expected_host
                    ):
                        raise ValueError(
                            f"type the host name `{expected_host}` to confirm"
                        )
                if mode is TrialMode.OFF:
                    state = self.server.manager.transition(
                        mode, actor="dashboard-emergency-off"
                    )
                elif mode is TrialMode.CANARY:
                    state = self.server.manager.transition(
                        mode,
                        actor="dashboard-reviewer",
                        canary_turns=int(body.get("turns", 0)),
                    )
                else:
                    state = self.server.manager.transition(
                        mode, actor="dashboard-reviewer"
                    )
                self._json(HTTPStatus.OK, state.public_status())
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (KeyError, TypeError, ValueError) as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def _authenticated(self) -> bool:
        cookies: dict[str, str] = {}
        for part in self.headers.get("Cookie", "").split(";"):
            key, separator, value = part.strip().partition("=")
            if separator:
                cookies[key] = value
        return secrets.compare_digest(
            cookies.get("aetnamem_trial", ""), self.server.session_token
        )

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
        from aetnamem.trial.ui import APP_HTML

        return APP_HTML
    except ImportError:
        return _FALLBACK_HTML


_FALLBACK_HTML = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>AetnaMem Safe Switch</title>
<style>
body{font:16px system-ui;max-width:760px;margin:4rem auto;padding:0 1rem;color:#1a2b2f}
pre{background:#f1f4f3;padding:1rem;overflow:auto}button{padding:.6rem 1rem}
</style>
<h1>AetnaMem Safe Switch</h1>
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
