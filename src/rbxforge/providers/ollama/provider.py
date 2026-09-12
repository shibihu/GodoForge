import json
import httpx

from rbxforge.core.agent import ToolModelResponse
from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import CostCategory, LLMRequest, LLMResponse, ModelInfo, Usage
from rbxforge.core.tools import ToolCall, ToolDefinition


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "qwen3:4b", client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model or self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "options": {"temperature": request.temperature},
        }
        if request.max_tokens is not None:
            payload["options"]["num_predict"] = request.max_tokens
        client = self.client or httpx.AsyncClient(timeout=60)
        try:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            if response.status_code >= 400:
                raise ProviderError(response.text, self.name, response.status_code == 429 or response.status_code >= 500, response.status_code)
            data = response.json()
            return LLMResponse(
                text=data.get("message", {}).get("content", ""),
                provider=self.name,
                model=data.get("model", payload["model"]),
                usage=Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0)),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc), self.name, retryable=True) from exc
        finally:
            if self.client is None:
                await client.aclose()

    async def list_models(self) -> list[ModelInfo]:
        client = self.client or httpx.AsyncClient(timeout=10)
        try:
            response = await client.get(f"{self.base_url}/api/tags")
            if not response.is_success:
                return []
            data = response.json()
            models = []
            tool_keywords = {"qwen", "llama", "mistral", "command-r", "firefunction", "granite", "smollm", "hermes", "nemotron"}
            for item in data.get("models", []):
                name = item.get("name", "")
                if name:
                    lower_name = name.lower()
                    supports_tools = any(kw in lower_name for kw in tool_keywords)
                    score = 80.0 if supports_tools else 60.0
                    models.append(
                        ModelInfo(
                            name=name,
                            provider=self.name,
                            cost=CostCategory.FREE,
                            supports_tools=supports_tools,
                            score=score,
                        )
                    )
            return models
        except httpx.HTTPError:
            return []
        finally:
            if self.client is None:
                await client.aclose()

    async def generate_with_tools(self, request: LLMRequest, tools: list[ToolDefinition]) -> ToolModelResponse:
        model = request.model or self.model
        formatted_messages = []
        for m in request.messages:
            if m.role == "tool":
                try:
                    parsed = json.loads(m.content)
                    resp = parsed.get("__rbxforge_function_response__", {})
                    formatted_messages.append({
                        "role": "tool",
                        "content": json.dumps({"ok": resp.get("ok"), "data": resp.get("data"), "error": resp.get("error")}),
                    })
                except Exception:
                    formatted_messages.append({"role": "user", "content": m.content})
            elif m.role == "model":
                try:
                    parsed = json.loads(m.content)
                    calls = parsed.get("__rbxforge_function_calls__")
                    if calls:
                        tool_calls = [
                            {
                                "function": {"name": c["name"], "arguments": c.get("args", {})},
                            }
                            for c in calls
                        ]
                        formatted_messages.append({"role": "assistant", "tool_calls": tool_calls, "content": ""})
                    else:
                        formatted_messages.append({"role": "assistant", "content": m.content})
                except Exception:
                    formatted_messages.append({"role": "assistant", "content": m.content})
            else:
                formatted_messages.append({"role": m.role if m.role != "model" else "assistant", "content": m.content})

        ollama_tools = [
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
            "tools": ollama_tools,
            "stream": False,
            "options": {"temperature": request.temperature},
        }
        if request.max_tokens is not None:
            payload["options"]["num_predict"] = request.max_tokens

        client = self.client or httpx.AsyncClient(timeout=60)
        try:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            if response.status_code >= 400:
                raise ProviderError(response.text, self.name, response.status_code in (429, 500, 502, 503, 504), response.status_code)
            data = response.json()
            message = data.get("message", {})
            content = message.get("content") or ""

            tool_calls = []
            for tc in message.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                elif not isinstance(args, dict):
                    args = {}
                tool_calls.append(ToolCall(fn.get("name", ""), args, tc.get("id")))

            return ToolModelResponse(text=content, tool_calls=tool_calls)
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc), self.name, retryable=True) from exc
        finally:
            if self.client is None:
                await client.aclose()

    async def health(self) -> bool:
        client = self.client or httpx.AsyncClient(timeout=10)
        try:
            response = await client.get(f"{self.base_url}/api/tags")
            return response.is_success
        except httpx.HTTPError:
            return False
        finally:
            if self.client is None:
                await client.aclose()
