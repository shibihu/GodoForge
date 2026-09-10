from pathlib import Path

import pytest

from rbxforge.godot.files import FileToolError, GodotFileService


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text("[application]\n", encoding="utf-8")
    return project


def test_read_file_and_reject_parent_traversal(tmp_path):
    project = make_project(tmp_path)
    (project / "player.gd").write_text("extends Node\n", encoding="utf-8")
    (tmp_path / "outside.gd").write_text("secret\n", encoding="utf-8")

    service = GodotFileService(project)
    assert service.read_file("player.gd") == "extends Node\n"
    with pytest.raises(FileToolError):
        service.read_file("../outside.gd")


def test_list_files_is_sorted_and_ignores_generated_dirs(tmp_path):
    project = make_project(tmp_path)
    (project / "z.gd").write_text("z", encoding="utf-8")
    (project / "a.gd").write_text("needle", encoding="utf-8")
    generated = project / ".godot"
    generated.mkdir()
    (generated / "hidden.gd").write_text("needle", encoding="utf-8")

    service = GodotFileService(project)
    assert service.list_files() == ["a.gd", "project.godot", "z.gd"]


def test_search_code_returns_line_numbers(tmp_path):
    project = make_project(tmp_path)
    (project / "player.gd").write_text("extends Node\nmove_and_slide()\n", encoding="utf-8")
    service = GodotFileService(project)

    matches = service.search_code("move_and_slide")
    assert [(m.path, m.line, m.text) for m in matches] == [("player.gd", 2, "move_and_slide()")]


def test_read_file_is_bounded(tmp_path):
    project = make_project(tmp_path)
    (project / "large.gd").write_text("x" * 11, encoding="utf-8")
    service = GodotFileService(project, max_file_bytes=10)
    with pytest.raises(FileToolError, match="exceeds"):
        service.read_file("large.gd")


def test_symlink_escape_is_rejected(tmp_path):
    project = make_project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.gd").write_text("secret", encoding="utf-8")
    link = project / "link.gd"
    try:
        link.symlink_to(outside / "secret.gd")
    except OSError:
        pytest.skip("symlinks are unavailable")
    service = GodotFileService(project)
    with pytest.raises(FileToolError):
        service.read_file("link.gd")


def test_create_requires_confirmation(tmp_path):
    project = make_project(tmp_path)
    service = GodotFileService(project)

    denied = service.create_file("health.gd", "extends Node\n", lambda *_: False)
    assert denied.changed is False
    assert not (project / "health.gd").exists()

    approved = service.create_file("health.gd", "extends Node\n", lambda *_: True)
    assert approved.changed is True
    assert (project / "health.gd").read_text(encoding="utf-8") == "extends Node\n"


def test_write_creates_backup_after_confirmation(tmp_path):
    project = make_project(tmp_path)
    target = project / "player.gd"
    target.write_text("old\n", encoding="utf-8")
    service = GodotFileService(project)

    result = service.write_file("player.gd", "new\n", lambda *_: True)
    assert result.changed is True
    assert target.read_text(encoding="utf-8") == "new\n"
    assert (project / "player.gd.rbxforge.bak").read_text(encoding="utf-8") == "old\n"


def test_write_denial_leaves_existing_file_untouched(tmp_path):
    project = make_project(tmp_path)
    target = project / "player.gd"
    target.write_text("old\n", encoding="utf-8")
    service = GodotFileService(project)
    result = service.write_file("player.gd", "new\n", lambda *_: False)
    assert result.changed is False
    assert target.read_text(encoding="utf-8") == "old\n"
    assert not (project / "player.gd.rbxforge.bak").exists()


def test_delete_never_deletes_project_manifest(tmp_path):
    project = make_project(tmp_path)
    service = GodotFileService(project)
    with pytest.raises(FileToolError):
        service.delete_file("project.godot", lambda *_: True)
    assert (project / "project.godot").exists()


def test_delete_requires_confirmation(tmp_path):
    project = make_project(tmp_path)
    target = project / "old.gd"
    target.write_text("old", encoding="utf-8")
    service = GodotFileService(project)
    denied = service.delete_file("old.gd", lambda *_: False)
    assert denied.changed is False
    assert target.exists()
    approved = service.delete_file("old.gd", lambda *_: True)
    assert approved.changed is True
    assert not target.exists()
