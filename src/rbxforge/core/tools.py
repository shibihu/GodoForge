from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rbxforge.godot.files import Confirmation, GodotFileService, FileToolError


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    read_only: bool


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    data: dict | list | str | None = None
    error: str | None = None


class GodotToolExecutor:
    _DEFINITIONS = (
        ToolDefinition(
            "list_files",
            "List project-relative files in a directory.",
            {"type": "object", "properties": {"directory": {"type": "string"}}},
            True,
        ),
        ToolDefinition(
            "read_file",
            "Read a bounded UTF-8 project file.",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            True,
        ),
        ToolDefinition(
            "search_code",
            "Search .gd, .tscn, and .tres files for text.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "directory": {"type": "string"},
                },
                "required": ["query"],
            },
            True,
        ),
        ToolDefinition(
            "create_file",
            "Create a new project file after explicit confirmation.",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
            False,
        ),
        ToolDefinition(
            "write_file",
            "Replace a project file after explicit confirmation; existing files are backed up.",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
            False,
        ),
        ToolDefinition(
            "delete_file",
            "Delete a project file after explicit confirmation.",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            False,
        ),
    )

    def __init__(self, service: GodotFileService, confirm: Confirmation):
        self.service = service
        self.confirm = confirm

    def definitions(self) -> list[ToolDefinition]:
        return list(self._DEFINITIONS)

    def execute(self, call: ToolCall) -> ToolResult:
        try:
            args = call.arguments
            if call.name == "list_files":
                return ToolResult(call.name, True, self.service.list_files(args.get("directory", ".")))
            if call.name == "read_file":
                return ToolResult(call.name, True, self.service.read_file(self._required(args, "path")))
            if call.name == "search_code":
                matches = self.service.search_code(
                    self._required(args, "query"), args.get("directory", ".")
                )
                return ToolResult(
                    call.name,
                    True,
                    [{"path": m.path, "line": m.line, "text": m.text} for m in matches],
                )
            if call.name == "create_file":
                result = self.service.create_file(
                    self._required(args, "path"), self._required(args, "content"), self.confirm
                )
                return ToolResult(call.name, True, result.__dict__)
            if call.name == "write_file":
                result = self.service.write_file(
                    self._required(args, "path"), self._required(args, "content"), self.confirm
                )
                return ToolResult(call.name, True, result.__dict__)
            if call.name == "delete_file":
                result = self.service.delete_file(self._required(args, "path"), self.confirm)
                return ToolResult(call.name, True, result.__dict__)
            return ToolResult(call.name, False, error=f"Unknown tool: {call.name}")
        except (FileToolError, TypeError, KeyError) as exc:
            return ToolResult(call.name, False, error=str(exc))

    @staticmethod
    def _required(arguments: dict[str, Any], name: str) -> str:
        value = arguments.get(name)
        if not isinstance(value, str) or not value:
            raise FileToolError(f"Missing required argument: {name}")
        return value
