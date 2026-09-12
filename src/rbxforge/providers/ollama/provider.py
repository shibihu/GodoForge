import json
import httpx

from rbxforge.core.agent import ToolModelResponse
from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import CostCategory, LLMRequest, LLMResponse, ModelInfo, Usage
from rbxforge.core.tools import ToolCall, ToolDefinition


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3:4b",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        connect_timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client
        self.timeout = httpx.Timeout(timeout, connect=connect_timeout)

    def _handle_exception(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, httpx.TimeoutException):
            return ProviderError(f"Ollama request timed out: {exc}", self.name, retryable=True)
        if isinstance(exc, httpx.ConnectError):
            return ProviderError(f"Cannot connect to Ollama server at {self.base_url}: {exc}", self.name, retryable=True)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            retryable = status in (429, 500, 502, 503, 504)
            return ProviderError(f"Ollama HTTP error {status}: {exc.response.text}", self.name, retryable=retryable, status_code=status)
        if isinstance(exc, (httpx.HTTPError, json.JSONDecodeError)):
            return ProviderError(f"Ollama error: {exc}", self.name, retryable=True)
        return ProviderError(f"Unexpected Ollama error: {exc}", self.name, retryable=False)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model or self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "options": {"temperature": request.temperature},
        }
        if request.max_tokens is not None:
            payload["options"]["num_predict"] = request.max_tokens
        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            if response.status_code >= 400:
                retryable = response.status_code in (429, 500, 502, 503, 504)
                raise ProviderError(response.text, self.name, retryable, response.status_code)
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Malformed JSON response from Ollama: {exc}", self.name, retryable=True) from exc
            if not isinstance(data, dict):
                raise ProviderError("Invalid response format from Ollama", self.name, retryable=True)
            msg = data.get("message") or {}
            content = msg.get("content") or "" if isinstance(msg, dict) else ""
            return LLMResponse(
                text=content,
                provider=self.name,
                model=data.get("model", payload["model"]),
                usage=Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0)),
            )
        except Exception as exc:
            raise self._handle_exception(exc) from exc
        finally:
            if self.client is None:
                await client.aclose()

    async def _check_model_tool_support(self, client: httpx.AsyncClient, model_name: str) -> bool:
        """Inspect model metadata via Ollama /api/show, falling back to name heuristics."""
        tool_keywords = {"qwen", "llama", "mistral", "command-r", "firefunction", "granite", "smollm", "hermes", "nemotron"}
        lower_name = model_name.lower()
        heuristic = any(kw in lower_name for kw in tool_keywords)

        try:
            show_resp = await client.post(f"{self.base_url}/api/show", json={"name": model_name})
            if show_resp.is_success:
                info = show_resp.json()
                template = str(info.get("template") or "").lower()
                system = str(info.get("system") or "").lower()
                details = info.get("details") or {}
                families = [str(f).lower() for f in (details.get("families") or [])]
                family = str(details.get("family") or "").lower()

                if "tools" in template or ".tool_calls" in template or "tool_call" in template or "tools" in system:
                    return True
                if any(kw in family for kw in tool_keywords) or any(kw in f for f in families for kw in tool_keywords):
                    return True
        except Exception:
            pass

        return heuristic

    async def list_models(self) -> list[ModelInfo]:
        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.get(f"{self.base_url}/api/tags")
            if not response.is_success:
                return []
            data = response.json()
            models = []
            for item in data.get("models", []):
                name = item.get("name", "")
                if name:
                    supports_tools = await self._check_model_tool_support(client, name)
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
        except Exception:
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

        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            if response.status_code >= 400:
                retryable = response.status_code in (429, 500, 502, 503, 504)
                raise ProviderError(response.text, self.name, retryable, response.status_code)
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Malformed JSON response from Ollama: {exc}", self.name, retryable=True) from exc

            if not isinstance(data, dict):
                raise ProviderError("Invalid response format from Ollama", self.name, retryable=True)

            message = data.get("message") or {}
            if not isinstance(message, dict):
                message = {}
            content = message.get("content") or ""

            tool_calls = []
            tc_list = message.get("tool_calls")
            if isinstance(tc_list, list):
                for tc in tc_list:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function") or {}
                    if not isinstance(fn, dict):
                        fn = {}
                    fn_name = fn.get("name") or ""
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    if not isinstance(args, dict):
                        args = {}
                    tool_calls.append(ToolCall(fn_name, args, tc.get("id")))

            return ToolModelResponse(text=content, tool_calls=tool_calls)
        except Exception as exc:
            raise self._handle_exception(exc) from exc
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
