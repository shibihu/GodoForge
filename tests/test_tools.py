from pathlib import Path

from rbxforge.core.tools import GodotToolExecutor, ToolCall
from rbxforge.godot.files import GodotFileService


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text("[application]\n", encoding="utf-8")
    return project


def test_tool_executor_dispatches_read_file(tmp_path):
    project = make_project(tmp_path)
    (project / "player.gd").write_text("extends Node\n", encoding="utf-8")
    executor = GodotToolExecutor(GodotFileService(project), lambda *_: False)

    result = executor.execute(ToolCall("read_file", {"path": "player.gd"}))

    assert result.ok is True
    assert result.data == "extends Node\n"


def test_tool_executor_definitions_are_stable_and_mark_mutations(tmp_path):
    executor = GodotToolExecutor(GodotFileService(make_project(tmp_path)), lambda *_: False)
    definitions = executor.definitions()
    assert [item.name for item in definitions] == [
        "list_files", "read_file", "search_code", "create_file", "write_file", "delete_file", "run_godot"
    ]
    assert [item.read_only for item in definitions] == [True, True, True, False, False, False, True]


def test_tool_executor_does_not_bypass_confirmation(tmp_path):
    project = make_project(tmp_path)
    target = project / "player.gd"
    target.write_text("extends Node\n", encoding="utf-8")
    executor = GodotToolExecutor(GodotFileService(project), lambda *_: False)

    result = executor.execute(ToolCall("write_file", {"path": "player.gd", "content": "changed\n"}))

    assert result.ok is True
    assert result.data["changed"] is False
    assert target.read_text(encoding="utf-8") == "extends Node\n"


def test_tool_executor_returns_controlled_unknown_tool_error(tmp_path):
    executor = GodotToolExecutor(GodotFileService(make_project(tmp_path)), lambda *_: False)
    result = executor.execute(ToolCall("does_not_exist", {}))
    assert result.ok is False
    assert "Unknown tool" in (result.error or "")
