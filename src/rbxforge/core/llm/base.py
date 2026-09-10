from typing import Protocol

from .models import LLMRequest, LLMResponse


class LLMProvider(Protocol):
    name: str

    async def generate(self, request: LLMRequest) -> LLMResponse: ...
    async def health(self) -> bool: ...
