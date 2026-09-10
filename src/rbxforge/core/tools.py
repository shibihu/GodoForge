from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rbxforge.godot.files import Confirmation, GodotFileService, FileToolError
from rbxforge.godot.runner import GodotRunner


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
    thought_signature: bytes | None = None


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
            {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Project-relative directory path to list (defaults to '.').",
                    }
                },
                "additionalProperties": False,
            },
            True,
        ),
        ToolDefinition(
            "read_file",
            "Read a bounded UTF-8 project file.",
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project-relative file path to read.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            True,
        ),
        ToolDefinition(
            "search_code",
            "Search .gd, .tscn, and .tres files for text.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text query to search for.",
                    },
                    "directory": {
                        "type": "string",
                        "description": "Project-relative directory to search in (defaults to '.').",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            True,
        ),
        ToolDefinition(
            "create_file",
            "Create a new project file after explicit confirmation.",
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project-relative path where the file will be created.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Text content to write to the new file.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            False,
        ),
        ToolDefinition(
            "write_file",
            "Replace a project file after explicit confirmation; existing files are backed up.",
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project-relative path of the file to replace.",
                    },
                    "content": {
                        "type": "string",
                        "description": "New text content to write to the file.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            False,
        ),
        ToolDefinition(
            "delete_file",
            "Delete a project file after explicit confirmation.",
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project-relative path of the file to delete.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            False,
        ),
        ToolDefinition(
            "run_godot",
            "Execute the Godot project in headless mode to verify scripts and capture runtime errors.",
            {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional command line arguments to pass to Godot.",
                    }
                },
                "additionalProperties": False,
            },
            True,
        ),
    )

    def __init__(self, service: GodotFileService, confirm: Confirmation, runner: GodotRunner | None = None):
        self.service = service
        self.confirm = confirm
        self.runner = runner or GodotRunner()

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
            if call.name == "run_godot":
                extra_args = args.get("args")
                if not isinstance(extra_args, list):
                    extra_args = None
                run_res = self.runner.run(self.service.root, extra_args)
                errs_data = [
                    {
                        "message": e.message,
                        "file": e.file,
                        "line": e.line,
                        "column": e.column,
                        "severity": e.severity,
                    }
                    for e in run_res.errors
                ]
                payload = {
                    "success": run_res.success,
                    "exit_code": run_res.exit_code,
                    "timed_out": run_res.timed_out,
                    "duration_seconds": run_res.duration_seconds,
                    "errors": errs_data,
                    "stdout": run_res.stdout,
                    "stderr": run_res.stderr,
                }
                return ToolResult(call.name, True, payload)
            return ToolResult(call.name, False, error=f"Unknown tool: {call.name}")
        except (FileToolError, TypeError, KeyError) as exc:
            return ToolResult(call.name, False, error=str(exc))

    @staticmethod
    def _required(arguments: dict[str, Any], name: str) -> str:
        value = arguments.get(name)
        if not isinstance(value, str) or not value:
            raise FileToolError(f"Missing required argument: {name}")
        return value
