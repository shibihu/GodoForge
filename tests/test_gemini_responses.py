import pytest

from rbxforge.core.llm.models import LLMRequest, Message
from rbxforge.core.tools import ToolDefinition
from rbxforge.providers.gemini.provider import GeminiProvider


READ_TOOL = ToolDefinition(
    "read_file",
    "Read a file",
    {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    True,
)


class _FunctionCall:
    def __init__(self, name, args, call_id=None):
        self.name = name
        self.args = args
        if call_id is not None:
            self.id = call_id


class _TextPart:
    def __init__(self, text):
        self.text = text
        self.function_call = None
        self.thought_signature = None


class _CallPart:
    def __init__(self, name, args, call_id=None, signature=None):
        self.text = None
        self.function_call = _FunctionCall(name, args, call_id)
        self.thought_signature = signature


class _Content:
    def __init__(self, parts):
        self.parts = parts


class _Candidate:
    def __init__(self, parts):
        self.content = _Content(parts)


class _Response:
    def __init__(self, candidates):
        self.candidates = candidates

    @property
    def text(self):
        raise AssertionError(
            "response.text must not be accessed when the response may contain function calls"
        )


class _Models:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _Aio:
    def __init__(self, response):
        self.models = _Models(response)


class _Client:
    def __init__(self, response):
        self.aio = _Aio(response)


def _run(response):
    client = _Client(response)
    provider = GeminiProvider("key", "gemini-test", client=client)
    return provider.generate_with_tools(LLMRequest([Message("user", "go")]), [READ_TOOL])


@pytest.mark.asyncio
async def test_text_only_response_preserves_text():
    response = _Response([_Candidate([_TextPart("hello "), _TextPart("world")])])
    result = await _run(response)
    assert result.text == "hello world"
    assert result.tool_calls == []


@pytest.mark.asyncio
async def test_function_call_only_response_returns_calls():
    response = _Response(
        [_Candidate([_CallPart("read_file", {"path": "player.gd"}, call_id="call-1")])]
    )
    result = await _run(response)
    assert result.text == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "player.gd"}
    assert result.tool_calls[0].call_id == "call-1"


@pytest.mark.asyncio
async def test_mixed_text_and_function_call_keeps_both():
    response = _Response(
        [
            _Candidate(
                [
                    _TextPart("Let me inspect that. "),
                    _CallPart("read_file", {"path": "player.gd"}, call_id="call-1"),
                ]
            )
        ]
    )
    result = await _run(response)
    assert result.text == "Let me inspect that. "
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read_file"


@pytest.mark.asyncio
async def test_multiple_function_calls_in_one_response_are_preserved_in_order():
    response = _Response(
        [
            _Candidate(
                [
                    _CallPart("read_file", {"path": "a.gd"}, call_id="call-1"),
                    _CallPart("read_file", {"path": "b.gd"}, call_id="call-2"),
                    _CallPart("search_code", {"query": "health"}, call_id="call-3"),
                ]
            )
        ]
    )
    result = await _run(response)
    assert [call.name for call in result.tool_calls] == ["read_file", "read_file", "search_code"]
    assert [call.arguments["path"] for call in result.tool_calls[:2]] == ["a.gd", "b.gd"]


@pytest.mark.asyncio
async def test_function_call_without_id_yields_none_call_id():
    response = _Response([_Candidate([_CallPart("read_file", {"path": "a.gd"})])])
    result = await _run(response)
    assert result.tool_calls[0].call_id is None


@pytest.mark.asyncio
async def test_empty_and_missing_candidates_do_not_crash():
    empty = await _run(_Response([]))
    assert empty.text == ""
    assert empty.tool_calls == []

    missing = await _run(_Response(None))
    assert missing.text == ""
    assert missing.tool_calls == []


@pytest.mark.asyncio
async def test_bytes_thought_signature_is_preserved():
    response = _Response(
        [_Candidate([_CallPart("read_file", {"path": "a.gd"}, call_id="c", signature=b"raw-bytes")])]
    )
    result = await _run(response)
    assert result.tool_calls[0].thought_signature == b"raw-bytes"


@pytest.mark.asyncio
async def test_base64_thought_signature_is_decoded():
    import base64

    encoded = base64.b64encode(b"raw-bytes").decode("ascii")
    response = _Response(
        [_Candidate([_CallPart("read_file", {"path": "a.gd"}, call_id="c", signature=encoded)])]
    )
    result = await _run(response)
    assert result.tool_calls[0].thought_signature == b"raw-bytes"


@pytest.mark.asyncio
async def test_thought_signature_survives_agent_loop_and_gemini_reconstruction():
    from rbxforge.core.agent import ToolAgent, ToolModelResponse
    from rbxforge.core.tools import ToolCall, ToolResult

    class _StubExecutor:
        def definitions(self):
            return []

        def execute(self, call):
            return ToolResult(call.name, True, {"ok": True})

    captured = {"count": 0, "history": None}

    async def model_call(request, tools):
        captured["count"] += 1
        if captured["count"] == 1:
            return ToolModelResponse(
                tool_calls=[
                    ToolCall("read_file", {"path": "a.gd"}, "call-1", thought_signature=b"sig-bytes")
                ]
            )
        captured["history"] = list(request.messages)
        return ToolModelResponse(text="done")

    agent = ToolAgent(model_call, max_tool_calls=4)
    await agent.run(LLMRequest([Message("user", "read it")]), _StubExecutor())

    assert captured["history"] is not None
    serialized_model_message = captured["history"][1]
    assert "sig-bytes" not in serialized_model_message.content  # bytes are not dumped into the raw JSON

    client = _Client(_Response([_Candidate([_TextPart("ok")])]))
    provider = GeminiProvider("key", "gemini-test", client=client)
    await provider.generate_with_tools(LLMRequest(list(captured["history"])), [])

    contents = client.aio.models.calls[-1]["contents"]
    reconstructed = [part for entry in contents for part in entry["parts"] if "function_call" in part]
    assert len(reconstructed) == 1
    assert reconstructed[0]["thought_signature"] == b"sig-bytes"


def _run_generate(response):
    client = _Client(response)
    provider = GeminiProvider("key", "gemini-test", client=client)
    return provider.generate(LLMRequest([Message("user", "hi")]))


@pytest.mark.asyncio
async def test_generate_text_only_response_never_touches_response_text():
    # _Response.text raises, so this passes only if parts are read explicitly.
    response = _Response([_Candidate([_TextPart("hello "), _TextPart("world")])])
    result = await _run_generate(response)
    assert result.text == "hello world"
    assert result.provider == "gemini"
    assert result.model == "gemini-test"


@pytest.mark.asyncio
async def test_generate_empty_response_returns_empty_text():
    assert (await _run_generate(_Response([]))).text == ""
    assert (await _run_generate(_Response(None))).text == ""


@pytest.mark.asyncio
async def test_generate_malformed_response_is_tolerated():
    class _Weird:
        candidates = [object(), _Candidate([_TextPart("ok")])]
        usage_metadata = None

    assert (await _run_generate(_Weird())).text == "ok"

    class _NoParts:
        candidates = [object()]

    assert (await _run_generate(_NoParts())).text == ""


@pytest.mark.asyncio
async def test_generate_function_call_part_does_not_access_response_text():
    # generate() never exposes tools, but an unexpected function-call part must
    # not trigger the response.text warning/error path.
    response = _Response([_Candidate([_CallPart("read_file", {"path": "a.gd"})])])
    assert (await _run_generate(response)).text == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_generate_transient_error_makes_one_request_and_is_retryable(status):
    # generate() itself must not retry: the router falls through to the next
    # provider. This guards against an excessive/double retry storm.
    from rbxforge.core.llm.errors import ProviderError

    client = _Client(_Response([_Candidate([_TextPart("ok")])]))

    async def generate_content(**kwargs):
        client.aio.models.calls.append(kwargs)
        exc = Exception(f"{status} transient failure")
        exc.status_code = status
        raise exc

    client.aio.models.generate_content = generate_content
    provider = GeminiProvider("key", "gemini-test", client=client)

    with pytest.raises(ProviderError) as exc_info:
        await provider.generate(LLMRequest([Message("user", "hi")]))

    assert len(client.aio.models.calls) == 1
    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == status


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_generate_permanent_error_fails_fast(status):
    from rbxforge.core.llm.errors import ProviderError

    client = _Client(_Response([_Candidate([_TextPart("ok")])]))

    async def generate_content(**kwargs):
        client.aio.models.calls.append(kwargs)
        exc = Exception(f"{status} permanent failure")
        exc.status_code = status
        raise exc

    client.aio.models.generate_content = generate_content
    provider = GeminiProvider("key", "gemini-test", client=client)

    with pytest.raises(ProviderError) as exc_info:
        await provider.generate(LLMRequest([Message("user", "hi")]))

    assert len(client.aio.models.calls) == 1
    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == status


@pytest.mark.asyncio
async def test_tool_declarations_are_sent_with_function_declarations():
    client = _Client(_Response([_Candidate([_TextPart("ok")])]))
    provider = GeminiProvider("key", "gemini-test", client=client)
    await provider.generate_with_tools(LLMRequest([Message("user", "go")]), [READ_TOOL])

    config = client.aio.models.calls[0]["config"]
    declaration = config["tools"][0]["function_declarations"][0]
    name = getattr(declaration, "name", None) or declaration["name"]
    assert name == "read_file"
