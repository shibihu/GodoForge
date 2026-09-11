from unittest.mock import MagicMock
import pytest

from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import LLMRequest, Message
from rbxforge.providers.gemini.provider import GeminiProvider


@pytest.mark.asyncio
async def test_gemini_provider_does_not_retry_on_400():
    client = MagicMock()
    mock_models = MagicMock()
    client.aio.models = mock_models

    call_count = 0

    async def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        exc = Exception("400 INVALID_ARGUMENT")
        exc.status_code = 400
        raise exc

    mock_models.generate_content = mock_generate

    provider = GeminiProvider("key", "gemini-test", client=client)
    with pytest.raises(ProviderError) as exc_info:
        await provider.generate(LLMRequest([Message("user", "test")]))

    assert call_count == 1
    assert exc_info.value.retryable is False
