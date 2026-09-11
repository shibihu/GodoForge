from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from .errors import GodotErrorParser
from .models import GodotRunResult


class BoundedStreamBuffer:
    """Thread-safe bounded output buffer that caps memory usage while reading streams."""

    def __init__(self, max_bytes: int = 20000):
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._bytes = bytearray()
        self._total_read = 0

    def append(self, text: str) -> None:
        if not text:
            return
        data = text.encode("utf-8", errors="replace")
        with self._lock:
            self._total_read += len(data)
            self._bytes.extend(data)
            if len(self._bytes) > self.max_bytes * 2:
                # Keep head and tail to fit max_bytes
                half = self.max_bytes // 2
                head = self._bytes[:half]
                tail = self._bytes[-half:]
                self._bytes = head + b"\n\n... [output truncated] ...\n\n" + tail

    def get_value(self) -> str:
        with self._lock:
            raw = bytes(self._bytes)
        output = raw.decode("utf-8", errors="replace")
        if len(raw) > self.max_bytes:
            half = self.max_bytes // 2
            start_part = raw[:half].decode("utf-8", errors="ignore")
            end_part = raw[-half:].decode("utf-8", errors="ignore")
            return start_part + "\n\n... [output truncated] ...\n\n" + end_part
        return output


class GodotRunner:
    def __init__(self, godot_path: str = "godot", timeout: int = 30, max_output_bytes: int = 20000):
        self.godot_path = godot_path
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes

    def truncate_output(self, output: str) -> str:
        output_bytes = output.encode("utf-8", errors="replace")
        if len(output_bytes) > self.max_output_bytes:
            half = self.max_output_bytes // 2
            start_part = output_bytes[:half].decode("utf-8", errors="ignore")
            end_part = output_bytes[-half:].decode("utf-8", errors="ignore")
            return start_part + "\n\n... [output truncated] ...\n\n" + end_part
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
                bufsize=1,
            )

            stdout_buf = BoundedStreamBuffer(max_bytes=self.max_output_bytes)
            stderr_buf = BoundedStreamBuffer(max_bytes=self.max_output_bytes)

            def read_stream(stream, buffer):
                try:
                    for line in iter(stream.readline, ""):
                        buffer.append(line)
                    stream.close()
                except Exception:
                    pass

            t_stdout = threading.Thread(target=read_stream, args=(process.stdout, stdout_buf), daemon=True)
            t_stderr = threading.Thread(target=read_stream, args=(process.stderr, stderr_buf), daemon=True)
            t_stdout.start()
            t_stderr.start()

            timed_out = False
            has_fatal_startup_error = False

            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= self.timeout:
                    timed_out = True
                    break

                current_stdout = stdout_buf.get_value()
                current_stderr = stderr_buf.get_value()
                parsed = GodotErrorParser.parse(current_stdout, current_stderr)
                if any(e.severity == "error" for e in parsed):
                    has_fatal_startup_error = True
                    # Grace period for stream threads to finish writing traceback details
                    time.sleep(0.2)
                    break

                if process.poll() is not None:
                    break

                time.sleep(0.05)

            if has_fatal_startup_error or timed_out:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass

            t_stdout.join(timeout=1)
            t_stderr.join(timeout=1)

            duration = time.monotonic() - start_time
            raw_stdout = stdout_buf.get_value()
            raw_stderr = stderr_buf.get_value()
            if timed_out and not has_fatal_startup_error:
                raw_stderr += "\nError: Process timed out."

            stdout = self.truncate_output(raw_stdout)
            stderr = self.truncate_output(raw_stderr)
            exit_code = process.returncode

            parsed_errors = GodotErrorParser.parse(stdout, stderr)
            has_fatal_errors = any(e.severity == "error" for e in parsed_errors)
            success = (exit_code == 0 or (has_fatal_startup_error and not exit_code)) and not has_fatal_errors and not (timed_out and not has_fatal_startup_error)
            if has_fatal_startup_error:
                success = False

            return GodotRunResult(
                success=success,
                exit_code=exit_code if exit_code is not None else 1,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=round(duration, 3),
                timed_out=timed_out and not has_fatal_startup_error,
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
