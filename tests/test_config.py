from rbxforge.config import Settings
from rbxforge.core.llm.models import TaskComplexity


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("RBXFORGE_OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setenv("RBXFORGE_DEFAULT_COMPLEXITY", "complex")

    settings = Settings.from_env()

    assert settings.ollama_model == "qwen3:8b"
    assert settings.gemini_api_key == "secret"
    assert settings.gemini_model == "gemini-test"
    assert settings.default_complexity is TaskComplexity.COMPLEX
