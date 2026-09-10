from pathlib import Path

import pytest

from rbxforge.core.agent import ToolAgent, ToolModelResponse
from rbxforge.core.llm.models import LLMRequest, LLMResponse, Message
from rbxforge.core.tools import GodotToolExecutor, ToolCall
from rbxforge.godot.files import GodotFileService


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text("[application]\n", encoding="utf-8")
    return project


@pytest.mark.asyncio
async def test_agent_executes_read_tool_and_feeds_result_back(tmp_path):
    project = make_project(tmp_path)
    (project / "player.gd").write_text("extends CharacterBody2D\n", encoding="utf-8")
    calls = []

    async def fake_model(request: LLMRequest, tools):
        calls.append(request)
        if len(calls) == 1:
            return ToolModelResponse(tool_calls=[ToolCall("read_file", {"path": "player.gd"})])
        assert "extends CharacterBody2D" in calls[-1].messages[-1].content
        return ToolModelResponse(text="The player uses CharacterBody2D.")

    agent = ToolAgent(fake_model, max_tool_calls=12)
    executor = GodotToolExecutor(GodotFileService(project), lambda *_: False)
    result = await agent.run(LLMRequest([Message("user", "Inspect player.gd")]), executor)

    assert result.text == "The player uses CharacterBody2D."
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_agent_cannot_mutate_when_confirmation_denied(tmp_path):
    project = make_project(tmp_path)
    approvals = []

    async def fake_model(request: LLMRequest, tools):
        if not approvals:
            return ToolModelResponse(
                tool_calls=[ToolCall("write_file", {"path": "player.gd", "content": "new\n"})]
            )
        return ToolModelResponse(text="I could not apply the change.")

    def confirm(operation, path, details):
        approvals.append((operation, path, details))
        return False

    agent = ToolAgent(fake_model, max_tool_calls=12)
    executor = GodotToolExecutor(GodotFileService(project), confirm)
    result = await agent.run(LLMRequest([Message("user", "Create player.gd")]), executor)

    assert result.text == "I could not apply the change."
    assert not (project / "player.gd").exists()
    assert approvals[0][0] == "write_file"


@pytest.mark.asyncio
async def test_agent_stops_at_tool_call_limit(tmp_path):
    project = make_project(tmp_path)
    count = 0

    async def fake_model(request, tools):
        nonlocal count
        count += 1
        return ToolModelResponse(tool_calls=[ToolCall("list_files", {})])

    agent = ToolAgent(fake_model, max_tool_calls=2)
    executor = GodotToolExecutor(GodotFileService(project), lambda *_: True)
    result = await agent.run(LLMRequest([Message("user", "loop")]), executor)

    assert "maximum tool-call limit" in result.text
    assert count == 2


def test_confirmation_only_accepts_yes(monkeypatch, capsys):
    from rbxforge.main import confirm_tool_action

    answers = iter(["n", "YES"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert confirm_tool_action("write_file", "player.gd", "Replace it") is False
    assert confirm_tool_action("write_file", "player.gd", "Replace it") is True
    output = capsys.readouterr().out
    assert "RBXForge wants to write_file" in output
    assert "player.gd" in output
