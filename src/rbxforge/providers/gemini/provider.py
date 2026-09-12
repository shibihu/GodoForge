import asyncio
import base64
import json
import re

from rbxforge.core.agent import ToolModelResponse
from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import CostCategory, LLMRequest, LLMResponse, ModelInfo, Usage
from rbxforge.core.tools import ToolCall, ToolDefinition


# Transient failures that are safe to retry. Anything else (400/401/403, ...)
# must fail fast without additional requests.
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_TRANSIENT_KEYWORDS = ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED")
_TRANSIENT_STATUS_PATTERN = re.compile(r"\b(?:429|500|502|503|504)\b")


def _error_status_code(exc: BaseException) -> int | None:
    """Best-effort extraction of an HTTP status from a provider exception.

    ``google-genai`` exposes ``code`` as an int on ``APIError`` while other
    wrappers use ``status_code``; both are inspected so transient failures are
    recognised even though the raw text differs between SDK versions.
    """
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _is_transient_error(exc: BaseException) -> bool:
    """Return True only for failures that are safe to retry (429/5xx + gRPC)."""
    status = _error_status_code(exc)
    if status is not None:
        return status in _TRANSIENT_STATUS_CODES
    text = str(exc)
    if any(keyword in text.upper() for keyword in _TRANSIENT_KEYWORDS):
        return True
    return bool(_TRANSIENT_STATUS_PATTERN.search(text))


def _extract_text(response) -> str:
    """Join text from ``response.candidates[*].content.parts[*].text``.

    ``response.text`` is intentionally avoided: the SDK raises a warning (and
    newer versions an error) when the response contains non-text parts such as
    function calls. Walking the parts explicitly keeps text-only responses
    working while tolerating empty/partial/malformed responses.
    """
    text_parts: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            text = getattr(part, "text", None)
            if isinstance(text, str) and text:
                text_parts.append(text)
    return "".join(text_parts)


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
            return LLMResponse(_extract_text(response), self.name, request.model or self.model, usage)
        except Exception as exc:
            raise ProviderError(
                str(exc), self.name, retryable=_is_transient_error(exc), status_code=_error_status_code(exc)
            ) from exc


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
        max_attempts = 3
        backoffs = [2, 4, 8]

        for attempt in range(max_attempts):
            try:
                models = getattr(client, "aio", client).models
                response = await models.generate_content(
                    model=request.model or self.model, contents=contents, config=config
                )
                calls: list[ToolCall] = []
                text_parts = []
                for candidate in getattr(response, "candidates", []) or []:
                    content = getattr(candidate, "content", None)
                    for part in getattr(content, "parts", []) or []:
                        text = getattr(part, "text", None)
                        if text:
                            text_parts.append(text)
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
                response_text = "".join(text_parts) if text_parts else ""
                return ToolModelResponse(text=response_text, tool_calls=calls)
            except Exception as exc:
                retryable = _is_transient_error(exc)
                if retryable and attempt < max_attempts - 1:
                    await asyncio.sleep(backoffs[attempt])
                    continue
                raise ProviderError(
                    str(exc), self.name, retryable=retryable, status_code=_error_status_code(exc)
                ) from exc

    async def health(self) -> bool:
        return bool(self.api_key or self.client)

    async def list_models(self) -> list[ModelInfo]:
        if not self.api_key and self.client is None:
            return []
        # Return Gemini models with capability detection and free/paid cost classification
        default_model = self.model or "gemini-2.5-flash"
        known_models = [
            ("gemini-2.5-flash", 95.0),
            ("gemini-2.0-flash", 90.0),
            ("gemini-1.5-pro", 85.0),
            ("gemini-1.5-flash", 80.0),
        ]
        models = [
            ModelInfo(
                name=name,
                provider=self.name,
                cost=CostCategory.FREE,
                supports_tools=True,
                score=score,
            )
            for name, score in known_models
        ]
        if default_model not in [m.name for m in models]:
            models.insert(0, ModelInfo(name=default_model, provider=self.name, cost=CostCategory.FREE, supports_tools=True, score=85.0))
        return models
