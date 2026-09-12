import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import LLMRequest, Message
from rbxforge.core.tools import ToolDefinition
from rbxforge.providers.ollama.provider import OllamaProvider


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
async def test_ollama_tool_calling_parses_tool_calls():
    client = MagicMock()
    client.post = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "qwen3:4b",
        "message": {
            "content": "Running tool",
            "tool_calls": [
                {
                    "id": "call_123",
                    "function": {
                        "name": "read_file",
                        "arguments": {"filepath": "player.gd"},
                    },
                }
            ],
        },
    }
    client.post.return_value = mock_resp

    provider = OllamaProvider(client=client)
    tools = [ToolDefinition("read_file", "Read file", {"type": "object"}, False)]
    res = await provider.generate_with_tools(LLMRequest([Message("user", "read player.gd")]), tools)

    assert res.text == "Running tool"
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].name == "read_file"
    assert res.tool_calls[0].arguments == {"filepath": "player.gd"}
    assert res.tool_calls[0].call_id == "call_123"


@pytest.mark.asyncio
async def test_ollama_tool_calling_handles_json_str_args_and_empty_calls():
    client = MagicMock()
    client.post = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "qwen3:4b",
        "message": {
            "content": "No tools called",
            "tool_calls": [],
        },
    }
    client.post.return_value = mock_resp

    provider = OllamaProvider(client=client)
    tools = [ToolDefinition("read_file", "Read file", {"type": "object"}, False)]
    res = await provider.generate_with_tools(LLMRequest([Message("user", "hello")]), tools)

    assert res.text == "No tools called"
    assert res.tool_calls == []


@pytest.mark.asyncio
async def test_ollama_tool_calling_message_history_formatting():
    client = MagicMock()
    client.post = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "qwen3:4b",
        "message": {"content": "Done"},
    }
    client.post.return_value = mock_resp

    provider = OllamaProvider(client=client)
    messages = [
        Message("user", "read player.gd"),
        Message("model", json.dumps({"__rbxforge_function_calls__": [{"name": "read_file", "args": {"filepath": "player.gd"}}]})),
        Message("tool", json.dumps({"__rbxforge_function_response__": {"name": "read_file", "ok": True, "data": "extends Node"}})),
    ]
    tools = [ToolDefinition("read_file", "Read file", {"type": "object"}, False)]
    await provider.generate_with_tools(LLMRequest(messages), tools)

    args, kwargs = client.post.call_args
    posted_json = kwargs["json"]
    sent_msgs = posted_json["messages"]
    assert sent_msgs[0] == {"role": "user", "content": "read player.gd"}
    assert sent_msgs[1]["role"] == "assistant"
    assert sent_msgs[1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert sent_msgs[2]["role"] == "tool"


@pytest.mark.asyncio
async def test_ollama_http_error_handling():
    client = MagicMock()
    client.post = AsyncMock(side_effect=httpx.HTTPError("Connection refused"))

    provider = OllamaProvider(client=client)
    with pytest.raises(ProviderError) as exc_info:
        await provider.generate(LLMRequest([Message("user", "hi")]))
    assert exc_info.value.provider == "ollama"

    with pytest.raises(ProviderError) as exc_info2:
        await provider.generate_with_tools(LLMRequest([Message("user", "hi")]), [])
    assert exc_info2.value.provider == "ollama"


@pytest.mark.asyncio
async def test_ollama_list_models_capability_detection():
    client = MagicMock()
    client.get = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "models": [
            {"name": "qwen3:4b"},
            {"name": "deepseek-coder:6.7b"},
        ]
    }
    client.get.return_value = mock_resp

    provider = OllamaProvider(client=client)
    models = await provider.list_models()

    assert len(models) == 2
    assert models[0].name == "qwen3:4b"
    assert models[0].supports_tools is True
    assert models[1].name == "deepseek-coder:6.7b"
    assert models[1].supports_tools is False
