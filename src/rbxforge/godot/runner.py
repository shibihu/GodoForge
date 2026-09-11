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
        output_bytes = output.encode("utf-8", errors="replace")
        if len(output_bytes) > self.max_output_bytes:
            half = self.max_output_bytes // 2
            start_part = output_bytes[:half].decode("utf-8", errors="ignore")
            end_part = output_bytes[-half:].decode("utf-8", errors="ignore")
            return start_part + "\n\n... [output truncated] ...\n\n" + end_part
        return output

    def _execute(self, root: Path, cmd: list[str]) -> GodotRunResult:
        import selectors

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

            stdout_chunks: list[str] = []
            stderr_chunks: list[str] = []
            has_fatal_startup_error = False

            sel = selectors.DefaultSelector()
            if process.stdout:
                sel.register(process.stdout, selectors.EVENT_READ, data="stdout")
            if process.stderr:
                sel.register(process.stderr, selectors.EVENT_READ, data="stderr")

            timed_out = False

            while sel.get_map():
                elapsed = time.monotonic() - start_time
                remaining = self.timeout - elapsed
                if remaining <= 0:
                    timed_out = True
                    break

                events = sel.select(timeout=min(0.2, remaining))
                if not events:
                    if process.poll() is not None:
                        # Process finished, read remaining streams
                        for key in list(sel.get_map().values()):
                            line = key.fileobj.read()
                            if line:
                                if key.data == "stdout":
                                    stdout_chunks.append(line)
                                else:
                                    stderr_chunks.append(line)
                            sel.unregister(key.fileobj)
                        break

                for key, _ in events:
                    line = key.fileobj.readline()
                    if not line:
                        sel.unregister(key.fileobj)
                        continue
                    if key.data == "stdout":
                        stdout_chunks.append(line)
                    else:
                        stderr_chunks.append(line)

                    # Check for fatal startup error
                    current_stderr = "".join(stderr_chunks)
                    current_stdout = "".join(stdout_chunks)
                    parsed = GodotErrorParser.parse(current_stdout, current_stderr)
                    if any(e.severity == "error" for e in parsed):
                        has_fatal_startup_error = True

                if has_fatal_startup_error:
                    # Give Godot a short grace period (0.2s) to finish printing traceback details then kill
                    time.sleep(0.2)
                    for key in list(sel.get_map().values()):
                        try:
                            rest = key.fileobj.read()
                            if rest:
                                if key.data == "stdout":
                                    stdout_chunks.append(rest)
                                else:
                                    stderr_chunks.append(rest)
                        except Exception:
                            pass
                        sel.unregister(key.fileobj)
                    process.kill()
                    process.wait()
                    break

            if timed_out and process.poll() is None:
                process.kill()
                process.wait()

            sel.close()

            duration = time.monotonic() - start_time
            raw_stdout = "".join(stdout_chunks)
            raw_stderr = "".join(stderr_chunks)
            if timed_out:
                raw_stderr += "\nError: Process timed out."

            stdout = self.truncate_output(raw_stdout)
            stderr = self.truncate_output(raw_stderr)
            exit_code = process.returncode

            parsed_errors = GodotErrorParser.parse(stdout, stderr)
            has_fatal_errors = any(e.severity == "error" for e in parsed_errors)
            success = (exit_code == 0) and not has_fatal_errors and not timed_out

            return GodotRunResult(
                success=success,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=round(duration, 3),
                timed_out=timed_out,
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
