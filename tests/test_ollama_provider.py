import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import LLMRequest, Message
from rbxforge.core.tools import ToolDefinition
from rbxforge.providers.ollama.provider import OllamaProvider


@pytest.mark.asyncio
async def test_ollama_configurable_timeout():
    provider = OllamaProvider(timeout=120.0, connect_timeout=15.0)
    assert provider.timeout.read == 120.0
    assert provider.timeout.connect == 15.0


@pytest.mark.asyncio
async def test_ollama_normal_generation():
    client = MagicMock()
    client.post = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "qwen3:4b",
        "message": {"content": "Hello from Ollama"},
        "prompt_eval_count": 10,
        "eval_count": 5,
    }
    client.post.return_value = mock_resp

    provider = OllamaProvider(client=client)
    res = await provider.generate(LLMRequest([Message("user", "hi")]))

    assert res.text == "Hello from Ollama"
    assert res.provider == "ollama"
    assert res.model == "qwen3:4b"
    assert res.usage.prompt_tokens == 10
    assert res.usage.completion_tokens == 5


@pytest.mark.asyncio
async def test_ollama_tool_calling_parses_multiple_tool_calls():
    client = MagicMock()
    client.post = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "qwen3:4b",
        "message": {
            "content": "Running tools",
            "tool_calls": [
                {
                    "id": "call_123",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"filepath": "player.gd"}',
                    },
                },
                {
                    "id": "call_456",
                    "function": {
                        "name": "search_code",
                        "arguments": {"pattern": "CharacterBody2D"},
                    },
                },
            ],
        },
    }
    client.post.return_value = mock_resp

    provider = OllamaProvider(client=client)
    tools = [ToolDefinition("read_file", "Read file", {"type": "object"}, False)]
    res = await provider.generate_with_tools(LLMRequest([Message("user", "inspect")]), tools)

    assert res.text == "Running tools"
    assert len(res.tool_calls) == 2
    assert res.tool_calls[0].name == "read_file"
    assert res.tool_calls[0].arguments == {"filepath": "player.gd"}
    assert res.tool_calls[1].name == "search_code"
    assert res.tool_calls[1].arguments == {"pattern": "CharacterBody2D"}


@pytest.mark.asyncio
async def test_ollama_tool_calling_handles_empty_or_malformed_calls():
    client = MagicMock()
    client.post = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "qwen3:4b",
        "message": {
            "content": "No tools called",
            "tool_calls": "invalid_type",
        },
    }
    client.post.return_value = mock_resp

    provider = OllamaProvider(client=client)
    tools = [ToolDefinition("read_file", "Read file", {"type": "object"}, False)]
    res = await provider.generate_with_tools(LLMRequest([Message("user", "hello")]), tools)

    assert res.text == "No tools called"
    assert res.tool_calls == []


@pytest.mark.asyncio
async def test_ollama_error_handling_timeout_and_connection():
    client = MagicMock()
    client.post = AsyncMock(side_effect=httpx.ReadTimeout("Read timeout"))

    provider = OllamaProvider(client=client)
    with pytest.raises(ProviderError) as exc_info:
        await provider.generate(LLMRequest([Message("user", "hi")]))
    assert exc_info.value.retryable is True
    assert "timed out" in exc_info.value.message

    client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    with pytest.raises(ProviderError) as exc_info2:
        await provider.generate_with_tools(LLMRequest([Message("user", "hi")]), [])
    assert exc_info2.value.retryable is True
    assert "Cannot connect" in exc_info2.value.message


@pytest.mark.asyncio
async def test_ollama_malformed_json_response():
    client = MagicMock()
    client.post = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
    client.post.return_value = mock_resp

    provider = OllamaProvider(client=client)
    with pytest.raises(ProviderError) as exc_info:
        await provider.generate(LLMRequest([Message("user", "hi")]))
    assert "Malformed JSON" in exc_info.value.message


@pytest.mark.asyncio
async def test_ollama_list_models_capability_detection_api_show():
    client = MagicMock()
    client.get = AsyncMock()
    client.post = AsyncMock()

    tags_resp = MagicMock()
    tags_resp.is_success = True
    tags_resp.json.return_value = {
        "models": [
            {"name": "custom-tool-model:latest"},
            {"name": "plain-text-model:latest"},
        ]
    }
    client.get.return_value = tags_resp

    def show_side_effect(url, json):
        resp = MagicMock()
        resp.is_success = True
        if json.get("name") == "custom-tool-model:latest":
            resp.json.return_value = {"template": "some template with tool_calls in it"}
        else:
            resp.json.return_value = {"template": "basic template"}
        return resp

    client.post.side_effect = show_side_effect

    provider = OllamaProvider(client=client)
    models = await provider.list_models()

    assert len(models) == 2
    assert models[0].name == "custom-tool-model:latest"
    assert models[0].supports_tools is True
    assert models[1].name == "plain-text-model:latest"
    assert models[1].supports_tools is False
