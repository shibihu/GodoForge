from pathlib import Path

import pytest

from rbxforge.core.llm.models import LLMRequest, Message
from rbxforge.core.tools import ToolCall, ToolDefinition
from rbxforge.providers.gemini.provider import GeminiProvider


class FakeResponse:
    text = "done"
    usage_metadata = None
    candidates = []


class FakeModels:
    def __init__(self):
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse()


class FakeAio:
    def __init__(self):
        self.models = FakeModels()


class FakeClient:
    def __init__(self):
        self.aio = FakeAio()


@pytest.mark.asyncio
async def test_gemini_provider_can_receive_tool_declarations():
    client = FakeClient()
    provider = GeminiProvider("key", "gemini-test", client=client)
    definitions = [
        ToolDefinition(
            "read_file",
            "Read a file",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            True,
        )
    ]

    result = await provider.generate_with_tools(LLMRequest([Message("user", "read it")]), definitions)

    assert result.text == "done"
    config = client.aio.models.calls[0]["config"]
    assert config["tools"][0]["function_declarations"][0]["name"] == "read_file"


class FakeFunctionCall:
    name = "read_file"
    args = {"path": "player.gd"}
    id = "call-1"


class FakePart:
    function_call = FakeFunctionCall()


class FakeContent:
    parts = [FakePart()]


class FakeCandidate:
    content = FakeContent()


class ToolCallResponse(FakeResponse):
    text = ""
    candidates = [FakeCandidate()]


@pytest.mark.asyncio
async def test_gemini_provider_translates_function_calls():
    client = FakeClient()
    client.aio.models.generate_content = lambda **kwargs: None

    async def generate_content(**kwargs):
        return ToolCallResponse()

    client.aio.models.generate_content = generate_content
    provider = GeminiProvider("key", "gemini-test", client=client)
    result = await provider.generate_with_tools(
        LLMRequest([Message("user", "read it")]),
        [ToolDefinition("read_file", "Read a file", {"type": "object"}, True)],
    )
    assert result.tool_calls == [ToolCall("read_file", {"path": "player.gd"}, "call-1")]


@pytest.mark.asyncio
async def test_gemini_provider_translates_agent_tool_history():
    client = FakeClient()
    provider = GeminiProvider("key", "gemini-test", client=client)
    request = LLMRequest(
        [
            Message("user", "read it"),
            Message("model", '{"__rbxforge_function_calls__":[{"name":"read_file","args":{"path":"player.gd"},"id":"call-1"}]}'),
            Message("tool", '{"__rbxforge_function_response__":{"name":"read_file","id":"call-1","ok":true,"data":"extends Node\\n","error":null}}'),
        ]
    )
    await provider.generate_with_tools(request, [ToolDefinition("read_file", "Read", {"type": "object"}, True)])
    contents = client.aio.models.calls[-1]["contents"]
    assert contents[1]["parts"][0]["function_call"]["name"] == "read_file"
    assert contents[2]["parts"][0]["function_response"]["response"]["data"] == "extends Node\n"
