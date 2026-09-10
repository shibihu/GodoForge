from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from rbxforge.godot.runner import GodotRunner


def test_runner_invalid_project_root(tmp_path):
    runner = GodotRunner()
    result = runner.run(tmp_path)
    assert not result.success
    assert result.exit_code == 1
    assert "missing project.godot" in result.stderr


def test_runner_missing_executable(tmp_path):
    (tmp_path / "project.godot").touch()
    runner = GodotRunner(godot_path="non_existent_godot_executable_12345")
    result = runner.run(tmp_path)
    assert not result.success
    assert result.exit_code is None
    assert "Godot executable was not found" in result.stderr


@patch("subprocess.Popen")
def test_runner_success(mock_popen, tmp_path):
    (tmp_path / "project.godot").touch()
    process_mock = MagicMock()
    process_mock.communicate.return_value = ("Godot v4.2.1\n", "")
    process_mock.returncode = 0
    mock_popen.return_value = process_mock

    runner = GodotRunner(godot_path="godot")
    result = runner.run(tmp_path)

    assert result.success
    assert result.exit_code == 0
    assert "Godot v4.2.1" in result.stdout
    assert not result.timed_out


@patch("subprocess.Popen")
def test_runner_error(mock_popen, tmp_path):
    (tmp_path / "project.godot").touch()
    process_mock = MagicMock()
    process_mock.communicate.return_value = ("", "SCRIPT ERROR: Parse error in res://player.gd:10\n")
    process_mock.returncode = 1
    mock_popen.return_value = process_mock

    runner = GodotRunner(godot_path="godot")
    result = runner.run(tmp_path)

    assert not result.success
    assert result.exit_code == 1
    assert len(result.errors) == 1
    assert result.errors[0].file == "res://player.gd"
    assert result.errors[0].line == 10


@patch("subprocess.Popen")
def test_runner_timeout(mock_popen, tmp_path):
    import subprocess
    (tmp_path / "project.godot").touch()

    process_mock = MagicMock()
    process_mock.communicate.side_effect = [
        subprocess.TimeoutExpired(cmd="godot", timeout=1),
        ("stdout partially", "stderr partially"),
    ]
    mock_popen.return_value = process_mock

    runner = GodotRunner(godot_path="godot", timeout=1)
    result = runner.run(tmp_path)

    assert not result.success
    assert result.timed_out
    assert process_mock.kill.called


def test_runner_output_truncation():
    long_output = "a" * 25000
    truncated = GodotRunner.truncate_output(long_output)
    assert len(truncated) < 25000
    assert "... output truncated ..." in truncated
