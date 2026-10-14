"""Provider adapters, verified against mocked HTTP (no live API was called in these tests)."""
import json

import httpx
import pytest

from app.core.config import get_settings
from app.services.providers import embeddings as emb, llm as llm_mod, stt as stt_mod
from app.services.providers.base import ProviderError, ProviderUnavailable


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_local_hash_embedding_is_deterministic_normalised_and_lexical():
    e = emb.LocalHashEmbedding(768)
    a1, a2 = e.embed(["The Carnot cycle efficiency"]), e.embed(["The Carnot cycle efficiency"])
    assert a1 == a2 and abs(sum(x * x for x in a1[0]) - 1) < 1e-9 and len(a1[0]) == 768
    assert e.semantic is False
    q, rel, irr = e.embed(["carnot cycle efficiency", "Efficiency of the Carnot cycle is bounded.", "Chloroplasts perform photosynthesis."])
    dot = lambda x, y: sum(i * j for i, j in zip(x, y))
    assert dot(q, rel) > 0.3 > dot(q, irr)


def test_default_embedding_provider_is_the_offline_one(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_provider", "local-hash")
    p = emb.get_embedding_provider()
    assert p.name == "local-hash" and p.semantic is False


def test_openai_embeddings_request_shape_and_dimensions():
    seen = {}
    def handler(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [0.1] * 768} for i in range(len(seen["body"]["input"]))]})
    p = emb.OpenAICompatibleEmbedding("https://api.example.com/v1/", "sk-test", "text-embedding-3-small", 768, client_for(handler))
    out = p.embed(["a", "b"])
    assert len(out) == 2 and seen["url"] == "https://api.example.com/v1/embeddings"
    assert seen["auth"] == "Bearer sk-test" and seen["body"]["dimensions"] == 768 and p.semantic is True


def test_google_gemini_embeddings_use_batch_rest_shape_and_validate_dimension():
    seen = {}
    def handler(req):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("x-goog-api-key"), json.loads(req.content)
        return httpx.Response(200, json={"embeddings": [{"values": [0.25] * 768} for _ in seen["body"]["requests"]]})
    provider = emb.GoogleGeminiEmbedding("google-test-key", "gemini-embedding-001", 768, client_for(handler))
    result = provider.embed(["first text", "second text"])
    assert len(result) == 2 and len(result[0]) == 768 and provider.semantic
    assert seen["url"].endswith("/models/gemini-embedding-001:batchEmbedContents")
    assert seen["key"] == "google-test-key"
    assert seen["body"]["requests"][0]["outputDimensionality"] == 768
    assert seen["body"]["requests"][0]["taskType"] == "SEMANTIC_SIMILARITY"


def test_google_embedding_dimension_mismatch_fails_clearly():
    provider = emb.GoogleGeminiEmbedding("key", "gemini-embedding-001", 768,
        client_for(lambda req: httpx.Response(200, json={"embeddings": [{"values": [0.1] * 512}]})))
    with pytest.raises(ProviderError, match="512 dimensions.*EMBEDDING_DIM"):
        provider.embed(["text"])


def test_embedding_response_must_contain_one_ordered_vector_per_input():
    missing = emb.OpenAICompatibleEmbedding(
        "http://x/v1", "", "model", 2,
        client_for(lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})),
    )
    with pytest.raises(ProviderError, match="unexpected number of vectors"):
        missing.embed(["first", "second"])

    bad_index = emb.OpenAICompatibleEmbedding(
        "http://x/v1", "", "model", 2,
        client_for(lambda r: httpx.Response(200, json={"data": [{"index": 4, "embedding": [0.1, 0.2]}]})),
    )
    with pytest.raises(ProviderError, match="unexpected vector indexes"):
        bad_index.embed(["one"])


def test_embedding_dimension_mismatch_is_explained():
    p = emb.OpenAICompatibleEmbedding("http://x/v1", "", "nomic", 768, client_for(lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 384}]})))
    with pytest.raises(ProviderError, match="384 dimensions.*EMBEDDING_DIM"):
        p.embed(["a"])


def test_provider_errors_never_leak_the_api_key():
    p = emb.OpenAICompatibleEmbedding("http://x/v1", "sk-SECRET", "m", 768, client_for(lambda r: httpx.Response(401, text="bad key sk-SECRET")))
    with pytest.raises(ProviderError) as e:
        p.embed(["a"])
    assert "sk-SECRET" not in str(e.value) and "401" in str(e.value)

    def boom(req): raise httpx.ConnectError("refused for sk-SECRET")
    with pytest.raises(ProviderError) as e2:
        emb.OpenAICompatibleEmbedding("http://x/v1", "sk-SECRET", "m", 768, client_for(boom)).embed(["a"])
    assert "sk-SECRET" not in str(e2.value)


def test_openai_chat_request_and_json_mode():
    seen = {}
    def handler(req):
        seen["body"], seen["auth"] = json.loads(req.content), req.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello [1]"}}]})
    p = llm_mod.OpenAICompatibleLLM("http://x/v1", "k", "gpt-test", client_for(handler))
    assert p.complete("sys", "usr", json_mode=True) == "hello [1]"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"} and seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["auth"] == "Bearer k"
    p.describe_image(b"\x89PNG", "describe")
    assert seen["body"]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openai_chat_uses_current_token_parameter():
    seen = {}
    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})
    p = llm_mod.OpenAICompatibleLLM("https://api.openai.com/v1", "k", "gpt-6-luna", client_for(handler), openai_api=True)
    assert p.complete("system", "user", max_tokens=37) == "hello"
    assert seen["body"]["max_completion_tokens"] == 37
    assert "max_tokens" not in seen["body"] and "temperature" not in seen["body"]


def test_google_gemini_llm_generate_content_json_and_vision_request_shapes():
    seen = []
    def handler(req):
        seen.append({"url": str(req.url), "key": req.headers.get("x-goog-api-key"), "body": json.loads(req.content)})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"answer":"ok"}'}]}}]})
    provider = llm_mod.GoogleGeminiLLM("google-test-key", "gemini-2.5-flash", client=client_for(handler))
    assert provider.complete("system", "user", json_mode=True, max_tokens=88) == '{"answer":"ok"}'
    text_request = seen[0]
    assert text_request["url"].endswith("/models/gemini-2.5-flash:generateContent")
    assert text_request["key"] == "google-test-key"
    assert text_request["body"]["systemInstruction"]["parts"][0]["text"] == "system"
    assert text_request["body"]["contents"][0]["parts"][0]["text"] == "user"
    assert text_request["body"]["generationConfig"] == {"maxOutputTokens": 88, "temperature": 0.2, "responseMimeType": "application/json"}

    assert provider.describe_image(b"png-data", "describe") == '{"answer":"ok"}'
    image_parts = seen[1]["body"]["contents"][0]["parts"]
    assert image_parts[0]["inlineData"]["mimeType"] == "image/png"
    assert image_parts[1]["text"] == "describe"


def test_google_gemini_llm_rejects_blocked_or_empty_response():
    provider = llm_mod.GoogleGeminiLLM("key", "gemini-test", client=client_for(
        lambda req: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []})))
    with pytest.raises(ProviderError, match="unexpected or blocked"):
        provider.complete("system", "user")


def test_google_gemini_llm_error_includes_provider_detail_without_api_key():
    provider = llm_mod.GoogleGeminiLLM("private-test-key", "gemini-test", client=client_for(
        lambda r: httpx.Response(503, json={"error": {"message": "Model is overloaded; key=private-test-key"}})))
    with pytest.raises(ProviderError) as exc:
        provider.complete("system", "user")
    assert "HTTP 503" in str(exc.value)
    assert "overloaded" in str(exc.value)
    assert "private-test-key" not in str(exc.value)


def test_anthropic_request_and_response_parsing():
    seen = {}
    def handler(req):
        seen["h"], seen["body"], seen["url"] = dict(req.headers), json.loads(req.content), str(req.url)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Answer "}, {"type": "text", "text": "[2]"}]})
    p = llm_mod.AnthropicLLM("key", "claude-test", client=client_for(handler))
    assert p.complete("sys", "usr", json_mode=True) == "Answer [2]"
    assert seen["url"].endswith("/v1/messages") and seen["h"]["x-api-key"] == "key" and seen["h"]["anthropic-version"]
    assert "JSON" in seen["body"]["system"] and seen["body"]["messages"] == [{"role": "user", "content": "usr"}]


def test_llm_malformed_response_is_a_provider_error():
    p = llm_mod.OpenAICompatibleLLM("http://x/v1", "", "m", client_for(lambda r: httpx.Response(200, json={"oops": 1})))
    with pytest.raises(ProviderError):
        p.complete("s", "u")


def test_openai_stt_parses_timestamped_segments(tmp_path):
    wav = tmp_path / "a.wav"; wav.write_bytes(b"RIFF....WAVE")
    seen = {}
    def handler(r):
        seen["url"] = str(r.url)
        seen["authorization"] = r.headers.get("authorization")
        seen["multipart"] = r.read().decode("utf-8", errors="replace")
        return httpx.Response(200, json={"segments": [{"start": 0.0, "end": 2.5, "text": " Hello "}, {"start": 2.5, "end": 4.0, "text": "  "}]})
    out = stt_mod.OpenAIWhisperSTT("http://x/v1", "k", "whisper-1", client_for(handler)).transcribe(str(wav))
    assert [(s.start, s.end, s.text) for s in out] == [(0.0, 2.5, "Hello")]
    assert seen["url"] == "http://x/v1/audio/transcriptions" and seen["authorization"] == "Bearer k"
    assert 'name="timestamp_granularities[]"' in seen["multipart"] and "segment" in seen["multipart"]
    with pytest.raises(ProviderError, match="no timestamped segments"):
        stt_mod.OpenAIWhisperSTT("http://x/v1", "k", "whisper-1", client_for(lambda r: httpx.Response(200, json={"text": "x"}))).transcribe(str(wav))


def test_openai_stt_rejects_models_without_timestamped_verbose_json():
    with pytest.raises(ProviderUnavailable, match="STT_MODEL=whisper-1"):
        stt_mod.OpenAIWhisperSTT("http://x/v1", "k", "gpt-4o-transcribe")


def test_startup_embedding_probe_confirms_dimension(monkeypatch):
    class Probe:
        name = "probe-model"
        def embed(self, texts):
            return [[0.0] * 768 for _ in texts]

    monkeypatch.setattr(emb, "get_embedding_provider", lambda: Probe())
    emb.validate_embedding_dimension.cache_clear()
    try:
        assert emb.validate_embedding_dimension() == 768
        settings = get_settings()
        monkeypatch.setattr(settings, "embedding_dim", 512)
        emb.validate_embedding_dimension.cache_clear()
        with pytest.raises(RuntimeError, match=r"vector\(768\)"):
            emb.validate_embedding_dimension()
        monkeypatch.setattr(settings, "embedding_dim", 768)
        monkeypatch.setattr(emb, "get_embedding_provider", lambda: type("BadProbe", (), {
            "name": "bad-probe", "embed": lambda self, texts: [[0.0] * 384 for _ in texts]
        })())
        emb.validate_embedding_dimension.cache_clear()
        with pytest.raises(RuntimeError, match="returned 384 dimensions"):
            emb.validate_embedding_dimension()
    finally:
        emb.validate_embedding_dimension.cache_clear()


def test_provider_selection_and_clear_configuration_errors(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "none")
    assert llm_mod.get_llm() is None
    monkeypatch.setattr(s, "llm_provider", "openai"); monkeypatch.setattr(s, "llm_model", "m"); monkeypatch.setattr(s, "llm_api_key", "")
    with pytest.raises(ProviderUnavailable, match="LLM_API_KEY"):
        llm_mod.get_llm()
    monkeypatch.setattr(s, "llm_api_key", "k")
    assert llm_mod.get_llm().openai_api is True
    monkeypatch.setattr(s, "llm_provider", "anthropic"); monkeypatch.setattr(s, "llm_api_key", "k")
    assert llm_mod.get_llm().name == "anthropic:m"
    monkeypatch.setattr(s, "llm_provider", "ollama"); monkeypatch.setattr(s, "llm_api_key", "")
    assert "11434" in llm_mod.get_llm().base_url
    monkeypatch.setattr(s, "llm_provider", "xai"); monkeypatch.setattr(s, "llm_api_key", "grok-key")
    assert llm_mod.get_llm().base_url == "https://api.x.ai/v1"
    monkeypatch.setattr(s, "llm_provider", "google"); monkeypatch.setattr(s, "llm_api_key", "google-key")
    monkeypatch.setattr(s, "llm_model", "gemini-3.8-flash")
    assert isinstance(llm_mod.get_llm(), llm_mod.GoogleGeminiLLM)
    monkeypatch.setattr(s, "embedding_provider", "google"); monkeypatch.setattr(s, "embedding_api_key", "google-key")
    monkeypatch.setattr(s, "embedding_model", "gemini-embedding-001")
    assert isinstance(emb.get_embedding_provider(), emb.GoogleGeminiEmbedding)
    monkeypatch.setattr(s, "llm_provider", "mystery")
    with pytest.raises(ProviderUnavailable, match="Unknown"):
        llm_mod.get_llm()
    monkeypatch.setattr(s, "stt_provider", "none")
    with pytest.raises(ProviderUnavailable, match="transcript"):
        stt_mod.get_stt()


def test_whisper_local_explains_missing_dependency(monkeypatch):
    import builtins
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, *a, **k: (_ for _ in ()).throw(ImportError()) if n == "faster_whisper" else real(n, *a, **k))
    with pytest.raises(ProviderUnavailable, match="requirements-optional"):
        stt_mod.WhisperLocalSTT("base")


def test_capabilities_endpoint_reports_the_truth(client, alice, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "none")
    monkeypatch.setattr(settings, "embedding_provider", "local-hash")
    c = client.get("/api/system/capabilities", headers=alice).json()
    assert c["llm"] == {"configured": False, "provider": None}
    assert c["embeddings"] == {"provider": "local-hash", "semantic": False}
    assert c["speech_to_text"]["configured"] is False and isinstance(c["ocr"]["available"], bool)


def test_google_gemini_llm_filters_thinking_parts():
    parts = [
        {"text": "Internal reasoning trace that should be ignored.", "thought": True},
        {"text": "Actual visible completion."},
    ]
    provider = llm_mod.GoogleGeminiLLM(
        "key", "gemini-3.5-flash-lite",
        client=client_for(lambda req: httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]}))
    )
    result = provider.complete("system", "user")
    assert result == "Actual visible completion."
    assert "Internal reasoning trace" not in result


def test_get_llm_supports_model_override(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "google")
    monkeypatch.setattr(s, "llm_api_key", "google-key")
    monkeypatch.setattr(s, "llm_model", "gemini-3.8-flash")
    default_llm = llm_mod.get_llm()
    assert default_llm.model == "gemini-3.8-flash"
    override_llm = llm_mod.get_llm(model="gemini-3.5-flash-lite")
    assert override_llm.model == "gemini-3.5-flash-lite"

