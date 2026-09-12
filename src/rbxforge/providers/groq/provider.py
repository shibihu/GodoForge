import httpx

from rbxforge.core.agent import ToolModelResponse
from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import CostCategory, LLMRequest, LLMResponse, ModelInfo, Usage
from rbxforge.core.tools import ToolCall, ToolDefinition


class GroqProvider:
    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str = "",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        connect_timeout: float = 10.0,
    ):
        self.api_key = api_key
        self.model = model
        self.client = client
        self.timeout = httpx.Timeout(timeout, connect=connect_timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ProviderError("Groq API key is not configured", self.name)
        model = request.model or self.model or "llama-3.3-70b-versatile"
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            if response.status_code >= 400:
                raise ProviderError(
                    response.text,
                    self.name,
                    retryable=response.status_code in (429, 500, 502, 503, 504),
                    status_code=response.status_code,
                )
            data = response.json()
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content") or ""
            usage_data = data.get("usage", {})
            usage = Usage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
            )
            return LLMResponse(text=content, provider=self.name, model=data.get("model", model), usage=usage)
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc), self.name, retryable=True) from exc
        finally:
            if self.client is None:
                await client.aclose()

    async def generate_with_tools(self, request: LLMRequest, tools: list[ToolDefinition]) -> ToolModelResponse:
        if not self.api_key:
            raise ProviderError("Groq API key is not configured", self.name)
        model = request.model or self.model or "llama-3.3-70b-versatile"

        formatted_messages = []
        for m in request.messages:
            if m.role == "tool":
                # Convert rbxforge tool response JSON to OpenAI tool message
                try:
                    import json
                    parsed = json.loads(m.content)
                    resp = parsed.get("__rbxforge_function_response__", {})
                    formatted_messages.append({
                        "role": "tool",
                        "tool_call_id": resp.get("id") or "call_0",
                        "content": json.dumps({"ok": resp.get("ok"), "data": resp.get("data"), "error": resp.get("error")}),
                    })
                except Exception:
                    formatted_messages.append({"role": "user", "content": m.content})
            elif m.role == "model":
                try:
                    import json
                    parsed = json.loads(m.content)
                    calls = parsed.get("__rbxforge_function_calls__")
                    if calls:
                        tool_calls = [
                            {
                                "id": c.get("id") or "call_0",
                                "type": "function",
                                "function": {"name": c["name"], "arguments": json.dumps(c.get("args", {}))},
                            }
                            for c in calls
                        ]
                        formatted_messages.append({"role": "assistant", "tool_calls": tool_calls, "content": None})
                    else:
                        formatted_messages.append({"role": "assistant", "content": m.content})
                except Exception:
                    formatted_messages.append({"role": "assistant", "content": m.content})
            else:
                formatted_messages.append({"role": m.role if m.role != "model" else "assistant", "content": m.content})

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

        payload = {
            "model": model,
            "messages": formatted_messages,
            "tools": openai_tools,
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        client = self.client or httpx.AsyncClient(timeout=60)
        try:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            if response.status_code >= 400:
                raise ProviderError(
                    response.text,
                    self.name,
                    retryable=response.status_code in (429, 500, 502, 503, 504),
                    status_code=response.status_code,
                )
            data = response.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content") or ""

            tool_calls = []
            for tc in message.get("tool_calls", []):
                import json
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                tool_calls.append(ToolCall(fn.get("name", ""), args, tc.get("id")))

            return ToolModelResponse(text=content, tool_calls=tool_calls)
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc), self.name, retryable=True) from exc
        finally:
            if self.client is None:
                await client.aclose()

    async def health(self) -> bool:
        if not self.api_key:
            return False
        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.get("https://api.groq.com/openai/v1/models", headers=self._headers())
            return response.is_success
        except httpx.HTTPError:
            return False
        finally:
            if self.client is None:
                await client.aclose()

    async def list_models(self) -> list[ModelInfo]:
        if not self.api_key:
            return []
        client = self.client or httpx.AsyncClient(timeout=10)
        try:
            response = await client.get("https://api.groq.com/openai/v1/models", headers=self._headers())
            if not response.is_success:
                return []
            data = response.json()
            models = []
            for m in data.get("data", []):
                m_id = m.get("id", "")
                if m_id:
                    # Groq API access is free tier/free models for supported endpoints
                    models.append(
                        ModelInfo(
                            name=m_id,
                            provider=self.name,
                            cost=CostCategory.FREE,
                            supports_tools=True,
                            score=85.0 if "70b" in m_id or "llama-3.3" in m_id else 70.0,
                        )
                    )
            return models
        except httpx.HTTPError:
            return []
        finally:
            if self.client is None:
                await client.aclose()
