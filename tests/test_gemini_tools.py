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
    decl = config["tools"][0]["function_declarations"][0]
    name = getattr(decl, "name", None) or decl["name"]
    assert name == "read_file"


class FakeFunctionCall:
    name = "read_file"
    args = {"path": "player.gd"}
    id = "call-1"


class FakePart:
    function_call = FakeFunctionCall()
    thought_signature = b"signature-bytes"


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
    assert result.tool_calls == [ToolCall("read_file", {"path": "player.gd"}, "call-1", thought_signature=b"signature-bytes")]


@pytest.mark.asyncio
async def test_gemini_provider_preserves_thought_signature_round_trip():
    import base64
    from rbxforge.core.agent import ToolAgent

    client = FakeClient()
    sig_bytes = b"signature-bytes"

    async def model_call(req, defs):
        return ToolCallResponse().text, [ToolCall("read_file", {"path": "player.gd"}, "call-1", thought_signature=sig_bytes)]

    # 1. Test parsing of Gemini response containing thought_signature
    async def generate_content(**kwargs):
        client.aio.models.calls.append(kwargs)
        return ToolCallResponse()

    client.aio.models.generate_content = generate_content
    provider = GeminiProvider("key", "gemini-test", client=client)

    result = await provider.generate_with_tools(
        LLMRequest([Message("user", "read it")]),
        [ToolDefinition("read_file", "Read a file", {"type": "object"}, True)],
    )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].thought_signature == sig_bytes

    # 2. Test ToolAgent serialization of history with thought_signature
    encoded_sig = base64.b64encode(sig_bytes).decode("ascii")
    history_request = LLMRequest(
        [
            Message("user", "read it"),
            Message(
                "model",
                f'{{"__rbxforge_function_calls__":[{{"name":"read_file","args":{{"path":"player.gd"}},"id":"call-1","thought_signature":"{encoded_sig}"}}]}}',
            ),
            Message(
                "tool",
                '{"__rbxforge_function_response__":{"name":"read_file","id":"call-1","ok":true,"data":"extends Node\\n","error":null}}',
            ),
        ]
    )

    # 3. Test reconstruction of Gemini contents from serialized history
    await provider.generate_with_tools(
        history_request,
        [ToolDefinition("read_file", "Read", {"type": "object"}, True)],
    )

    contents = client.aio.models.calls[-1]["contents"]
    model_part = contents[1]["parts"][0]
    assert model_part["function_call"]["name"] == "read_file"
    assert model_part["thought_signature"] == sig_bytes


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
