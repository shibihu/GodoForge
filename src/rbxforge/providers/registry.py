from rbxforge.config import Settings
from .ollama.provider import OllamaProvider
from .gemini.provider import GeminiProvider
from .groq.provider import GroqProvider
from .openrouter.provider import OpenRouterProvider


def build_providers(settings: Settings):
    providers = {
        "ollama": OllamaProvider(
            settings.ollama_base_url,
            settings.ollama_model,
            timeout=settings.llm_timeout,
            connect_timeout=settings.llm_connect_timeout,
        )
    }
    if settings.gemini_api_key:
        providers["gemini"] = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if settings.groq_api_key:
        providers["groq"] = GroqProvider(
            settings.groq_api_key,
            settings.groq_model,
            timeout=settings.llm_timeout,
            connect_timeout=settings.llm_connect_timeout,
        )
    if settings.openrouter_api_key:
        providers["openrouter"] = OpenRouterProvider(
            settings.openrouter_api_key,
            settings.openrouter_model,
            timeout=settings.llm_timeout,
            connect_timeout=settings.llm_connect_timeout,
        )
    return providers
