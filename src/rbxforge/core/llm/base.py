from typing import Protocol, Any

from .models import LLMRequest, LLMResponse, ModelInfo


class LLMProvider(Protocol):
    name: str

    async def generate(self, request: LLMRequest) -> LLMResponse: ...
    async def health(self) -> bool: ...
    async def list_models(self) -> list[ModelInfo]: ...
