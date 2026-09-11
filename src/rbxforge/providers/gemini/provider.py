import base64
import json

from rbxforge.core.agent import ToolModelResponse
from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import LLMRequest, LLMResponse, Usage
from rbxforge.core.tools import ToolCall, ToolDefinition


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, client=None):
        self.api_key = api_key
        self.model = model
        self.client = client

    def _get_client(self):
        if self.client is not None:
            return self.client
        from google import genai
        self.client = genai.Client(api_key=self.api_key)
        return self.client

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key and self.client is None:
            raise ProviderError("Gemini API key is not configured", self.name)
        client = self._get_client()
        contents = [{"role": "user" if m.role == "user" else "model", "parts": [{"text": m.content}]} for m in request.messages]
        config = {"temperature": request.temperature}
        if request.max_tokens is not None:
            config["max_output_tokens"] = request.max_tokens
        try:
            models = getattr(client, "aio", client).models
            response = await models.generate_content(model=request.model or self.model, contents=contents, config=config)
            metadata = getattr(response, "usage_metadata", None)
            usage = Usage(getattr(metadata, "prompt_token_count", 0), getattr(metadata, "candidates_token_count", 0)) if metadata else None
            return LLMResponse(response.text, self.name, request.model or self.model, usage)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            text = str(exc)
            retryable = status == 429 or status is not None and status >= 500 or "429" in text or "RESOURCE_EXHAUSTED" in text
            raise ProviderError(text, self.name, retryable=retryable, status_code=status) from exc


    async def generate_with_tools(self, request: LLMRequest, tools: list[ToolDefinition]) -> ToolModelResponse:
        """Generate a response while exposing provider-neutral function declarations."""
        if not self.api_key and self.client is None:
            raise ProviderError("Gemini API key is not configured", self.name)
        client = self._get_client()
        contents = []
        for message in request.messages:
            if message.role == "model":
                try:
                    marker = json.loads(message.content)
                except (TypeError, ValueError):
                    marker = None
                calls = marker.get("__rbxforge_function_calls__") if isinstance(marker, dict) else None
                if calls is not None:
                    parts = []
                    for item in calls:
                        part_dict = {
                            "function_call": {
                                "name": item["name"],
                                "args": item.get("args", {}),
                                **({"id": item["id"]} if item.get("id") else {}),
                            }
                        }
                        sig = item.get("thought_signature")
                        if sig is not None:
                            if isinstance(sig, str):
                                try:
                                    part_dict["thought_signature"] = base64.b64decode(sig)
                                except Exception:
                                    part_dict["thought_signature"] = sig.encode("utf-8")
                            elif isinstance(sig, bytes):
                                part_dict["thought_signature"] = sig
                        parts.append(part_dict)
                    contents.append({
                        "role": "model",
                        "parts": parts,
                    })
                    continue
            if message.role == "tool":
                try:
                    marker = json.loads(message.content)
                except (TypeError, ValueError):
                    marker = None
                function_response = marker.get("__rbxforge_function_response__") if isinstance(marker, dict) else None
                if function_response is not None:
                    response_payload = {
                        "ok": function_response.get("ok", False),
                        "data": function_response.get("data"),
                        "error": function_response.get("error"),
                    }
                    contents.append({
                        "role": "user",
                        "parts": [
                            {
                                "function_response": {
                                    "name": function_response["name"],
                                    "response": response_payload,
                                    **({"id": function_response["id"]} if function_response.get("id") else {}),
                                }
                            }
                        ],
                    })
                    continue
            contents.append({
                "role": "user" if message.role in {"user", "tool"} else "model",
                "parts": [{"text": message.content}],
            })
        def _clean_schema(obj):
            if isinstance(obj, dict):
                return {
                    k: _clean_schema(v)
                    for k, v in obj.items()
                    if k not in ("additionalProperties", "additional_properties")
                }
            if isinstance(obj, list):
                return [_clean_schema(item) for item in obj]
            return obj

        from google.genai import types
        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=_clean_schema(tool.parameters),
            )
            for tool in tools
        ]
        config = {
            "temperature": request.temperature,
            "tools": [{"function_declarations": declarations}],
        }
        if request.max_tokens is not None:
            config["max_output_tokens"] = request.max_tokens
        try:
            models = getattr(client, "aio", client).models
            response = await models.generate_content(
                model=request.model or self.model, contents=contents, config=config
            )
            calls: list[ToolCall] = []
            for candidate in getattr(response, "candidates", []) or []:
                content = getattr(candidate, "content", None)
                for part in getattr(content, "parts", []) or []:
                    function_call = getattr(part, "function_call", None)
                    if function_call is not None:
                        sig = getattr(part, "thought_signature", None)
                        if isinstance(sig, str):
                            try:
                                sig = base64.b64decode(sig)
                            except Exception:
                                sig = sig.encode("utf-8")
                        calls.append(
                            ToolCall(
                                str(getattr(function_call, "name", "")),
                                dict(getattr(function_call, "args", {}) or {}),
                                getattr(function_call, "id", None),
                                thought_signature=sig,
                            )
                        )
            return ToolModelResponse(text=getattr(response, "text", "") or "", tool_calls=calls)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            text = str(exc)
            retryable = status == 429 or status is not None and status >= 500 or "429" in text or "RESOURCE_EXHAUSTED" in text
            raise ProviderError(text, self.name, retryable=retryable, status_code=status) from exc

    async def health(self) -> bool:
        return bool(self.api_key or self.client)
