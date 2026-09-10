import pytest

from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import LLMRequest, LLMResponse, Message, TaskComplexity
from rbxforge.core.router import LLMRouter


class FakeProvider:
    def __init__(self, name, error=None):
        self.name = name
        self.error = error
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return LLMResponse("ok", self.name, "test")

    async def health(self):
        return True


@pytest.mark.asyncio
async def test_simple_routes_to_ollama():
    ollama = FakeProvider("ollama")
    gemini = FakeProvider("gemini")
    result = await LLMRouter({"ollama": ollama, "gemini": gemini}).generate(
        LLMRequest([Message("user", "hi")]), TaskComplexity.SIMPLE
    )
    assert result.provider == "ollama"
    assert ollama.calls == 1
    assert gemini.calls == 0


@pytest.mark.asyncio
async def test_moderate_falls_back_to_gemini_on_retryable_ollama_error():
    ollama = FakeProvider("ollama", ProviderError("busy", "ollama", retryable=True, status_code=503))
    gemini = FakeProvider("gemini")
    result = await LLMRouter({"ollama": ollama, "gemini": gemini}).generate(
        LLMRequest([Message("user", "hi")]), TaskComplexity.MODERATE
    )
    assert result.provider == "gemini"
    assert ollama.calls == 1
    assert gemini.calls == 1


@pytest.mark.asyncio
async def test_non_retryable_error_does_not_fallback():
    ollama = FakeProvider("ollama", ProviderError("bad request", "ollama"))
    gemini = FakeProvider("gemini")
    with pytest.raises(ProviderError):
        await LLMRouter({"ollama": ollama, "gemini": gemini}).generate(
            LLMRequest([Message("user", "hi")]), TaskComplexity.MODERATE
        )
    assert gemini.calls == 0


@pytest.mark.asyncio
async def test_explicit_provider_bypasses_complexity_route():
    ollama = FakeProvider("ollama")
    gemini = FakeProvider("gemini")
    result = await LLMRouter({"ollama": ollama, "gemini": gemini}).generate(
        LLMRequest([Message("user", "hi")]), TaskComplexity.SIMPLE, provider="gemini"
    )
    assert result.provider == "gemini"
    assert ollama.calls == 0
