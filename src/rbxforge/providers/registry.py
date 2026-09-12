from rbxforge.config import Settings
from .ollama.provider import OllamaProvider
from .gemini.provider import GeminiProvider
from .groq.provider import GroqProvider
from .openrouter.provider import OpenRouterProvider


def build_providers(settings: Settings):
    providers = {"ollama": OllamaProvider(settings.ollama_base_url, settings.ollama_model)}
    if settings.gemini_api_key:
        providers["gemini"] = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if settings.groq_api_key:
        providers["groq"] = GroqProvider(settings.groq_api_key, settings.groq_model)
    if settings.openrouter_api_key:
        providers["openrouter"] = OpenRouterProvider(settings.openrouter_api_key, settings.openrouter_model)
    return providers
