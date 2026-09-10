from __future__ import annotations

import re
from pathlib import Path

from .models import GodotFile, GodotProject, GodotScene


_SUPPORTED = {".gd": "script", ".tscn": "scene", ".tres": "resource"}
_IGNORED_DIRS = {".godot", ".git", "bin", "obj"}
_SCENE_NODE_RE = re.compile(r'^\[node\s+name="([^"]+)"', re.MULTILINE)
_RES_PATH_RE = re.compile(r'^\[ext_resource[^\n]*?path="([^"]+)"', re.MULTILINE)


class GodotProjectAnalyzer:
    def __init__(self, root: str | Path, max_file_bytes: int = 200_000):
        self.root = Path(root).expanduser().resolve()
        self.max_file_bytes = max_file_bytes
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")

    def _validate(self) -> None:
        if not self.root.is_dir():
            raise ValueError(f"Godot project directory does not exist: {self.root}")
        manifest = self.root / "project.godot"
        if not manifest.is_file():
            raise ValueError(f"Invalid Godot project: missing project.godot in {self.root}")

    def _read(self, path: Path) -> str:
        try:
            with path.open("rb") as handle:
                data = handle.read(self.max_file_bytes)
            return data.decode("utf-8", errors="replace")
        except OSError:
            return ""

    def _project_name(self) -> str:
        text = self._read(self.root / "project.godot")
        match = re.search(r'^config/name\s*=\s*"([^"]*)"', text, re.MULTILINE)
        return match.group(1) if match else self.root.name

    def _discover(self) -> list[GodotFile]:
        files: list[GodotFile] = []
        for path in self.root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                relative = path.relative_to(self.root)
            except ValueError:
                continue
            if any(part in _IGNORED_DIRS for part in relative.parts):
                continue
            kind = _SUPPORTED.get(path.suffix.lower())
            if kind is None:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            files.append(GodotFile(relative.as_posix(), kind, size, self._read(path)))
        return sorted(files, key=lambda item: item.path)

    @staticmethod
    def _parse_scene(item: GodotFile) -> GodotScene:
        nodes = _SCENE_NODE_RE.findall(item.content)
        resources = _RES_PATH_RE.findall(item.content)
        return GodotScene(item.path, list(dict.fromkeys(nodes)), list(dict.fromkeys(resources)))

    def scan(self) -> GodotProject:
        self._validate()
        files = self._discover()
        scenes = [self._parse_scene(item) for item in files if item.kind == "scene"]
        return GodotProject(str(self.root), self._project_name(), files, scenes)

    def build_context(self, project: GodotProject, max_chars: int = 12_000) -> str:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        chunks = [f"[Godot Project]\nName: {project.name}\nRoot: {project.root}\n"]
        chunks.append("\n[File Inventory]")
        for item in project.files:
            chunks.append(f"\n- {item.path} ({item.kind}, {item.size} bytes)")
        for scene in project.scenes:
            chunks.append(f"\n\n[Scene: {scene.path}]")
            if scene.nodes:
                chunks.append("\nNodes: " + ", ".join(scene.nodes))
            if scene.external_resources:
                chunks.append("\nExternal resources: " + ", ".join(scene.external_resources))
        for item in project.files:
            if item.kind in {"script", "resource"} and item.content:
                chunks.append(f"\n\n[{item.kind.title()}: {item.path}]\n{item.content}")
        return "".join(chunks)[:max_chars]
