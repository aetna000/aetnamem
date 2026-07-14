"""Local assistant loop for the macOS sidecar UI."""

from aetnamem.assistant.agent import AssistantLoop
from aetnamem.assistant.providers import (
    AssistantProvider,
    EchoProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
)

__all__ = [
    "AssistantLoop",
    "AssistantProvider",
    "EchoProvider",
    "OpenAICompatibleProvider",
    "ProviderConfig",
]
