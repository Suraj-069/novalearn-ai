"""Provider interfaces. Every AI capability is behind one of these so models are swappable by config."""
from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """A provider call failed. The message is safe to show to the user (never contains keys)."""


class ProviderUnavailable(ProviderError):
    """The provider is not configured or a required dependency is missing."""


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 1200) -> str: ...
    def describe_image(self, image_png: bytes, prompt: str) -> str: ...


class EmbeddingProvider(Protocol):
    name: str
    semantic: bool  # False for lexical-only embeddings: retrieval thresholds adapt to this

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class STTProvider(Protocol):
    name: str

    def transcribe(self, wav_path: str) -> list[TranscriptSegment]: ...
