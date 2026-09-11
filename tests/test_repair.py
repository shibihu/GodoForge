from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rbxforge.config import Settings
from rbxforge.core.llm.errors import ProviderError
from rbxforge.godot.models import GodotError, GodotRunResult
from rbxforge.main import run_check, run_repair


def _failing_result(message="SCRIPT ERROR: Identifier 'foo' not declared in res://player.gd:10", file="res://player.gd", line=10):
    return GodotRunResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr=message + "\n",
        duration_seconds=0.1,
        errors=[GodotError(message, file, line, severity="error")],
    )


def _passing_result():
    return GodotRunResult(success=True, exit_code=0, stdout="OK", stderr="", duration_seconds=0.1, errors=[])


def _patch(monkeypatch, runner, agent):
    monkeypatch.setattr("rbxforge.main.GodotRunner", lambda **kwargs: runner)
    monkeypatch.setattr("rbxforge.main.build_providers", lambda settings: {"gemini": MagicMock()})
    monkeypatch.setattr("rbxforge.main.run_agent", agent)


def test_run_check_success(tmp_path):
    (tmp_path / "project.godot").touch()
    settings = Settings(godot_path="godot")

    mock_runner = MagicMock()
    mock_runner.check_project.return_value = _passing_result()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("rbxforge.main.GodotRunner", lambda **kwargs: mock_runner)
        out = run_check(tmp_path, settings)
        assert "passed successfully" in out


def test_run_repair_success_without_repairs(tmp_path):
    (tmp_path / "project.godot").touch()
    settings = Settings(godot_path="godot")

    mock_runner = MagicMock()
    mock_runner.run_project.return_value = _passing_result()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("rbxforge.main.GodotRunner", lambda **kwargs: mock_runner)
        out = run_repair(tmp_path, settings)
        assert "No repairs needed" in out


def test_run_repair_stops_when_error_persists(tmp_path):
    (tmp_path / "project.godot").touch()
    settings = Settings(godot_path="godot", max_repair_attempts=3)

    mock_runner = MagicMock()
    mock_runner.run_project.return_value = _failing_result()

    fake_provider = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("rbxforge.main.GodotRunner", lambda **kwargs: mock_runner)
        mp.setattr("rbxforge.main.build_providers", lambda s: {"gemini": fake_provider})
        mp.setattr("rbxforge.main.run_agent", lambda *args, **kwargs: "tried fix")

        out = run_repair(tmp_path, settings, provider="gemini")
        assert "Repair stopped early" in out or "Repair limit reached" in out


# ---------------------------------------------------------------------------
# Provider failure semantics
# ---------------------------------------------------------------------------


def test_provider_failure_before_file_modification_reports_provider_error(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("[application]\n", encoding="utf-8")
    settings = Settings(godot_path="godot", max_repair_attempts=2)

    runner = MagicMock()
    runner.run_project.return_value = _failing_result()
    agent_calls = {"count": 0}

    def agent(project_root, prompt, provider, max_tool_calls, runner=None):
        agent_calls["count"] += 1
        raise ProviderError("503 UNAVAILABLE: model overloaded", "gemini", retryable=True, status_code=503)

    _patch(monkeypatch, runner, agent)

    out = run_repair(tmp_path, settings, provider="gemini")

    assert agent_calls["count"] == 1
    assert "AI provider failed" in out
    assert "503 UNAVAILABLE" in out
    assert "did not pass" in out
    assert "Project completed successfully" not in out
    # The provider error must be surfaced, not silently replaced by the Godot error.
    assert out.index("503 UNAVAILABLE") < out.index("SCRIPT ERROR")


def test_provider_failure_after_file_modification_does_not_claim_success(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("[application]\n", encoding="utf-8")
    settings = Settings(godot_path="godot", max_repair_attempts=2)

    runner = MagicMock()
    runner.run_project.return_value = _failing_result()

    def agent(project_root, prompt, provider, max_tool_calls, runner=None):
        (Path(project_root) / "main.gd").write_text("print('attempted')\n", encoding="utf-8")
        raise ProviderError("503 UNAVAILABLE: model overloaded", "gemini", retryable=True, status_code=503)

    _patch(monkeypatch, runner, agent)

    out = run_repair(tmp_path, settings, provider="gemini")

    assert "AI provider failed" in out
    assert "Project completed successfully" not in out
    assert "Godot verification passed" not in out


def test_provider_failure_after_file_modification_but_verification_passes_is_success(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("[application]\n", encoding="utf-8")
    settings = Settings(godot_path="godot", max_repair_attempts=2)

    runner = MagicMock()
    runner.run_project.side_effect = [_failing_result(), _passing_result()]

    def agent(project_root, prompt, provider, max_tool_calls, runner=None):
        (Path(project_root) / "main.gd").write_text("print('fixed')\n", encoding="utf-8")
        raise ProviderError("503 UNAVAILABLE: model overloaded", "gemini", retryable=True, status_code=503)

    _patch(monkeypatch, runner, agent)

    out = run_repair(tmp_path, settings, provider="gemini")

    assert "Godot verification passed" in out
    assert "Project completed successfully" in out
    assert "1 repair(s) performed and verified by Godot" in out


# ---------------------------------------------------------------------------
# Verification / counting semantics
# ---------------------------------------------------------------------------


def test_file_modification_alone_is_not_a_successful_repair(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("[application]\n", encoding="utf-8")
    settings = Settings(godot_path="godot", max_repair_attempts=2)

    runner = MagicMock()
    runner.run_project.return_value = _failing_result()
    attempts = {"count": 0}

    def agent(project_root, prompt, provider, max_tool_calls, runner=None):
        attempts["count"] += 1
        (Path(project_root) / "main.gd").write_text(f"print({attempts['count']})\n", encoding="utf-8")
        return "applied a change"

    _patch(monkeypatch, runner, agent)

    out = run_repair(tmp_path, settings, provider="gemini")

    assert "Godot verification passed" not in out
    assert "Project completed successfully" not in out
    assert "Repair stopped early" in out


def test_repair_limit_reached_when_errors_keep_changing(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("[application]\n", encoding="utf-8")
    settings = Settings(godot_path="godot", max_repair_attempts=2)

    runner = MagicMock()
    first = GodotRunResult(
        success=False, exit_code=1, stdout="", stderr="error A\n", duration_seconds=0.1,
        errors=[GodotError("error A", "res://a.gd", 1, severity="error")],
    )
    second = GodotRunResult(
        success=False, exit_code=1, stdout="", stderr="error B\n", duration_seconds=0.1,
        errors=[GodotError("error B", "res://b.gd", 2, severity="error")],
    )
    runner.run_project.side_effect = [first, second, second]
    attempts = {"count": 0}

    def agent(project_root, prompt, provider, max_tool_calls, runner=None):
        attempts["count"] += 1
        (Path(project_root) / "main.gd").write_text(f"print({attempts['count']})\n", encoding="utf-8")
        return "applied a change"

    _patch(monkeypatch, runner, agent)

    out = run_repair(tmp_path, settings, provider="gemini")

    assert attempts["count"] == settings.max_repair_attempts
    assert "Repair limit reached" in out
    assert "Project completed successfully" not in out


def test_unchanged_error_detected_even_when_output_formatting_differs(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text("[application]\n", encoding="utf-8")
    settings = Settings(godot_path="godot", max_repair_attempts=3)

    message = "SCRIPT ERROR: Identifier 'foo' not declared in res://main.gd:12"
    same_error = lambda: [GodotError(message, "res://main.gd", 12, severity="error")]
    first = GodotRunResult(
        success=False, exit_code=1, stdout="", stderr=f"{message}\n", duration_seconds=0.1,
        errors=same_error(),
    )
    second = GodotRunResult(
        success=False, exit_code=1, stdout="Godot Engine v4.7\nLoading project...\n",
        stderr=f"\n\n   {message}   \n", duration_seconds=0.2, errors=same_error(),
    )
    runner = MagicMock()
    runner.run_project.side_effect = [first, second, second]
    attempts = {"count": 0}

    def agent(project_root, prompt, provider, max_tool_calls, runner=None):
        attempts["count"] += 1
        return "tried a fix"

    _patch(monkeypatch, runner, agent)

    out = run_repair(tmp_path, settings, provider="gemini")

    assert attempts["count"] == 1
    assert "Repair stopped early" in out
    assert "Project completed successfully" not in out
