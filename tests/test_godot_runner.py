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


@patch("selectors.DefaultSelector")
@patch("subprocess.Popen")
def test_runner_success(mock_popen, mock_selector_cls, tmp_path):
    (tmp_path / "project.godot").touch()

    stdout_mock = MagicMock()
    stdout_mock.readline.side_effect = ["Godot v4.2.1\n", ""]
    stdout_mock.read.return_value = ""

    stderr_mock = MagicMock()
    stderr_mock.readline.side_effect = [""]
    stderr_mock.read.return_value = ""

    process_mock = MagicMock()
    process_mock.stdout = stdout_mock
    process_mock.stderr = stderr_mock
    process_mock.poll.side_effect = [None, 0]
    process_mock.returncode = 0
    mock_popen.return_value = process_mock

    selector_mock = MagicMock()
    key_stdout = MagicMock()
    key_stdout.data = "stdout"
    key_stdout.fileobj = stdout_mock

    key_stderr = MagicMock()
    key_stderr.data = "stderr"
    key_stderr.fileobj = stderr_mock

    selector_mock.get_map.side_effect = [
        {1: key_stdout, 2: key_stderr},
        {1: key_stdout, 2: key_stderr},
        {},
    ]
    selector_mock.select.return_value = [(key_stdout, None)]
    mock_selector_cls.return_value = selector_mock

    runner = GodotRunner(godot_path="godot")
    result = runner.run(tmp_path)

    assert result.success
    assert result.exit_code == 0
    assert "Godot v4.2.1" in result.stdout
    assert not result.timed_out


@patch("selectors.DefaultSelector")
@patch("subprocess.Popen")
def test_runner_error(mock_popen, mock_selector_cls, tmp_path):
    (tmp_path / "project.godot").touch()

    stdout_mock = MagicMock()
    stdout_mock.readline.side_effect = [""]
    stdout_mock.read.return_value = ""

    stderr_mock = MagicMock()
    stderr_mock.readline.side_effect = ["SCRIPT ERROR: Parse error in res://player.gd:10\n", ""]
    stderr_mock.read.return_value = ""

    process_mock = MagicMock()
    process_mock.stdout = stdout_mock
    process_mock.stderr = stderr_mock
    process_mock.poll.return_value = 1
    process_mock.returncode = 1
    mock_popen.return_value = process_mock

    selector_mock = MagicMock()
    key_stderr = MagicMock()
    key_stderr.data = "stderr"
    key_stderr.fileobj = stderr_mock

    selector_mock.get_map.side_effect = [
        {2: key_stderr},
        {},
    ]
    selector_mock.select.return_value = [(key_stderr, None)]
    mock_selector_cls.return_value = selector_mock

    runner = GodotRunner(godot_path="godot")
    result = runner.run(tmp_path)

    assert not result.success
    assert result.exit_code == 1
    assert len(result.errors) == 1
    assert result.errors[0].file == "res://player.gd"
    assert result.errors[0].line == 10


def test_runner_output_truncation():
    long_output = "a" * 25000
    runner = GodotRunner()
    truncated = runner.truncate_output(long_output)
    assert len(truncated) < 25000
    assert "... [output truncated] ..." in truncated


@patch("subprocess.Popen")
def test_runner_timeout_kills_process_and_reports_timeout(mock_popen, tmp_path):
    (tmp_path / "project.godot").touch()

    stdout_mock = MagicMock()
    stdout_mock.readline.return_value = ""
    stderr_mock = MagicMock()
    stderr_mock.readline.return_value = ""

    process_mock = MagicMock()
    process_mock.stdout = stdout_mock
    process_mock.stderr = stderr_mock
    process_mock.poll.return_value = None
    process_mock.returncode = -9
    mock_popen.return_value = process_mock

    runner = GodotRunner(godot_path="godot", timeout=1)
    result = runner.run(tmp_path)

    assert result.timed_out is True
    assert not result.success
    assert process_mock.kill.called


@patch("subprocess.Popen")
def test_runner_fatal_error_terminates_process(mock_popen, tmp_path):
    (tmp_path / "project.godot").touch()

    stdout_mock = MagicMock()
    stdout_mock.readline.return_value = ""

    stderr_lines = iter(["SCRIPT ERROR: Parse error in res://player.gd:10\n", ""])
    stderr_mock = MagicMock()
    stderr_mock.readline.side_effect = lambda: next(stderr_lines, "")

    process_mock = MagicMock()
    process_mock.stdout = stdout_mock
    process_mock.stderr = stderr_mock
    process_mock.poll.return_value = None
    process_mock.returncode = 1
    mock_popen.return_value = process_mock

    runner = GodotRunner(godot_path="godot", timeout=10)
    result = runner.run(tmp_path)

    assert not result.success
    assert result.timed_out is False
    assert process_mock.kill.called
    assert len(result.errors) == 1
    assert result.errors[0].file == "res://player.gd"


def test_bounded_stream_buffer_caps_memory():
    from rbxforge.godot.runner import BoundedStreamBuffer

    buffer = BoundedStreamBuffer(max_bytes=1000)
    for index in range(2000):
        buffer.append(f"line-{index:05d}\n")

    value = buffer.get_value()
    assert "output truncated" in value
    assert len(value.encode("utf-8")) < 1100
