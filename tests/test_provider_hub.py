from unittest.mock import AsyncMock, MagicMock

import pytest

from rbxforge.config import Settings
from rbxforge.core.llm.models import CostCategory, LLMRequest, LLMResponse, Message, ModelInfo
from rbxforge.providers.groq.provider import GroqProvider
from rbxforge.providers.hub import ProviderHub
from rbxforge.providers.openrouter.provider import OpenRouterProvider


@pytest.mark.asyncio
async def test_groq_provider_list_models():
    client = MagicMock()
    client.get = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "data": [
            {"id": "llama-3.3-70b-versatile"},
            {"id": "mixtral-8x7b-32768"},
        ]
    }
    client.get.return_value = mock_resp

    provider = GroqProvider(api_key="gsk_test", client=client)
    models = await provider.list_models()

    assert len(models) == 2
    assert models[0].name == "llama-3.3-70b-versatile"
    assert models[0].cost == CostCategory.FREE
    assert models[0].supports_tools is True


@pytest.mark.asyncio
async def test_openrouter_provider_list_models():
    client = MagicMock()
    client.get = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "data": [
            {
                "id": "meta-llama/llama-3.3-70b-instruct:free",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["tools"],
            },
            {
                "id": "openai/gpt-4o",
                "pricing": {"prompt": "0.000005", "completion": "0.000015"},
                "supported_parameters": ["tools"],
            },
        ]
    }
    client.get.return_value = mock_resp

    provider = OpenRouterProvider(api_key="sk-or-test", client=client)
    models = await provider.list_models()

    assert len(models) == 2
    assert models[0].cost == CostCategory.FREE
    assert models[1].cost == CostCategory.PAID


@pytest.mark.asyncio
async def test_provider_hub_cost_filtering():
    settings_no_paid = Settings(allow_paid_models=False)

    p_gemini = AsyncMock()
    p_gemini.name = "gemini"
    p_gemini.list_models.return_value = [
        ModelInfo("gemini-2.5-flash", "gemini", CostCategory.FREE, True, 95.0)
    ]

    p_openrouter = AsyncMock()
    p_openrouter.name = "openrouter"
    p_openrouter.list_models.return_value = [
        ModelInfo("openai/gpt-4o", "openrouter", CostCategory.PAID, True, 99.0)
    ]

    hub = ProviderHub({"gemini": p_gemini, "openrouter": p_openrouter}, settings_no_paid)
    discovered = await hub.list_models()
    filtered = hub.filter_models(discovered)

    assert len(filtered) == 1
    assert filtered[0].name == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_provider_hub_select_best_model_and_auto_generate():
    settings = Settings(allow_paid_models=False)

    p_gemini = AsyncMock()
    p_gemini.name = "gemini"
    p_gemini.health.return_value = True
    p_gemini.list_models.return_value = [
        ModelInfo("gemini-2.5-flash", "gemini", CostCategory.FREE, True, 95.0)
    ]
    p_gemini.generate.return_value = LLMResponse("hello from gemini", "gemini", "gemini-2.5-flash")

    hub = ProviderHub({"gemini": p_gemini}, settings)
    res = await hub.generate(LLMRequest([Message("user", "hi")]), provider="auto")

    assert res.text == "hello from gemini"
    assert res.provider == "gemini"
