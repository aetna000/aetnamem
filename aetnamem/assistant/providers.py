from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Protocol
from urllib.request import Request, urlopen


class AssistantProvider(Protocol):
    def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> str:
        """Return assistant text. Implementations may encode a tool call as JSON."""


@dataclass(frozen=True)
class ProviderConfig:
    kind: str = "echo"
    model: str = "local-echo"
    api_key: str | None = None
    base_url: str | None = None


class EchoProvider:
    """Offline provider used before the user connects an API key."""

    def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> str:
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return (
            "I am running locally with aetnamem protection. "
            f"I captured your request and can use {len(tools)} governed tools. "
            f"Last request: {user}"
        )


class OpenAICompatibleProvider:
    """Minimal Chat Completions client for OpenAI, DeepSeek, and compatible APIs."""

    def __init__(self, config: ProviderConfig, *, timeout: float = 60.0) -> None:
        if not config.api_key:
            raise ValueError("api_key is required")
        self.config = config
        self.timeout = timeout

    def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> str:
        url = (self.config.base_url or _default_base_url(self.config.kind)).rstrip("/")
        body = {
            "model": self.config.model,
            "messages": [
                *messages,
                {
                    "role": "system",
                    "content": (
                        "Available governed tools are listed below. If a tool is needed, "
                        "respond with JSON only: {\"tool\":\"name\",\"arguments\":{...}}. "
                        "Otherwise answer normally.\n"
                        + json.dumps(tools, sort_keys=True)
                    ),
                },
            ],
        }
        request = Request(
            f"{url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]


def provider_from_config(config: ProviderConfig) -> AssistantProvider:
    if config.kind == "echo":
        return EchoProvider()
    if config.kind in {"openai", "deepseek", "openai-compatible"}:
        return OpenAICompatibleProvider(config)
    raise ValueError(f"unknown provider kind: {config.kind}")


def config_from_env() -> ProviderConfig:
    provider = os.environ.get("AETNAMEM_PROVIDER", "echo").strip().lower()
    if provider == "openai":
        return ProviderConfig(
            kind="openai",
            model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
            api_key=os.environ.get("OPENAI_API_KEY"),
        )
    if provider == "deepseek":
        return ProviderConfig(
            kind="deepseek",
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
        )
    if provider == "openai-compatible":
        return ProviderConfig(
            kind="openai-compatible",
            model=os.environ.get("AETNAMEM_MODEL", "gpt-4.1-mini"),
            api_key=os.environ.get("AETNAMEM_API_KEY"),
            base_url=os.environ.get("AETNAMEM_BASE_URL"),
        )
    return ProviderConfig()


def _default_base_url(kind: str) -> str:
    if kind == "deepseek":
        return "https://api.deepseek.com"
    return "https://api.openai.com/v1"
