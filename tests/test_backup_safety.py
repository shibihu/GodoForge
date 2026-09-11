from pathlib import Path
from rbxforge.godot.files import GodotFileService, OperationResult


def test_unique_backup_creation(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "project.godot").touch()
    player_gd = project_dir / "player.gd"
    player_gd.write_text("extends Node\n", encoding="utf-8")

    service = GodotFileService(project_dir)

    def confirm_yes(*_):
        return True

    # First write -> player.gd.rbxforge.bak
    res1 = service.write_file("player.gd", "extends Node\n# v2\n", confirm_yes)
    assert res1.backup_path == "player.gd.rbxforge.bak"
    assert (project_dir / "player.gd.rbxforge.bak").read_text() == "extends Node\n"

    # Second write -> player.gd.rbxforge.bak.1
    res2 = service.write_file("player.gd", "extends Node\n# v3\n", confirm_yes)
    assert res2.backup_path == "player.gd.rbxforge.bak.1"
    assert (project_dir / "player.gd.rbxforge.bak.1").read_text() == "extends Node\n# v2\n"

    # Third write -> player.gd.rbxforge.bak.2
    res3 = service.write_file("player.gd", "extends Node\n# v4\n", confirm_yes)
    assert res3.backup_path == "player.gd.rbxforge.bak.2"
    assert (project_dir / "player.gd.rbxforge.bak.2").read_text() == "extends Node\n# v3\n"
