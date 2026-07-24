"""Optional semantic retrieval for canonical, auditable investigation search."""

from aetnamem.semantic.index import (
    SemanticIndex,
    SemanticIndexIntegrityError,
    default_index_path,
)
from aetnamem.semantic.providers import (
    Embedder,
    HashingEmbedder,
    OllamaEmbedder,
    OpenAICompatibleEmbedder,
    SentenceTransformersEmbedder,
    create_embedder,
)

__all__ = [
    "Embedder",
    "HashingEmbedder",
    "OllamaEmbedder",
    "OpenAICompatibleEmbedder",
    "SemanticIndex",
    "SemanticIndexIntegrityError",
    "SentenceTransformersEmbedder",
    "create_embedder",
    "default_index_path",
]
