from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .errors import GodotErrorParser
from .models import GodotRunResult


class GodotRunner:
    MAX_OUTPUT_LEN = 20000

    def __init__(self, godot_path: str = "godot", timeout: int = 30):
        self.godot_path = godot_path
        self.timeout = timeout

    @classmethod
    def truncate_output(cls, output: str) -> str:
        if len(output) > cls.MAX_OUTPUT_LEN:
            return output[: cls.MAX_OUTPUT_LEN] + "\n... output truncated ..."
        return output

    def run(self, project_root: str | Path, args: list[str] | None = None) -> GodotRunResult:
        root = Path(project_root).expanduser().resolve()
        if not (root / "project.godot").is_file():
            return GodotRunResult(
                success=False,
                exit_code=1,
                stdout="",
                stderr=f"Invalid Godot project root: {root} (missing project.godot)",
                duration_seconds=0.0,
                timed_out=False,
                errors=GodotErrorParser.parse("", f"ERROR: Invalid Godot project root: {root}")
            )

        cmd = [self.godot_path, "--path", str(root), "--headless"]
        if args:
            cmd.extend(args)
        else:
            cmd.append("--editor")  # default headless check/import validate

        start_time = time.monotonic()
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                stdout_raw, stderr_raw = process.communicate(timeout=self.timeout)
                duration = time.monotonic() - start_time
                stdout = self.truncate_output(stdout_raw or "")
                stderr = self.truncate_output(stderr_raw or "")
                exit_code = process.returncode

                parsed_errors = GodotErrorParser.parse(stdout, stderr)
                # Success if exit_code is 0 and no error severity parsed
                has_fatal_errors = any(e.severity == "error" for e in parsed_errors)
                success = (exit_code == 0) and not has_fatal_errors

                return GodotRunResult(
                    success=success,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=round(duration, 3),
                    timed_out=False,
                    errors=parsed_errors,
                )
            except subprocess.TimeoutExpired:
                process.kill()
                stdout_raw, stderr_raw = process.communicate()
                duration = time.monotonic() - start_time
                stdout = self.truncate_output(stdout_raw or "")
                stderr = self.truncate_output((stderr_raw or "") + "\nError: Process timed out.")
                parsed_errors = GodotErrorParser.parse(stdout, stderr)
                return GodotRunResult(
                    success=False,
                    exit_code=None,
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=round(duration, 3),
                    timed_out=True,
                    errors=parsed_errors,
                )

        except FileNotFoundError:
            return GodotRunResult(
                success=False,
                exit_code=None,
                stdout="",
                stderr=f"Godot executable was not found. Configure GODOFORGE_GODOT_PATH (attempted '{self.godot_path}').",
                duration_seconds=0.0,
                timed_out=False,
                errors=[],
            )
        except PermissionError:
            return GodotRunResult(
                success=False,
                exit_code=None,
                stdout="",
                stderr=f"Permission denied when attempting to execute Godot binary at '{self.godot_path}'.",
                duration_seconds=0.0,
                timed_out=False,
                errors=[],
            )
