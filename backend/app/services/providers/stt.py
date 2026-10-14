"""Speech-to-text providers: local faster-whisper (optional dependency) or an OpenAI-compatible API."""
import httpx

from app.core.config import get_settings
from app.services.providers.base import ProviderError, ProviderUnavailable, TranscriptSegment
from app.services.providers.transport import post_with_retries


class WhisperLocalSTT:
    name = "whisper-local"

    def __init__(self, model_size: str):
        try:
            try:
                import av
                # In PyAV 14+, metadata_errors was removed from av.open.
                # faster-whisper passes metadata_errors="ignore".
                _orig_open = av.open

                def _patched_open(*args, **kwargs):
                    kwargs.pop("metadata_errors", None)
                    return _orig_open(*args, **kwargs)

                av.open = _patched_open
            except ImportError:
                pass
            from faster_whisper import WhisperModel  # optional dependency
        except ImportError as e:
            raise ProviderUnavailable(
                "faster-whisper is not installed. Run: pip install -r requirements-optional.txt "
                "(or upload a transcript .vtt/.srt instead)."
            ) from e
        try:
            self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        except Exception as e:
            raise ProviderError(f"Could not load local whisper model '{model_size}': {e}") from e

    def transcribe(self, wav_path: str) -> list[TranscriptSegment]:
        segments, _ = self.model.transcribe(wav_path, vad_filter=True)
        return [TranscriptSegment(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]


class OpenAIWhisperSTT:
    def __init__(self, base_url: str, api_key: str, model: str, client: httpx.Client | None = None):
        if model != "whisper-1":
            raise ProviderUnavailable(
                "Timestamped segments in the OpenAI adapter require STT_MODEL=whisper-1 "
                "(the other transcription models do not support verbose segment timestamps)."
            )
        self.name = f"openai-compatible:{model}"
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.client = client or httpx.Client(timeout=600)

    def transcribe(self, wav_path: str) -> list[TranscriptSegment]:
        try:
            def send():
                with open(wav_path, "rb") as f:
                    return self.client.post(
                        f"{self.base_url}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        data={"model": self.model, "response_format": "verbose_json",
                              "timestamp_granularities[]": "segment"},
                        files={"file": ("audio.wav", f, "audio/wav")},
                    )
            r = post_with_retries(send)
        except httpx.HTTPError as e:
            raise ProviderError(f"Speech-to-text service unreachable: {type(e).__name__}") from e
        if r.status_code != 200:
            raise ProviderError(f"Speech-to-text service returned HTTP {r.status_code}.")
        segs = r.json().get("segments")
        if not segs:
            raise ProviderError("The speech-to-text service returned no timestamped segments.")
        return [TranscriptSegment(float(s["start"]), float(s["end"]), s["text"].strip()) for s in segs if s["text"].strip()]


def get_stt():
    s = get_settings()
    if s.stt_provider in ("none", ""):
        raise ProviderUnavailable(
            "Speech-to-text is not configured. Set STT_PROVIDER (whisper-local or openai), "
            "or upload a transcript (.vtt/.srt) for this lecture."
        )
    if s.stt_provider == "whisper-local":
        return WhisperLocalSTT(s.stt_model)
    if s.stt_provider in ("openai", "openai-compatible"):
        if not s.stt_api_key:
            raise ProviderUnavailable("STT_API_KEY is not set.")
        model = s.stt_model.strip() or "whisper-1"
        if model == "base":
            model = "whisper-1"
        return OpenAIWhisperSTT(s.stt_base_url or "https://api.openai.com/v1", s.stt_api_key, model)
    raise ProviderUnavailable(f"Unknown STT_PROVIDER '{s.stt_provider}'.")
