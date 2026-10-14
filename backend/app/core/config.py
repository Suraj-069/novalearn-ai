"""Application configuration. Everything comes from environment variables / .env.

No secrets are hardcoded. See ../../.env.example for the full list.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), ".env"), extra="ignore"
    )

    # --- Branding (easy to customise) ---
    app_name: str = "NOVA Learn AI"
    app_tagline: str = "Learn smarter. Understand deeper."

    # --- Database ---
    database_url: str = "postgresql+psycopg://nova:nova@localhost:5432/novalearn"

    # --- Auth ---
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- File storage & upload limits ---
    storage_dir: str = str(REPO_ROOT / "storage")
    max_document_mb: int = 100       # PDF / PPTX / transcript / image
    max_video_mb: int = 1024         # lecture videos

    # --- Vector retrieval (used from Stage 3) ---
    embedding_dim: int = 768

    # --- AI providers (used from Stage 3; declared now so config is stable) ---
    llm_provider: str = "none"       # none | openai | openai-compatible | ollama | anthropic | xai | google
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""           # optional override (e.g. http://localhost:11434/v1 for Ollama)
    vision_enabled: bool = False     # send figures to the LLM for description (needs a vision-capable model)
    embedding_provider: str = "local-hash"   # local-hash | openai | openai-compatible | ollama | google
    embedding_model: str = ""
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    stt_provider: str = "none"       # none | whisper-local | openai
    stt_model: str = "base"          # whisper-local model size, or OpenAI transcription model
    stt_api_key: str = ""
    stt_base_url: str = ""
    ocr_language: str = "eng"        # Tesseract language code(s), e.g. "eng+hin"

    # --- Retrieval / tutoring ---
    retrieval_top_k: int = 6
    # Minimum share of the question's content words that must appear in the best passage
    # (lexical evidence) for an answer to count as supported when embeddings are not semantic.
    min_lexical_support: float = 0.5
    # Minimum cosine similarity for semantic embeddings (hosted/Ollama models).
    min_semantic_score: float = 0.45

    @field_validator("jwt_secret")
    @classmethod
    def _secret_not_placeholder(cls, v: str) -> str:
        if v in {"change-me", "changeme", "secret"}:
            raise ValueError("JWT_SECRET must not be a placeholder value")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def storage_path(self) -> Path:
        """STORAGE_DIR, with relative paths resolved against the repo root (not the cwd)."""
        p = Path(self.storage_dir)
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def upload_root(self) -> Path:
        return self.storage_path / "uploads"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if len(s.jwt_secret) < 32:
        raise RuntimeError(
            "JWT_SECRET is missing or shorter than 32 characters. "
            "Copy .env.example to .env and set JWT_SECRET "
            "(generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\")."
        )
    return s
