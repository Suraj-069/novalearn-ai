"""LLM providers (OpenAI-compatible and Anthropic) over plain HTTPS via httpx. Keys stay server-side."""
import base64

import httpx

from app.core.config import get_settings
from app.services.providers.base import ProviderError, ProviderUnavailable
from app.services.providers.transport import post_with_retries


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, api_key: str, model: str, client: httpx.Client | None = None,
                 *, openai_api: bool = False):
        self.name = f"openai-compatible:{model}"
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.client = client or httpx.Client(timeout=120)
        self.openai_api = openai_api

    def _post(self, messages: list[dict], *, json_mode: bool, max_tokens: int) -> str:
        body: dict = {"model": self.model, "messages": messages}
        if self.openai_api:
            # OpenAI deprecated max_tokens; newer reasoning models reject it.
            body["max_completion_tokens"] = max_tokens
        else:
            # Keep the established OpenAI-compatible/Ollama request shape.
            body.update(temperature=0.2, max_tokens=max_tokens)
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = post_with_retries(lambda: self.client.post(
                f"{self.base_url}/chat/completions", json=body,
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}))
        except httpx.HTTPError as e:
            raise ProviderError(f"Language model unreachable: {type(e).__name__}") from e
        if r.status_code != 200:
            raise ProviderError(f"Language model returned HTTP {r.status_code}.")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as e:
            raise ProviderError("Language model returned an unexpected response.") from e

    def complete(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 1200) -> str:
        return self._post([{"role": "system", "content": system}, {"role": "user", "content": user}],
                          json_mode=json_mode, max_tokens=max_tokens)

    def describe_image(self, image_png: bytes, prompt: str) -> str:
        b64 = base64.b64encode(image_png).decode()
        msg = [{"role": "user", "content": [{"type": "text", "text": prompt},
                                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]
        return self._post(msg, json_mode=False, max_tokens=500)


class AnthropicLLM:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.anthropic.com", client: httpx.Client | None = None):
        self.name = f"anthropic:{model}"
        self.api_key, self.model, self.base_url = api_key, model, base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=120)

    def _post(self, system: str, content, max_tokens: int) -> str:
        body = {"model": self.model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": content}]}
        try:
            r = post_with_retries(lambda: self.client.post(
                f"{self.base_url}/v1/messages", json=body,
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}))
        except httpx.HTTPError as e:
            raise ProviderError(f"Language model unreachable: {type(e).__name__}") from e
        if r.status_code != 200:
            raise ProviderError(f"Language model returned HTTP {r.status_code}.")
        try:
            return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        except (KeyError, ValueError) as e:
            raise ProviderError("Language model returned an unexpected response.") from e

    def complete(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 1200) -> str:
        if json_mode:
            system += "\nRespond with a single valid JSON object and nothing else."
        return self._post(system, user, max_tokens)

    def describe_image(self, image_png: bytes, prompt: str) -> str:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(image_png).decode()}},
                   {"type": "text", "text": prompt}]
        return self._post("You describe educational figures accurately and concisely.", content, 500)


class GoogleGeminiLLM:
    """Gemini generateContent REST adapter (text, JSON mode, and inline image input)."""
    def __init__(self, api_key: str, model: str, base_url: str = "https://generativelanguage.googleapis.com/v1beta",
                 client: httpx.Client | None = None):
        self.name = f"google:{model}"
        self.api_key, self.model = api_key, model.removeprefix("models/")
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=120)

    def _post(self, system: str, parts: list[dict], *, json_mode: bool, max_tokens: int) -> str:
        body: dict = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        try:
            response = post_with_retries(lambda: self.client.post(
                f"{self.base_url}/models/{self.model}:generateContent", json=body,
                headers={"x-goog-api-key": self.api_key},
            ))
        except httpx.HTTPError as exc:
            raise ProviderError(f"Google language model unreachable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            detail = None
            try:
                payload = response.json()
                error = payload.get("error") if isinstance(payload, dict) else None
                detail = error.get("message") if isinstance(error, dict) else None
            except (ValueError, TypeError):
                pass
            if isinstance(detail, str):
                if self.api_key:
                    detail = detail.replace(self.api_key, "[redacted]")
                detail = " ".join(detail.split())[:240]
            suffix = f": {detail}" if detail else ""
            raise ProviderError(f"Google language model returned HTTP {response.status_code}{suffix}.")
        try:
            candidates = response.json()["candidates"]
            text = "".join(part.get("text", "") for part in candidates[0]["content"]["parts"]
                           if isinstance(part.get("text"), str) and not part.get("thought"))
            if not text.strip():
                raise ProviderError("Google language model returned no text content.")
            return text
        except ProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("Google language model returned an unexpected or blocked response.") from exc

    def complete(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 1200) -> str:
        return self._post(system, [{"text": user}], json_mode=json_mode, max_tokens=max_tokens)

    def describe_image(self, image_png: bytes, prompt: str) -> str:
        encoded = base64.b64encode(image_png).decode("ascii")
        return self._post("You describe educational figures accurately and concisely.",
                          [{"inlineData": {"mimeType": "image/png", "data": encoded}}, {"text": prompt}],
                          json_mode=False, max_tokens=500)


def get_llm(model: str | None = None) -> OpenAICompatibleLLM | AnthropicLLM | GoogleGeminiLLM | None:
    """Return the configured LLM, or None when no language model is configured (extractive mode)."""
    s = get_settings()
    p = s.llm_provider
    if p in ("none", ""):
        return None
    selected_model = model or s.llm_model
    if not selected_model:
        raise ProviderUnavailable("LLM_MODEL is not set.")
    if p == "anthropic":
        if not s.llm_api_key:
            raise ProviderUnavailable("LLM_API_KEY is not set.")
        return AnthropicLLM(s.llm_api_key, selected_model, s.llm_base_url or "https://api.anthropic.com")
    if p in ("google", "gemini"):
        if not s.llm_api_key:
            raise ProviderUnavailable("LLM_API_KEY is not set for Google Gemini.")
        return GoogleGeminiLLM(s.llm_api_key, selected_model,
                               s.llm_base_url or "https://generativelanguage.googleapis.com/v1beta")
    if p in ("openai", "openai-compatible", "ollama", "xai"):
        default_base = ("http://localhost:11434/v1" if p == "ollama" else
                        "https://api.x.ai/v1" if p == "xai" else "https://api.openai.com/v1")
        base = s.llm_base_url or default_base
        if p in ("openai", "xai") and not s.llm_api_key:
            raise ProviderUnavailable("LLM_API_KEY is not set.")
        return OpenAICompatibleLLM(base, s.llm_api_key, selected_model, openai_api=(p == "openai"))
    raise ProviderUnavailable(f"Unknown LLM_PROVIDER '{p}'.")
