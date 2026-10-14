"""Test doubles. They exist only in the test suite and are never used by the application."""
from app.services.providers.base import ProviderError, TranscriptSegment


class FakeLLM:
    name = "fake-llm"

    def __init__(self, reply="", raises: Exception | None = None, general_reply="General background."):
        self.reply, self.raises, self.general_reply = reply, raises, general_reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, system, user, *, json_mode=False, max_tokens=1200):
        self.calls.append((system, user))
        if self.raises:
            raise self.raises
        return self.general_reply if system.startswith("You are a tutor. The student's course") else self.reply

    def describe_image(self, image_png, prompt):
        return "a diagram"


class FakeSTT:
    name = "fake-stt"

    def __init__(self, segments):
        self.segments = segments

    def transcribe(self, wav_path):
        return self.segments


def segs(*triples):
    return [TranscriptSegment(a, b, t) for a, b, t in triples]


__all__ = ["FakeLLM", "FakeSTT", "segs", "ProviderError"]


class ScriptLLM:
    """LLM double whose reply is computed from the prompts, so tests can drive generation and verification separately."""
    name = "script-llm"

    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def complete(self, system, user, *, json_mode=False, max_tokens=1200):
        self.calls.append((system, user))
        return self.fn(system, user)

    def describe_image(self, image_png, prompt):
        return "NONE"
