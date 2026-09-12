from __future__ import annotations

import asyncio
from typing import Mapping

from rbxforge.config import Settings
from rbxforge.core.llm.base import LLMProvider
from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import CostCategory, LLMRequest, LLMResponse, ModelInfo, TaskComplexity
from rbxforge.core.tools import ToolDefinition


class ProviderHub:
    """Central provider hub managing discovery, cost filtering, ranking, auto selection, and safe fallback."""

    def __init__(self, providers: Mapping[str, LLMProvider], settings: Settings):
        self.providers = dict(providers)
        self.settings = settings

    async def list_models(self) -> list[ModelInfo]:
        """Discover models across all active providers."""
        all_models: list[ModelInfo] = []
        for name, provider in self.providers.items():
            try:
                models = await provider.list_models()
                all_models.extend(models)
            except Exception:
                continue
        return all_models

    def filter_models(self, models: list[ModelInfo], require_tools: bool = False) -> list[ModelInfo]:
        """Filter models based on cost settings (RBXFORGE_ALLOW_PAID_MODELS) and tool requirements."""
        filtered = []
        for model in models:
            if not self.settings.allow_paid_models and model.cost == CostCategory.PAID:
                continue
            if require_tools and not model.supports_tools:
                continue
            filtered.append(model)
        return filtered

    def rank_models(self, models: list[ModelInfo]) -> list[ModelInfo]:
        """Rank models by score (descending) and free cost priority."""
        def key(m: ModelInfo):
            cost_priority = 0 if m.cost == CostCategory.FREE else (1 if m.cost == CostCategory.UNKNOWN else 2)
            return (-m.score, cost_priority, m.name)

        return sorted(models, key=key)

    async def select_best_model(self, require_tools: bool = False) -> tuple[LLMProvider, str] | None:
        """Select the best available provider and model based on capabilities, cost, and health."""
        # Provider precedence for auto mode if model list discovery is empty/limited
        preference_order = ["gemini", "groq", "openrouter", "ollama"]

        discovered = await self.list_models()
        eligible = self.filter_models(discovered, require_tools=require_tools)
        ranked = self.rank_models(eligible)

        for model_info in ranked:
            provider = self.providers.get(model_info.provider)
            if provider:
                try:
                    if await provider.health():
                        return provider, model_info.name
                except Exception:
                    continue

        # Fallback to configured default model of healthy provider by precedence
        for name in preference_order:
            provider = self.providers.get(name)
            if provider:
                try:
                    if await provider.health():
                        default_model = getattr(provider, "model", "") or ""
                        return provider, default_model
                except Exception:
                    continue

        return None

    async def generate(
        self,
        request: LLMRequest,
        complexity: TaskComplexity = TaskComplexity.MODERATE,
        provider: str | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """Generate response with provider/model selection and safe fallback across providers."""
        candidates: list[tuple[LLMProvider, str | None]] = []

        if provider == "auto" or provider is None:
            best = await self.select_best_model(require_tools=False)
            if best:
                candidates.append((best[0], model or best[1]))
            # Fallback candidates order
            for name in ["gemini", "groq", "openrouter", "ollama"]:
                p = self.providers.get(name)
                if p and (not candidates or p.name != candidates[0][0].name):
                    candidates.append((p, model or getattr(p, "model", None)))
        else:
            p = self.providers.get(provider)
            if p is None:
                raise ProviderError(f"Provider is not configured: {provider}", provider or "hub")
            candidates.append((p, model or getattr(p, "model", None)))
            # Add remaining providers as fallback
            for name in ["gemini", "groq", "openrouter", "ollama"]:
                other = self.providers.get(name)
                if other and other.name != p.name:
                    candidates.append((other, getattr(other, "model", None)))

        last_error: Exception | None = None
        for prov, mod in candidates:
            req = LLMRequest(
                messages=request.messages,
                model=mod or request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
            try:
                return await prov.generate(req)
            except ProviderError as exc:
                if not exc.retryable and provider is not None and provider != "auto":
                    raise
                last_error = exc
            except Exception as exc:
                last_error = exc

        if last_error:
            if isinstance(last_error, ProviderError):
                raise last_error
            raise ProviderError(str(last_error), "hub")
        raise ProviderError("No LLM provider is available", "hub")

    async def generate_with_tools(
        self,
        request: LLMRequest,
        tools: list[ToolDefinition],
        provider: str | None = None,
        model: str | None = None,
    ):
        """Generate response using function/tool calling with provider/model selection and safe fallback."""
        candidates: list[tuple[LLMProvider, str | None]] = []

        if provider == "auto" or provider is None:
            best = await self.select_best_model(require_tools=True)
            if best:
                candidates.append((best[0], model or best[1]))
            for name in ["gemini", "groq", "openrouter", "ollama"]:
                p = self.providers.get(name)
                if p and hasattr(p, "generate_with_tools") and (not candidates or p.name != candidates[0][0].name):
                    candidates.append((p, model or getattr(p, "model", None)))
        else:
            p = self.providers.get(provider)
            if p is None:
                raise ProviderError(f"Provider is not configured: {provider}", provider or "hub")
            if not hasattr(p, "generate_with_tools"):
                raise ProviderError(f"Provider {provider} does not support tool calling", provider)
            candidates.append((p, model or getattr(p, "model", None)))
            for name in ["gemini", "groq", "openrouter", "ollama"]:
                other = self.providers.get(name)
                if other and hasattr(other, "generate_with_tools") and other.name != p.name:
                    candidates.append((other, getattr(other, "model", None)))

        last_error: Exception | None = None
        for prov, mod in candidates:
            req = LLMRequest(
                messages=request.messages,
                model=mod or request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
            try:
                return await prov.generate_with_tools(req, tools)
            except ProviderError as exc:
                if not exc.retryable and provider is not None and provider != "auto":
                    raise
                last_error = exc
            except Exception as exc:
                last_error = exc

        if last_error:
            if isinstance(last_error, ProviderError):
                raise last_error
            raise ProviderError(str(last_error), "hub")
        raise ProviderError("No LLM provider with tool capability is available", "hub")
