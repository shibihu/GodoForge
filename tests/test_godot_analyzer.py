from pathlib import Path

from rbxforge.godot.analyzer import GodotProjectAnalyzer


def test_scan_requires_project_manifest(tmp_path: Path):
    try:
        GodotProjectAnalyzer(tmp_path).scan()
    except ValueError as exc:
        assert "project.godot" in str(exc)
    else:
        raise AssertionError("expected invalid project error")


def test_scan_discovers_godot_files_and_ignores_generated_dirs(tmp_path: Path):
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Demo"\n', encoding="utf-8")
    (tmp_path / "player.gd").write_text("extends CharacterBody2D\n", encoding="utf-8")
    (tmp_path / "main.tscn").write_text("[gd_scene load_steps=2]\n", encoding="utf-8")
    (tmp_path / "data.tres").write_text('[gd_resource type="Resource"]\n', encoding="utf-8")
    generated = tmp_path / ".godot"
    generated.mkdir()
    (generated / "ignored.gd").write_text("extends Node\n", encoding="utf-8")

    project = GodotProjectAnalyzer(tmp_path).scan()

    assert project.name == "Demo"
    assert {item.path for item in project.files} == {"player.gd", "main.tscn", "data.tres"}


def test_scene_extracts_nodes_and_external_resources(tmp_path: Path):
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Demo"\n', encoding="utf-8")
    scene = '''[gd_scene load_steps=3]\n\n[ext_resource type="Script" path="res://player.gd" id="1"]\n[ext_resource type="Texture2D" path="res://player.png" id="2"]\n\n[node name="Player" type="CharacterBody2D"]\nscript = ExtResource("1")\n\n[node name="Sprite" type="Sprite2D" parent="."]\ntexture = ExtResource("2")\n'''
    (tmp_path / "main.tscn").write_text(scene, encoding="utf-8")

    project = GodotProjectAnalyzer(tmp_path).scan()
    parsed = next(item for item in project.scenes if item.path == "main.tscn")

    assert "Player" in parsed.nodes
    assert "Sprite" in parsed.nodes
    assert "res://player.gd" in parsed.external_resources
    assert "res://player.png" in parsed.external_resources
