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
    godot_path: str = "godot"
    godot_timeout: int = 30
    max_repair_attempts: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        try:
            max_tool_calls = int(os.getenv("RBXFORGE_MAX_TOOL_CALLS", str(cls.max_tool_calls)))
        except ValueError as exc:
            raise ValueError(f"Invalid RBXFORGE_MAX_TOOL_CALLS: {exc}") from exc

        try:
            godot_timeout = int(os.getenv("GODOFORGE_GODOT_TIMEOUT", str(cls.godot_timeout)))
            if godot_timeout <= 0:
                raise ValueError("timeout must be positive")
        except ValueError as exc:
            raise ValueError(f"Invalid GODOFORGE_GODOT_TIMEOUT: {exc}") from exc

        try:
            max_repair_attempts = int(os.getenv("GODOFORGE_MAX_REPAIR_ATTEMPTS", str(cls.max_repair_attempts)))
            if max_repair_attempts <= 0:
                raise ValueError("max_repair_attempts must be positive")
        except ValueError as exc:
            raise ValueError(f"Invalid GODOFORGE_MAX_REPAIR_ATTEMPTS: {exc}") from exc

        return cls(
            ollama_base_url=os.getenv("RBXFORGE_OLLAMA_BASE_URL", cls.ollama_base_url),
            ollama_model=os.getenv("RBXFORGE_OLLAMA_MODEL", cls.ollama_model),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", ""),
            default_complexity=TaskComplexity(os.getenv("RBXFORGE_DEFAULT_COMPLEXITY", cls.default_complexity.value)),
            max_tool_calls=max_tool_calls,
            godot_path=os.getenv("GODOFORGE_GODOT_PATH", cls.godot_path),
            godot_timeout=godot_timeout,
            max_repair_attempts=max_repair_attempts,
        )
