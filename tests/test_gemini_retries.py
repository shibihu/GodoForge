from unittest.mock import MagicMock
import pytest

from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import LLMRequest, Message
from rbxforge.providers.gemini.provider import GeminiProvider


@pytest.mark.asyncio
async def test_gemini_provider_retries_on_503():
    client = MagicMock()
    mock_models = MagicMock()
    client.aio.models = mock_models

    call_count = 0

    async def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            exc = Exception("503 Service Unavailable")
            exc.status_code = 503
            raise exc

        class FakeContent:
            parts = [MagicMock(text="recovered", function_call=None)]

        class FakeCandidate:
            content = FakeContent()

        class FakeResponse:
            candidates = [FakeCandidate()]

        return FakeResponse()

    mock_models.generate_content = mock_generate

    provider = GeminiProvider("key", "gemini-test", client=client)
    res = await provider.generate_with_tools(LLMRequest([Message("user", "test")]), [])

    assert call_count == 3
    assert res.text == "recovered"


@pytest.mark.asyncio
async def test_gemini_provider_raises_provider_error_when_retries_exhausted():
    client = MagicMock()
    mock_models = MagicMock()
    client.aio.models = mock_models

    async def mock_generate(*args, **kwargs):
        exc = Exception("503 Service Unavailable")
        exc.status_code = 503
        raise exc

    mock_models.generate_content = mock_generate

    provider = GeminiProvider("key", "gemini-test", client=client)
    with pytest.raises(ProviderError) as exc_info:
        await provider.generate_with_tools(LLMRequest([Message("user", "test")]), [])

    assert "503" in str(exc_info.value)
    assert exc_info.value.retryable is True
