"""Embedding providers.

- LocalHashEmbedding: REAL, offline, deterministic. Signed feature hashing of stemmed unigrams + bigrams.
  It is lexical: it matches shared words, not meaning (no synonyms). Hybrid retrieval and
  conservative thresholds compensate. Use a hosted/Ollama model for real semantic search.
- OpenAICompatibleEmbedding: any /v1/embeddings server (OpenAI, Ollama, vLLM, LM Studio...).
"""
import hashlib
import math
from functools import lru_cache

import httpx

from app.core.config import get_settings
from app.services.providers.base import ProviderError, ProviderUnavailable
from app.services.providers.transport import post_with_retries
from app.services.providers.text import tokens


class LocalHashEmbedding:
    name = "local-hash"
    semantic = False

    def __init__(self, dim: int):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        toks = tokens(text)
        feats: dict[str, float] = {}
        for t in toks:
            feats[t] = feats.get(t, 0.0) + 1.0
        for a, b in zip(toks, toks[1:]):
            k = f"{a}_{b}"
            feats[k] = feats.get(k, 0.0) + 1.0
        v = [0.0] * self.dim
        for f, c in feats.items():
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            sign = 1.0 if (h >> 63) & 1 else -1.0
            v[h % self.dim] += sign * (1.0 + math.log(c))
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v] if n else v

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OpenAICompatibleEmbedding:
    semantic = True

    def __init__(self, base_url: str, api_key: str, model: str, dim: int, client: httpx.Client | None = None):
        self.name = f"openai-compatible:{model}"
        self.base_url, self.api_key, self.model, self.dim = base_url.rstrip("/"), api_key, model, dim
        self.client = client or httpx.Client(timeout=60)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = texts[i : i + 64]
            body: dict = {"model": self.model, "input": batch}
            if "text-embedding-3" in self.model:
                body["dimensions"] = self.dim  # OpenAI v3 models can emit the dimension we store
            try:
                r = post_with_retries(lambda: self.client.post(
                    f"{self.base_url}/embeddings", json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}))
            except httpx.HTTPError as e:
                raise ProviderError(f"Embedding service unreachable: {type(e).__name__}") from e
            if r.status_code != 200:
                raise ProviderError(f"Embedding service returned HTTP {r.status_code}.")
            try:
                data = r.json()["data"]
                if not isinstance(data, list) or len(data) != len(batch):
                    raise ProviderError("Embedding service returned an unexpected number of vectors.")
                data = sorted(data, key=lambda d: d["index"])
                if [d["index"] for d in data] != list(range(len(batch))):
                    raise ProviderError("Embedding service returned unexpected vector indexes.")
                for d in data:
                    vec = d["embedding"]
                    if len(vec) != self.dim:
                        raise ProviderError(
                            f"Embedding model returned {len(vec)} dimensions but EMBEDDING_DIM is {self.dim}. "
                            "For this database schema, keep EMBEDDING_DIM=768 or create a migration and re-index."
                        )
                    out.append(vec)
            except ProviderError:
                raise
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise ProviderError("Embedding service returned an unexpected response.") from e
        return out


class GoogleGeminiEmbedding:
    """Gemini REST batchEmbedContents adapter with an explicit output dimension."""
    semantic = True

    def __init__(self, api_key: str, model: str, dim: int, client: httpx.Client | None = None):
        self.name = f"google:{model}"
        self.api_key, self.model, self.dim = api_key, model.removeprefix("models/"), dim
        self.client = client or httpx.Client(timeout=60)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 100):
            batch = texts[i:i + 100]
            body = {"requests": [{"model": f"models/{self.model}",
                                  "content": {"parts": [{"text": text}]},
                                  # These are direct EmbedContentRequest fields in Google's REST API.
                                  "outputDimensionality": self.dim,
                                  "taskType": "SEMANTIC_SIMILARITY"}
                                 for text in batch]}
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"
            try:
                response = post_with_retries(lambda: self.client.post(
                    url, json=body, headers={"x-goog-api-key": self.api_key}))
            except httpx.HTTPError as exc:
                raise ProviderError(f"Google embedding service unreachable: {type(exc).__name__}") from exc
            if response.status_code != 200:
                raise ProviderError(f"Google embedding service returned HTTP {response.status_code}.")
            try:
                vectors = response.json()["embeddings"]
                if not isinstance(vectors, list) or len(vectors) != len(batch):
                    raise ProviderError("Google embedding service returned an unexpected number of vectors.")
                for item in vectors:
                    vector = item["values"]
                    if not isinstance(vector, list) or len(vector) != self.dim:
                        actual = len(vector) if isinstance(vector, list) else 0
                        raise ProviderError(f"Google embedding model returned {actual} dimensions but EMBEDDING_DIM is {self.dim}.")
                    out.append(vector)
            except ProviderError:
                raise
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ProviderError("Google embedding service returned an unexpected response.") from exc
        return out


def get_embedding_provider() -> LocalHashEmbedding | OpenAICompatibleEmbedding | GoogleGeminiEmbedding:
    s = get_settings()
    if s.embedding_provider in ("none", "local-hash", ""):
        return LocalHashEmbedding(s.embedding_dim)
    if s.embedding_provider in ("openai", "openai-compatible", "ollama"):
        base = s.embedding_base_url or ("http://localhost:11434/v1" if s.embedding_provider == "ollama" else "https://api.openai.com/v1")
        if not s.embedding_model:
            raise ProviderUnavailable("EMBEDDING_MODEL is not set.")
        if s.embedding_provider == "openai" and not s.embedding_api_key:
            raise ProviderUnavailable("EMBEDDING_API_KEY is not set.")
        return OpenAICompatibleEmbedding(base, s.embedding_api_key, s.embedding_model, s.embedding_dim)
    if s.embedding_provider == "google":
        if not s.embedding_api_key:
            raise ProviderUnavailable("EMBEDDING_API_KEY is not set for Google embeddings.")
        if not s.embedding_model:
            raise ProviderUnavailable("EMBEDDING_MODEL is not set.")
        return GoogleGeminiEmbedding(s.embedding_api_key, s.embedding_model, s.embedding_dim)
    raise ProviderUnavailable(f"Unknown EMBEDDING_PROVIDER '{s.embedding_provider}'.")


@lru_cache(maxsize=1)
def validate_embedding_dimension() -> int:
    """Probe the configured model once per process and verify its output fits the current schema."""
    s = get_settings()
    if s.embedding_dim != 768:
        raise RuntimeError(
            f"EMBEDDING_DIM is {s.embedding_dim}, but the current Alembic schema stores vector(768). "
            "Keep EMBEDDING_DIM=768 or add a schema migration and re-index all documents."
        )

    provider = None
    try:
        provider = get_embedding_provider()
        vectors = provider.embed(["NOVA Learn AI startup embedding dimension check."])
    except Exception as e:
        model = s.embedding_model or getattr(provider, "name", s.embedding_provider)
        raise RuntimeError(
            f"Embedding startup check failed for {s.embedding_provider} model {model} "
            f"with EMBEDDING_DIM={s.embedding_dim}: {e}"
        ) from e

    if len(vectors) != 1 or len(vectors[0]) != s.embedding_dim:
        actual = len(vectors[0]) if vectors else 0
        raise RuntimeError(
            f"Embedding startup check returned {actual} dimensions for EMBEDDING_DIM={s.embedding_dim}; "
            "the app cannot store or retrieve vectors until the model and schema match."
        )
    return len(vectors[0])
