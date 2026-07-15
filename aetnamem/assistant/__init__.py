"""Local assistant loop for the macOS sidecar UI."""

from aetnamem.assistant.agent import AssistantLoop
from aetnamem.assistant.providers import (
    AssistantProvider,
    DEFAULT_LOCAL_MODEL,
    EchoProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
)

__all__ = [
    "AssistantLoop",
    "AssistantProvider",
    "DEFAULT_LOCAL_MODEL",
    "EchoProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "ProviderConfig",
]
