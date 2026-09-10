from collections.abc import Mapping

from .llm.base import LLMProvider
from .llm.errors import ProviderError
from .llm.models import LLMRequest, LLMResponse, TaskComplexity


class LLMRouter:
    ROUTES = {
        TaskComplexity.SIMPLE: ("ollama",),
        TaskComplexity.MODERATE: ("ollama", "gemini"),
        TaskComplexity.COMPLEX: ("gemini", "ollama"),
    }

    def __init__(self, providers: Mapping[str, LLMProvider]):
        self.providers = dict(providers)

    async def generate(self, request: LLMRequest, complexity: TaskComplexity, provider: str | None = None) -> LLMResponse:
        candidates = (provider,) if provider else self.ROUTES[complexity]
        last_error: ProviderError | None = None
        for name in candidates:
            selected = self.providers.get(name)
            if selected is None:
                last_error = ProviderError(f"Provider is not configured: {name}", name, retryable=True)
                continue
            try:
                return await selected.generate(request)
            except ProviderError as exc:
                if not exc.retryable:
                    raise
                last_error = exc
        if last_error:
            raise last_error
        raise ProviderError("No LLM provider is available", "router")
