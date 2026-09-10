from pathlib import Path

from rbxforge.godot.analyzer import GodotProjectAnalyzer


def test_context_contains_project_scene_and_script_information(tmp_path: Path):
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Context Demo"\n', encoding="utf-8")
    (tmp_path / "player.gd").write_text("extends CharacterBody2D\nfunc _physics_process(delta):\n    pass\n", encoding="utf-8")
    (tmp_path / "main.tscn").write_text('[node name="Player" type="CharacterBody2D"]\n', encoding="utf-8")

    analyzer = GodotProjectAnalyzer(tmp_path)
    project = analyzer.scan()
    context = analyzer.build_context(project, max_chars=2000)

    assert "Context Demo" in context
    assert "player.gd" in context
    assert "main.tscn" in context
    assert "CharacterBody2D" in context


def test_context_respects_character_limit(tmp_path: Path):
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Demo"\n', encoding="utf-8")
    (tmp_path / "large.gd").write_text("# x\n" * 10000, encoding="utf-8")

    analyzer = GodotProjectAnalyzer(tmp_path)
    context = analyzer.build_context(analyzer.scan(), max_chars=500)

    assert len(context) <= 500
