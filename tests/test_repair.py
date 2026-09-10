from unittest.mock import MagicMock
import pytest

from rbxforge.config import Settings
from rbxforge.godot.models import GodotError, GodotRunResult
from rbxforge.main import run_check, run_repair


def test_run_check_success(tmp_path):
    (tmp_path / "project.godot").touch()
    settings = Settings(godot_path="godot")

    mock_runner = MagicMock()
    mock_runner.run.return_value = GodotRunResult(
        success=True, exit_code=0, stdout="OK", stderr="", duration_seconds=0.1
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("rbxforge.main.GodotRunner", lambda **kwargs: mock_runner)
        out = run_check(tmp_path, settings)
        assert "passed successfully" in out


def test_run_repair_success_without_repairs(tmp_path):
    (tmp_path / "project.godot").touch()
    settings = Settings(godot_path="godot")

    mock_runner = MagicMock()
    mock_runner.run.return_value = GodotRunResult(
        success=True, exit_code=0, stdout="OK", stderr="", duration_seconds=0.1
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("rbxforge.main.GodotRunner", lambda **kwargs: mock_runner)
        out = run_repair(tmp_path, settings)
        assert "No repairs needed" in out


def test_run_repair_stops_when_error_persists(tmp_path):
    (tmp_path / "project.godot").touch()
    settings = Settings(godot_path="godot", max_repair_attempts=3)

    mock_runner = MagicMock()
    mock_runner.run.return_value = GodotRunResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr="SCRIPT ERROR in res://player.gd:10",
        duration_seconds=0.1,
        errors=[GodotError("error", "res://player.gd", 10, severity="error")]
    )

    fake_provider = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("rbxforge.main.GodotRunner", lambda **kwargs: mock_runner)
        mp.setattr("rbxforge.main.build_providers", lambda s: {"gemini": fake_provider})
        mp.setattr("rbxforge.main.run_agent", lambda *args, **kwargs: "tried fix")

        out = run_repair(tmp_path, settings, provider="gemini")
        assert "Repair stopped early" in out or "Repair limit reached" in out
