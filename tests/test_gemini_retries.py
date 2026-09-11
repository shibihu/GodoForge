import asyncio
from unittest.mock import MagicMock

import pytest

from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import LLMRequest, Message
from rbxforge.providers.gemini.provider import GeminiProvider


def _success_response(text: str = "recovered"):
    part = MagicMock(text=text, function_call=None, thought_signature=None)
    content = MagicMock(parts=[part])
    candidate = MagicMock(content=content)
    return MagicMock(candidates=[candidate])


def _provider(models):
    client = MagicMock()
    client.aio.models = models
    return GeminiProvider("key", "gemini-test", client=client)


@pytest.fixture
def fast_retries(monkeypatch):
    """Avoid real backoff sleeps while still exercising retry logic."""

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


def _request() -> LLMRequest:
    return LLMRequest([Message("user", "test")])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_transient_status_is_retried(fast_retries, status):
    models = MagicMock()
    calls = {"count": 0}

    async def generate_content(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            exc = Exception(f"{status} transient failure")
            exc.status_code = status
            raise exc
        return _success_response()

    models.generate_content = generate_content
    result = await _provider(models).generate_with_tools(_request(), [])

    assert calls["count"] == 2
    assert result.text == "recovered"


@pytest.mark.asyncio
async def test_transient_error_retries_twice_then_succeeds(fast_retries):
    models = MagicMock()
    calls = {"count": 0}

    async def generate_content(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            exc = Exception("503 Service Unavailable")
            exc.status_code = 503
            raise exc
        return _success_response("recovered-after-two-retries")

    models.generate_content = generate_content
    result = await _provider(models).generate_with_tools(_request(), [])

    assert calls["count"] == 3
    assert result.text == "recovered-after-two-retries"


@pytest.mark.asyncio
async def test_transient_error_exhausted_raises_provider_error(fast_retries):
    models = MagicMock()
    calls = {"count": 0}

    async def generate_content(*args, **kwargs):
        calls["count"] += 1
        exc = Exception("503 Service Unavailable")
        exc.status_code = 503
        raise exc

    models.generate_content = generate_content

    with pytest.raises(ProviderError) as exc_info:
        await _provider(models).generate_with_tools(_request(), [])

    assert calls["count"] == 3
    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 503
    assert "503" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_permanent_status_is_not_retried(fast_retries, status):
    models = MagicMock()
    calls = {"count": 0}

    async def generate_content(*args, **kwargs):
        calls["count"] += 1
        exc = Exception(f"{status} permanent failure")
        exc.status_code = status
        raise exc

    models.generate_content = generate_content

    with pytest.raises(ProviderError) as exc_info:
        await _provider(models).generate_with_tools(_request(), [])

    assert calls["count"] == 1
    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == status


@pytest.mark.asyncio
async def test_transient_keyword_without_status_is_retried(fast_retries):
    models = MagicMock()
    calls = {"count": 0}

    async def generate_content(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise Exception("UNAVAILABLE: backend is overloaded")
        return _success_response()

    models.generate_content = generate_content
    result = await _provider(models).generate_with_tools(_request(), [])

    assert calls["count"] == 2
    assert result.text == "recovered"


@pytest.mark.asyncio
async def test_google_genai_server_error_is_retried(fast_retries):
    from google.genai import errors

    models = MagicMock()
    calls = {"count": 0}

    async def generate_content(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise errors.ServerError(
                503, {"error": {"message": "model overloaded", "status": "UNAVAILABLE"}}
            )
        return _success_response()

    models.generate_content = generate_content
    result = await _provider(models).generate_with_tools(_request(), [])

    assert calls["count"] == 2
    assert result.text == "recovered"


@pytest.mark.asyncio
async def test_google_genai_client_error_is_not_retried(fast_retries):
    from google.genai import errors

    models = MagicMock()
    calls = {"count": 0}

    async def generate_content(*args, **kwargs):
        calls["count"] += 1
        raise errors.ClientError(
            400, {"error": {"message": "bad request", "status": "INVALID_ARGUMENT"}}
        )

    models.generate_content = generate_content

    with pytest.raises(ProviderError) as exc_info:
        await _provider(models).generate_with_tools(_request(), [])

    assert calls["count"] == 1
    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 400
