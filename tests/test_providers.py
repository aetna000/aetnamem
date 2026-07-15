from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from aetnamem.assistant.providers import (
    DEFAULT_LOCAL_MODEL,
    OllamaProvider,
    ProviderConfig,
    config_from_env,
    provider_from_config,
)


def test_local_provider_from_config_does_not_require_api_key() -> None:
    provider = provider_from_config(ProviderConfig(kind="local", model=DEFAULT_LOCAL_MODEL))

    assert isinstance(provider, OllamaProvider)


def test_local_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("AETNAMEM_PROVIDER", "ollama")
    monkeypatch.setenv("AETNAMEM_LOCAL_MODEL", "qwen3:1.7b")
    monkeypatch.setenv("AETNAMEM_OLLAMA_URL", "http://127.0.0.1:11434")

    config = config_from_env()

    assert config.kind == "local"
    assert config.model == "qwen3:1.7b"
    assert config.base_url == "http://127.0.0.1:11434"
    assert config.api_key is None


def test_ollama_provider_uses_chat_endpoint() -> None:
    seen: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: ANN001
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(length))
            body = json.dumps({"message": {"content": "local response"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        provider = OllamaProvider(
            ProviderConfig(
                kind="local",
                model="qwen3:1.7b",
                base_url=f"http://127.0.0.1:{server.server_address[1]}",
            )
        )
        result = provider.complete([{"role": "user", "content": "hello"}], [])
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result == "local response"
    assert seen["path"] == "/api/chat"
    assert seen["body"]["model"] == "qwen3:1.7b"
    assert seen["body"]["stream"] is False
