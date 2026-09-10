from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .errors import GodotErrorParser
from .models import GodotRunResult


class GodotRunner:
    def __init__(self, godot_path: str = "godot", timeout: int = 30, max_output_bytes: int = 20000):
        self.godot_path = godot_path
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes

    def truncate_output(self, output: str) -> str:
        if len(output) > self.max_output_bytes:
            half = self.max_output_bytes // 2
            return output[:half] + "\n\n... [output truncated] ...\n\n" + output[-half:]
        return output

    def _execute(self, root: Path, cmd: list[str]) -> GodotRunResult:
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

    def check_project(self, project_root: str | Path) -> GodotRunResult:
        """Validate/import the Godot project in headless mode without running the main scene."""
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
        cmd = [self.godot_path, "--path", str(root), "--headless", "--editor", "--quit"]
        return self._execute(root, cmd)

    def run_project(self, project_root: str | Path, args: list[str] | None = None) -> GodotRunResult:
        """Run the main scene of the Godot project in headless mode."""
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
        return self._execute(root, cmd)

    def run(self, project_root: str | Path, args: list[str] | None = None) -> GodotRunResult:
        """Backwards compatible run method."""
        return self.run_project(project_root, args)
