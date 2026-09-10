from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path


IGNORED_DIRS = frozenset({".godot", ".git", "bin", "obj"})
SUPPORTED_CODE_SUFFIXES = frozenset({".gd", ".tscn", ".tres"})
Confirmation = Callable[[str, str, str], bool]


class FileToolError(ValueError):
    """Controlled error raised for invalid or unsafe file-agent operations."""


@dataclass(frozen=True)
class CodeMatch:
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class OperationResult:
    operation: str
    path: str
    changed: bool
    backup_path: str | None = None


class GodotFileService:
    def __init__(self, root: str | Path, max_file_bytes: int = 200_000):
        if max_file_bytes <= 0:
            raise FileToolError("max_file_bytes must be greater than zero")
        root_path = Path(root).expanduser()
        try:
            resolved = root_path.resolve(strict=True)
        except OSError as exc:
            raise FileToolError(f"Invalid project root: {root}") from exc
        if not resolved.is_dir():
            raise FileToolError(f"Project root is not a directory: {root}")
        if not (resolved / "project.godot").is_file():
            raise FileToolError(f"Invalid Godot project: missing project.godot in {resolved}")
        self.root = resolved
        self.max_file_bytes = max_file_bytes

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    def _validate_components(self, candidate: Path) -> None:
        try:
            relative = candidate.relative_to(self.root)
        except ValueError as exc:
            raise FileToolError("Path is outside the Godot project root") from exc
        for component in relative.parts:
            if component in {"", "."}:
                continue
            if component in IGNORED_DIRS:
                raise FileToolError(f"Path is inside an inaccessible directory: {component}")

    def _resolve(self, relative_path: str | Path, *, allow_root: bool = False) -> Path:
        raw = Path(relative_path).expanduser()
        if not str(raw):
            raise FileToolError("Path must not be empty")
        candidate = raw.resolve(strict=False) if raw.is_absolute() else (self.root / raw).resolve(strict=False)
        if candidate != self.root and self.root not in candidate.parents:
            raise FileToolError("Path is outside the Godot project root")
        if candidate == self.root and not allow_root:
            raise FileToolError("Project root is not a file")
        self._validate_components(candidate)
        try:
            existing = candidate
            while existing != self.root:
                if existing.is_symlink():
                    raise FileToolError("Symlinked paths are not accessible to file-agent tools")
                existing = existing.parent
        except OSError as exc:
            raise FileToolError(f"Could not validate path: {relative_path}") from exc
        return candidate

    def _read_bounded(self, path: Path) -> str:
        try:
            with path.open("rb") as handle:
                data = handle.read(self.max_file_bytes + 1)
        except (OSError, PermissionError) as exc:
            raise FileToolError(f"Could not read file: {self._relative(path)}") from exc
        if len(data) > self.max_file_bytes:
            raise FileToolError(
                f"File exceeds the {self.max_file_bytes}-byte limit: {self._relative(path)}"
            )
        return data.decode("utf-8", errors="replace")

    def read_file(self, relative_path: str | Path) -> str:
        path = self._resolve(relative_path)
        if not path.exists():
            raise FileToolError(f"File does not exist: {self._relative(path)}")
        if not path.is_file():
            raise FileToolError(f"Path is not a file: {self._relative(path)}")
        return self._read_bounded(path)

    def _iter_files(self, start: Path) -> Iterator[Path]:
        if not start.exists():
            raise FileToolError(f"Directory does not exist: {self._relative(start)}")
        if not start.is_dir():
            raise FileToolError(f"Path is not a directory: {self._relative(start)}")
        for current, dirs, files in os.walk(start, topdown=True, followlinks=False):
            current_path = Path(current)
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
            files[:] = sorted(files)
            for name in files:
                path = current_path / name
                if path.is_symlink() or not path.is_file():
                    continue
                yield path

    def list_files(self, relative_dir: str | Path = ".") -> list[str]:
        directory = self._resolve(relative_dir, allow_root=True)
        return sorted(self._relative(path) for path in self._iter_files(directory))

    def search_code(self, query: str, relative_dir: str | Path = ".") -> list[CodeMatch]:
        if not isinstance(query, str) or not query:
            raise FileToolError("Search query must be a non-empty string")
        directory = self._resolve(relative_dir, allow_root=True)
        matches: list[CodeMatch] = []
        for path in self._iter_files(directory):
            if path.suffix.lower() not in SUPPORTED_CODE_SUFFIXES:
                continue
            text = self._read_bounded(path)
            for number, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    matches.append(CodeMatch(self._relative(path), number, line))
        matches.sort(key=lambda item: (item.path, item.line))
        return matches

    @staticmethod
    def _call_confirmation(confirm: Confirmation, operation: str, path: str, details: str) -> bool:
        try:
            return bool(confirm(operation, path, details))
        except Exception as exc:
            raise FileToolError("Confirmation callback failed") from exc

    def create_file(self, relative_path: str | Path, content: str, confirm: Confirmation) -> OperationResult:
        path = self._resolve(relative_path)
        if path.exists():
            raise FileToolError(f"File already exists: {self._relative(path)}")
        if not isinstance(content, str):
            raise FileToolError("File content must be text")
        relative = self._relative(path)
        details = f"Create a new file with {len(content.encode('utf-8'))} bytes."
        if not self._call_confirmation(confirm, "create_file", relative, details):
            return OperationResult("create_file", relative, False)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(path, content)
        except OSError as exc:
            raise FileToolError(f"Could not create file: {relative}") from exc
        return OperationResult("create_file", relative, True)

    def write_file(self, relative_path: str | Path, content: str, confirm: Confirmation) -> OperationResult:
        path = self._resolve(relative_path)
        if path.exists() and not path.is_file():
            raise FileToolError(f"Path is not a file: {self._relative(path)}")
        if not isinstance(content, str):
            raise FileToolError("File content must be text")
        relative = self._relative(path)
        existed = path.exists()
        old_text = self._read_bounded(path) if existed else ""
        new_bytes = len(content.encode("utf-8"))
        details = (
            f"Replace the existing file ({len(old_text.encode('utf-8'))} bytes) with "
            f"{new_bytes} bytes."
            if existed
            else f"Create the file with {new_bytes} bytes."
        )
        if not self._call_confirmation(confirm, "write_file", relative, details):
            return OperationResult("write_file", relative, False)
        backup_relative: str | None = None
        try:
            if existed:
                backup = self._get_unique_backup_path(path)
                self._atomic_copy(path, backup)
                backup_relative = self._relative(backup)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(path, content)
        except OSError as exc:
            raise FileToolError(f"Could not write file: {relative}") from exc
        return OperationResult("write_file", relative, True, backup_relative)

    def delete_file(self, relative_path: str | Path, confirm: Confirmation) -> OperationResult:
        path = self._resolve(relative_path)
        relative = self._relative(path)
        if relative == "project.godot":
            raise FileToolError("project.godot is protected and cannot be deleted")
        if not path.exists():
            raise FileToolError(f"File does not exist: {relative}")
        if not path.is_file():
            raise FileToolError(f"Path is not a file: {relative}")
        details = "This is an irreversible file deletion."
        if not self._call_confirmation(confirm, "delete_file", relative, details):
            return OperationResult("delete_file", relative, False)
        try:
            path.unlink()
        except OSError as exc:
            raise FileToolError(f"Could not delete file: {relative}") from exc
        return OperationResult("delete_file", relative, True)

    @staticmethod
    def _get_unique_backup_path(path: Path) -> Path:
        base_backup = Path(f"{path}.rbxforge.bak")
        if not base_backup.exists():
            return base_backup
        counter = 1
        while True:
            candidate = Path(f"{path}.rbxforge.bak.{counter}")
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temp_name).replace(path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        try:
            with source.open("rb") as source_handle, os.fdopen(fd, "wb") as destination_handle:
                while True:
                    chunk = source_handle.read(64 * 1024)
                    if not chunk:
                        break
                    destination_handle.write(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
            Path(temp_name).replace(destination)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
