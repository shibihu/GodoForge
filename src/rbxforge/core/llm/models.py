from dataclasses import dataclass
from enum import Enum


class TaskComplexity(str, Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class CostCategory(str, Enum):
    FREE = "free"
    PAID = "paid"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ModelInfo:
    name: str
    provider: str
    cost: CostCategory = CostCategory.UNKNOWN
    supports_tools: bool = False
    score: float = 0.0


@dataclass(frozen=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True)
class LLMRequest:
    messages: list[Message]
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int | None = None


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    usage: Usage | None = None
