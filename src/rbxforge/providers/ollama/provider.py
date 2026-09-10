import httpx

from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import LLMRequest, LLMResponse, Usage


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
