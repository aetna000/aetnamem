"""Provider-neutral embedding adapters with no mandatory model dependency."""

from __future__ import annotations

from hashlib import sha256
import json
import math
import os
import re
from typing import Any, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class Embedder(Protocol):
    @property
    def identity(self) -> dict[str, Any]: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """Ollama's current batch `/api/embed` contract."""

    def __init__(
        self,
        model: str,
        *,
        endpoint: str = "http://127.0.0.1:11434",
        model_version: str = "unverified",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.endpoint = _safe_endpoint(endpoint)
        self.timeout = timeout
        self.model_digest = _ollama_model_digest(
            self.endpoint, self.model, timeout=self.timeout
        )
        if model_version.startswith("sha256:") and model_version != self.model_digest:
            raise ValueError(
                "Ollama model digest mismatch: "
                f"expected {model_version!r}, current {self.model_digest!r}"
            )
        self.model_version = (
            self.model_digest if model_version == "unverified" else model_version
        )

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "provider": "ollama",
            "model": self.model,
            "version": self.model_version,
            "model_digest": self.model_digest,
            "endpoint": self.endpoint,
            "normalization": "l2",
        }

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(list(texts))

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def verify_identity(self) -> None:
        current = _ollama_model_digest(
            self.endpoint, self.model, timeout=self.timeout
        )
        if current != self.model_digest:
            raise ValueError(
                "Ollama model digest changed after embedder initialization: "
                f"expected {self.model_digest!r}, current {current!r}"
            )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = _post_json(
            f"{self.endpoint}/api/embed",
            {"model": self.model, "input": texts},
            timeout=self.timeout,
        )
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise ValueError("Ollama embedding response has an unexpected shape")
        return [_normalize(_float_vector(value)) for value in embeddings]


class OpenAICompatibleEmbedder:
    """Embedding adapter for OpenAI-compatible `/v1/embeddings` endpoints."""

    def __init__(
        self,
        model: str,
        *,
        endpoint: str,
        api_key: str | None = None,
        model_version: str = "unverified",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.endpoint = _safe_endpoint(endpoint)
        self.api_key = api_key
        self.model_version = model_version
        self.timeout = timeout

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "provider": "openai-compatible",
            "model": self.model,
            "version": self.model_version,
            "endpoint": self.endpoint,
            "normalization": "l2",
        }

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(list(texts))

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = _post_json(
            f"{self.endpoint}/v1/embeddings",
            {"model": self.model, "input": texts, "encoding_format": "float"},
            headers=headers,
            timeout=self.timeout,
        )
        data = response.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError("embedding response has an unexpected shape")
        ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
        return [_normalize(_float_vector(item.get("embedding"))) for item in ordered]


class SentenceTransformersEmbedder:
    """Optional local adapter, loaded only when the semantic extra is installed."""

    def __init__(self, model: str, *, model_version: str = "unverified") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                'sentence-transformers is optional; install `pip install "aetnamem[semantic]"`'
            ) from exc
        self.model_name = model
        self.model_version = model_version
        self._model = SentenceTransformer(model)

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "provider": "sentence-transformers",
            "model": self.model_name,
            "version": self.model_version,
            "normalization": "l2",
        }

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        method = getattr(self._model, "encode_document", self._model.encode)
        values = method(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [_normalize(_float_vector(value)) for value in values]

    def embed_query(self, text: str) -> list[float]:
        method = getattr(self._model, "encode_query", self._model.encode)
        values = method(
            [text],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return _normalize(_float_vector(values[0]))


class HashingEmbedder:
    """Dependency-free deterministic diagnostic embedder.

    It is useful for tests and plumbing checks, not for semantic-quality claims.
    """

    def __init__(self, *, dimensions: int = 128) -> None:
        if dimensions < 8:
            raise ValueError("hashing embedder dimensions must be at least 8")
        self.dimensions = dimensions

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "provider": "hashing-diagnostic",
            "model": f"token-hash-{self.dimensions}",
            "version": "1",
            "normalization": "l2",
        }

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[\w'-]+", text.casefold())
        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = -1.0 if digest[4] & 1 else 1.0
            vector[index] += sign
        return _normalize(vector)


def create_embedder(
    provider: str,
    model: str | None,
    *,
    endpoint: str | None = None,
    api_key_env: str | None = None,
    model_version: str = "unverified",
) -> Embedder:
    if provider == "hashing":
        dimensions = int(model) if model and model.isdigit() else 128
        return HashingEmbedder(dimensions=dimensions)
    if not model:
        raise ValueError(f"--model is required for the {provider} embedder")
    if provider == "ollama":
        return OllamaEmbedder(
            model,
            endpoint=endpoint or "http://127.0.0.1:11434",
            model_version=model_version,
        )
    if provider == "openai-compatible":
        if not endpoint:
            raise ValueError("--endpoint is required for an OpenAI-compatible embedder")
        api_key = os.environ.get(api_key_env, "") if api_key_env else None
        if api_key_env and not api_key:
            raise ValueError(f"embedding API key environment variable is not set: {api_key_env}")
        return OpenAICompatibleEmbedder(
            model,
            endpoint=endpoint,
            api_key=api_key,
            model_version=model_version,
        )
    if provider == "sentence-transformers":
        return SentenceTransformersEmbedder(model, model_version=model_version)
    raise ValueError(f"unknown embedding provider: {provider}")


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"embedding endpoint returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"embedding endpoint is unavailable: {exc.reason}") from exc
    if not isinstance(value, dict):
        raise ValueError("embedding endpoint returned a non-object response")
    return value


def _get_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"embedding endpoint returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"embedding endpoint is unavailable: {exc.reason}") from exc
    if not isinstance(value, dict):
        raise ValueError("embedding endpoint returned a non-object response")
    return value


def _ollama_model_digest(endpoint: str, model: str, *, timeout: float) -> str:
    response = _get_json(f"{endpoint}/api/tags", timeout=timeout)
    models = response.get("models")
    if not isinstance(models, list):
        raise ValueError("Ollama model list has an unexpected shape")
    exact: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    for value in models:
        if not isinstance(value, dict):
            continue
        names = {str(value.get("name") or ""), str(value.get("model") or "")}
        if model in names:
            exact.append(value)
        elif ":" not in model and f"{model}:latest" in names:
            aliases.append(value)
    matches = exact or aliases
    if len(matches) != 1:
        reason = "not found" if not matches else "ambiguous"
        raise ValueError(f"Ollama model {model!r} is {reason} in /api/tags")
    digest = matches[0].get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise ValueError(f"Ollama model {model!r} has no verifiable SHA-256 digest")
    return digest


def _safe_endpoint(value: str) -> str:
    endpoint = value.rstrip("/")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("embedding endpoint must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "embedding endpoint must not contain credentials, query parameters, or fragments"
        )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _float_vector(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("embedding must be a non-empty numeric vector")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError("embedding contains a non-finite value")
    return result


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return [0.0 for _ in vector]
    return [float(value / norm) for value in vector]
