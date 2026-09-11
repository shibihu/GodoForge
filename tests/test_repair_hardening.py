from unittest.mock import MagicMock
import pytest

from rbxforge.config import Settings
from rbxforge.core.llm.errors import ProviderError
from rbxforge.core.llm.models import LLMRequest, Message
from rbxforge.godot.models import GodotError, GodotRunResult
from rbxforge.main import run_repair
from rbxforge.providers.gemini.provider import GeminiProvider


@pytest.mark.asyncio
async def test_gemini_generate_retries_on_503():
    client = MagicMock()
    mock_models = MagicMock()
    client.aio.models = mock_models

    call_count = 0

    async def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            exc = Exception("503 Service Unavailable")
            exc.status_code = 503
            raise exc

        class FakePart:
            text = "success text"

        class FakeContent:
            parts = [FakePart()]

        class FakeCandidate:
            content = FakeContent()

        class FakeResponse:
            candidates = [FakeCandidate()]

        return FakeResponse()

    mock_models.generate_content = mock_generate

    provider = GeminiProvider("key", "gemini-test", client=client)
    res = await provider.generate(LLMRequest([Message("user", "test")]))

    assert call_count == 2
    assert res.text == "success text"


def test_repair_provider_failure_does_not_claim_success(tmp_path):
    (tmp_path / "project.godot").touch()
    (tmp_path / "main.gd").write_text("print(undefined_variable)\n", encoding="utf-8")
    settings = Settings(godot_path="godot", max_repair_attempts=2)

    mock_runner = MagicMock()
    # Initial run fails
    mock_runner.run_project.return_value = GodotRunResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr="SCRIPT ERROR in res://main.gd:1",
        duration_seconds=0.1,
        errors=[GodotError("error", "res://main.gd", 1, severity="error")],
    )

    fake_provider = MagicMock()

    def mock_run_agent(*args, **kwargs):
        # AI modifies main.gd but then provider raises ProviderError
        (tmp_path / "main.gd").write_text("print('fixed')\n", encoding="utf-8")
        raise ProviderError("503 Service Unavailable", "gemini")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("rbxforge.main.GodotRunner", lambda **kwargs: mock_runner)
        mp.setattr("rbxforge.main.build_providers", lambda s: {"gemini": fake_provider})
        mp.setattr("rbxforge.main.run_agent", mock_run_agent)

        out = run_repair(tmp_path, settings, provider="gemini")
        assert "Gemini API error" in out or "AI provider failed" in out
        assert "✓ Project completed successfully" not in out
