from rbxforge.config import Settings
from .ollama.provider import OllamaProvider
from .gemini.provider import GeminiProvider


def build_providers(settings: Settings):
    providers = {"ollama": OllamaProvider(settings.ollama_base_url, settings.ollama_model)}
    if settings.gemini_api_key and settings.gemini_model:
        providers["gemini"] = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    return providers
