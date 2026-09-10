import os
from dataclasses import dataclass

from dotenv import load_dotenv

from .core.llm.models import TaskComplexity


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    gemini_api_key: str = ""
    gemini_model: str = ""
    default_complexity: TaskComplexity = TaskComplexity.MODERATE
    max_tool_calls: int = 12

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            ollama_base_url=os.getenv("RBXFORGE_OLLAMA_BASE_URL", cls.ollama_base_url),
            ollama_model=os.getenv("RBXFORGE_OLLAMA_MODEL", cls.ollama_model),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", ""),
            default_complexity=TaskComplexity(os.getenv("RBXFORGE_DEFAULT_COMPLEXITY", cls.default_complexity.value)),
            max_tool_calls=int(os.getenv("RBXFORGE_MAX_TOOL_CALLS", str(cls.max_tool_calls))),
        )
