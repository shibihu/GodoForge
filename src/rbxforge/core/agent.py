from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .llm.models import LLMRequest, LLMResponse, Message
from .tools import GodotToolExecutor, ToolCall, ToolDefinition


@dataclass(frozen=True)
class ToolModelResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


ModelCall = Callable[[LLMRequest, list[ToolDefinition]], Awaitable[ToolModelResponse]]


class ToolAgent:
    def __init__(self, model_call: ModelCall, max_tool_calls: int = 12):
        if max_tool_calls <= 0:
            raise ValueError("max_tool_calls must be greater than zero")
        self.model_call = model_call
        self.max_tool_calls = max_tool_calls

    async def run(self, request: LLMRequest, executor: GodotToolExecutor) -> LLMResponse:
        messages = list(request.messages)
        tool_calls_used = 0
        while tool_calls_used < self.max_tool_calls:
            response = await self.model_call(
                LLMRequest(messages, request.model, request.temperature, request.max_tokens),
                executor.definitions(),
            )
            if not response.tool_calls:
                return LLMResponse(response.text, "gemini", request.model or "", None)

            function_calls = []
            for call in response.tool_calls:
                call_dict = {"name": call.name, "args": call.arguments, "id": call.call_id}
                if call.thought_signature is not None:
                    call_dict["thought_signature"] = base64.b64encode(call.thought_signature).decode("ascii")
                function_calls.append(call_dict)

            messages.append(
                Message(
                    "model",
                    json.dumps(
                        {
                            "__rbxforge_function_calls__": function_calls
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            for call in response.tool_calls:
                if tool_calls_used >= self.max_tool_calls:
                    break
                result = executor.execute(call)
                tool_calls_used += 1
                messages.append(
                    Message(
                        "tool",
                        json.dumps(
                            {
                                "__rbxforge_function_response__": {
                                    "name": call.name,
                                    "id": call.call_id,
                                    "ok": result.ok,
                                    "data": result.data,
                                    "error": result.error,
                                }
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
        return LLMResponse(
            f"RBXForge stopped because it reached the maximum tool-call limit ({self.max_tool_calls}).",
            "gemini",
            request.model or "",
            None,
        )
