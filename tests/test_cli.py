from pathlib import Path

import pytest

from rbxforge.core.llm.models import LLMResponse, TaskComplexity
from rbxforge.main import build_request, find_godot_project_root, main, run


class FakeRouter:
    def __init__(self):
        self.request = None
        self.complexity = None
        self.provider = None

    async def generate(self, request, complexity, provider=None):
        self.request = request
        self.complexity = complexity
        self.provider = provider
        return LLMResponse("answer", "fake", "test-model")


def _make_project(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "project.godot").write_text('[application]\nconfig/name="Demo"\n', encoding="utf-8")
    return root


def test_build_request_contains_godot_context(tmp_path: Path):
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Demo"\n', encoding="utf-8")
    (tmp_path / "player.gd").write_text("extends CharacterBody2D\n", encoding="utf-8")
    request = build_request(tmp_path, "Why is movement broken?")
    combined = "\n".join(message.content for message in request.messages)
    assert "Demo" in combined
    assert "player.gd" in combined
    assert "Why is movement broken?" in combined


def test_run_routes_godot_prompt(tmp_path: Path):
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Demo"\n', encoding="utf-8")
    router = FakeRouter()
    result = run(tmp_path, "Explain the project", "simple", None, router=router)
    assert result == "answer"
    assert router.complexity.value == "simple"


def test_find_godot_project_root_from_cwd(tmp_path: Path, monkeypatch):
    project = _make_project(tmp_path / "MyGame")
    monkeypatch.chdir(project)
    assert find_godot_project_root() == project.resolve()


def test_find_godot_project_root_from_subdirectory(tmp_path: Path, monkeypatch):
    project = _make_project(tmp_path / "MyGame")
    subdir = project / "scripts" / "player"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    assert find_godot_project_root() == project.resolve()


def test_find_godot_project_root_returns_none_outside_project(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert find_godot_project_root() is None


def test_main_auto_detects_project_from_cwd(tmp_path: Path, monkeypatch):
    project = _make_project(tmp_path / "MyGame")
    subdir = project / "scripts" / "player"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    captured = {}

    def fake_run(project_root, prompt, complexity, provider):
        captured["root"] = Path(project_root)
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr("rbxforge.main.run", fake_run)
    monkeypatch.setattr("sys.argv", ["rbxforge", "Fix the player script"])
    main()
    assert captured["root"] == project.resolve()
    assert captured["prompt"] == "Fix the player script"


def test_main_accepts_explicit_project_flag(tmp_path: Path, monkeypatch):
    project = _make_project(tmp_path / "OtherGame")
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_run(project_root, prompt, complexity, provider):
        captured["root"] = Path(project_root)
        return "ok"

    monkeypatch.setattr("rbxforge.main.run", fake_run)
    monkeypatch.setattr("sys.argv", ["rbxforge", "--project", str(project), "fix it"])
    main()
    assert captured["root"] == project.resolve()


def test_main_errors_outside_godot_project(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["rbxforge", "hello"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code != 0
    assert "Could not find project.godot" in capsys.readouterr().err


def test_main_rejects_invalid_explicit_project(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["rbxforge", "--project", str(tmp_path / "nope"), "hello"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code != 0
    assert "missing project.godot" in capsys.readouterr().err


def test_interactive_mode_runs_prompts_until_exit(tmp_path: Path, monkeypatch, capsys):
    project = _make_project(tmp_path / "MyGame")
    monkeypatch.chdir(project)
    inputs = iter(["Fix player movement", "", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    captured = []

    def fake_run(project_root, prompt, complexity, provider):
        captured.append(prompt)
        return f"answer:{prompt}"

    monkeypatch.setattr("rbxforge.main.run", fake_run)
    monkeypatch.setattr("sys.argv", ["rbxforge"])
    main()
    assert captured == ["Fix player movement"]
    out = capsys.readouterr().out
    assert "RBXForge" in out
    assert f"Godot project: {project.resolve()}" in out


def test_interactive_mode_continues_after_errors(tmp_path: Path, monkeypatch, capsys):
    project = _make_project(tmp_path / "MyGame")
    monkeypatch.chdir(project)
    inputs = iter(["boom", "ok now", "quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    captured = []

    def fake_run(project_root, prompt, complexity, provider):
        if prompt == "boom":
            raise ValueError("missing project.godot")
        captured.append(prompt)
        return "fine"

    monkeypatch.setattr("rbxforge.main.run", fake_run)
    monkeypatch.setattr("sys.argv", ["rbxforge"])
    main()
    assert captured == ["ok now"]
    assert "error: missing project.godot" in capsys.readouterr().out

def test_run_uses_gemini_tool_agent_when_available(tmp_path, monkeypatch):
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Demo"\n', encoding="utf-8")
    (tmp_path / "player.gd").write_text("extends Node\n", encoding="utf-8")

    class FakeGemini:
        async def generate_with_tools(self, request, tools):
            from rbxforge.core.agent import ToolModelResponse
            from rbxforge.core.tools import ToolCall
            if not any(message.role == "tool" for message in request.messages):
                return ToolModelResponse(tool_calls=[ToolCall("read_file", {"path": "player.gd"})])
            return ToolModelResponse(text="read complete")

    class FakeSettings:
        max_tool_calls = 12
        default_complexity = TaskComplexity.MODERATE

    monkeypatch.setattr("rbxforge.main.Settings.from_env", classmethod(lambda cls: FakeSettings()))
    monkeypatch.setattr("rbxforge.main.build_providers", lambda settings: {"gemini": FakeGemini()})
    assert run(tmp_path, "inspect player", "moderate", None) == "read complete"
