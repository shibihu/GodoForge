from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .config import Settings
from .core.agent import ToolAgent
from .core.llm.errors import ProviderError
from .core.llm.models import LLMRequest, Message, TaskComplexity
from .core.tools import GodotToolExecutor
from .core.router import LLMRouter
from .godot.analyzer import GodotProjectAnalyzer
from .godot.files import GodotFileService
from .godot.runner import GodotRunner
from .providers.registry import build_providers


def find_godot_project_root(start: str | Path | None = None) -> Path | None:
    """Return the nearest directory containing project.godot, walking up from start."""
    current = Path(start or Path.cwd()).expanduser().resolve()
    for directory in (current, *current.parents):
        if (directory / "project.godot").is_file():
            return directory
    return None


def build_request(project_root: str | Path, prompt: str) -> LLMRequest:
    analyzer = GodotProjectAnalyzer(project_root)
    project = analyzer.scan()
    context = analyzer.build_context(project)
    content = (
        "You are RBXForge, an AI assistant for Godot development.\n"
        "You are debugging a Godot 4 project.\n"
        "Do not assume the cause.\n"
        "Inspect the actual files first.\n"
        "Use the runtime error as evidence.\n"
        "Make the smallest correct change.\n"
        "Do not rewrite unrelated code.\n"
        "After changing code, run Godot again and verify the result.\n\n"
        f"Project Context:\n{context}\n\n[User Request]\n{prompt}"
    )
    return LLMRequest([Message("user", content)])


def confirm_tool_action(operation: str, path: str, details: str) -> bool:
    print(f"RBXForge wants to {operation}:\n")
    print(path)
    print()
    print(details)
    answer = input("Apply this change? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def run_agent(project_root: str | Path, prompt: str, gemini_provider, max_tool_calls: int = 12, runner: GodotRunner | None = None) -> str:
    request = build_request(project_root, prompt)
    service = GodotFileService(project_root)
    executor = GodotToolExecutor(service, confirm_tool_action, runner=runner)
    agent = ToolAgent(
        lambda req, tools: gemini_provider.generate_with_tools(req, tools),
        max_tool_calls=max_tool_calls,
    )
    response = asyncio.run(agent.run(request, executor))
    return response.text


def _snapshot_project_files(project_root: str | Path) -> dict[str, str]:
    try:
        service = GodotFileService(project_root)
        file_map = {}
        for rel_path in service.list_files():
            try:
                file_map[rel_path] = service.read_file(rel_path)
            except Exception:
                pass
        return file_map
    except Exception:
        return {}


def run_check(project_root: str | Path, settings: Settings) -> str:
    runner = GodotRunner(godot_path=settings.godot_path, timeout=settings.godot_timeout, max_output_bytes=settings.godot_max_output_bytes)
    result = runner.check_project(project_root)
    return _format_run_result(result, "validation")


def run_project_cmd(project_root: str | Path, settings: Settings) -> str:
    runner = GodotRunner(godot_path=settings.godot_path, timeout=settings.godot_timeout, max_output_bytes=settings.godot_max_output_bytes)
    result = runner.run_project(project_root)
    return _format_run_result(result, "execution")


def _format_run_result(result, mode_label: str) -> str:
    lines = []
    if result.success:
        if result.errors:
            lines.append(f"✓ Godot {mode_label} passed (with warnings):")
        else:
            lines.append(f"✓ Godot {mode_label} passed successfully:")
    else:
        if result.timed_out:
            lines.append(f"✗ Godot {mode_label} timed out:")
        else:
            lines.append(f"✗ Godot {mode_label} failed:")

    if result.exit_code is not None:
        lines.append(f"Exit code: {result.exit_code}")
    if result.duration_seconds:
        lines.append(f"Duration: {result.duration_seconds}s")

    if result.errors:
        lines.append("\nParsed Diagnostics:")
        for err in result.errors:
            loc = f" in {err.file}" if err.file else ""
            loc += f":{err.line}" if err.line else ""
            loc += f":{err.column}" if err.column else ""
            lines.append(f" - [{err.severity.upper()}][{err.error_type}]{loc}: {err.message}")

    if result.stderr:
        lines.append(f"\nStderr Output:\n{result.stderr}")
    elif result.stdout and not result.success:
        lines.append(f"\nStdout Output:\n{result.stdout}")

    return "\n".join(lines)


def run_repair(project_root: str | Path, settings: Settings, provider: str | None = None) -> str:
    providers = build_providers(settings)
    gemini_provider = providers.get("gemini")
    runner = GodotRunner(godot_path=settings.godot_path, timeout=settings.godot_timeout, max_output_bytes=settings.godot_max_output_bytes)

    last_errors = None
    repairs_performed = 0

    for attempt in range(1, settings.max_repair_attempts + 1):
        print(f"\n[Repair Attempt {attempt}/{settings.max_repair_attempts}]", flush=True)
        print("Running Godot project check...", flush=True)

        run_res = runner.run_project(project_root)
        if run_res.success:
            if repairs_performed > 0:
                return f"✓ Godot verification passed\n✓ {repairs_performed} repair(s) performed\n✓ Project completed successfully"
            else:
                return "✓ Godot verification passed. No repairs needed."

        fatal_errors = [e for e in run_res.errors if e.severity == "error"]
        if not fatal_errors and run_res.errors:
            return f"✓ Godot verification passed (with warnings)\nStderr:\n{run_res.stderr}"

        current_errors_str = run_res.stderr or run_res.stdout
        if current_errors_str == last_errors and attempt > 1:
            return f"Repair stopped early: Error persisted unchanged after attempt {attempt - 1}.\nLast error:\n{current_errors_str}"
        last_errors = current_errors_str

        print(f"Error detected during Godot execution:\n{current_errors_str}\n", flush=True)

        prompt = (
            f"Godot execution failed on attempt {attempt}/{settings.max_repair_attempts}.\n"
            f"Error output:\n{current_errors_str}\n\n"
            "Please analyze the runtime error, inspect project files, and fix the issue."
        )

        if gemini_provider is not None and provider in {None, "gemini"}:
            files_before = _snapshot_project_files(project_root)
            provider_failed = False
            try:
                output = run_agent(project_root, prompt, gemini_provider, settings.max_tool_calls, runner=runner)
                print(output)
            except ProviderError as exc:
                provider_failed = True
                print(f"\n⚠ Gemini API error: {exc}")
                print("Retry attempts exhausted or provider failure occurred.")

            files_after = _snapshot_project_files(project_root)
            files_changed = files_before != files_after

            if files_changed:
                repairs_performed += 1

            if provider_failed:
                if files_changed:
                    print("\n[Notice] Files were modified, but AI provider encountered an error.")
                    post_run = runner.run_project(project_root)
                    if post_run.success:
                        return f"✓ Godot verification passed\n✓ {repairs_performed} repair(s) performed\n✓ Project completed successfully"
                    return f"⚠ AI provider failed and Godot verification still failed:\n{post_run.stderr or post_run.stdout}"
                return f"⚠ Repair stopped due to Gemini API error: {last_errors}"
            elif not files_changed:
                print("\n[Notice] AI agent did not modify any project files on this attempt.")
        else:
            return f"Repair requires Gemini provider with function calling capability. Stderr: {run_res.stderr}"

    # Final check after max attempts
    final_run = runner.run_project(project_root)
    if final_run.success:
        return f"✓ Godot verification passed\n✓ {repairs_performed} repair(s) performed\n✓ Project completed successfully"

    return f"Repair limit reached ({settings.max_repair_attempts} attempts). The project still has errors:\n{final_run.stderr or final_run.stdout}"


def run(project_root: str | Path, prompt: str, complexity: str, provider: str | None, router: LLMRouter | None = None) -> str:
    settings = Settings.from_env()
    providers = build_providers(settings)
    if router is None and provider in {None, "gemini"} and "gemini" in providers:
        return run_agent(project_root, prompt, providers["gemini"], settings.max_tool_calls)
    active_router = router or LLMRouter(providers)
    request = build_request(project_root, prompt)
    response = asyncio.run(active_router.generate(request, TaskComplexity(complexity), provider=provider))
    return response.text


def run_interactive(project_root: str | Path, complexity: str, provider: str | None) -> None:
    print("RBXForge")
    print(f"Godot project: {Path(project_root).resolve()}")
    print("Type 'exit' or 'quit' to leave interactive mode.")
    while True:
        try:
            prompt = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        prompt = prompt.strip()
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            return
        try:
            print(run(project_root, prompt, complexity, provider))
        except (ValueError, ProviderError) as exc:
            print(f"error: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RBXForge - AI development assistant for Godot projects")
    parser.add_argument("prompt", nargs="?", default=None, help="Question or task for the AI. Omit to start interactive mode.")
    parser.add_argument("--project", default=None, help="Path to a Godot project containing project.godot (defaults to the nearest one found from the current directory)")
    parser.add_argument("--complexity", choices=[item.value for item in TaskComplexity], default=None)
    parser.add_argument("--provider", choices=["ollama", "gemini"], default=None)
    parser.add_argument("--check", action="store_true", help="Validate/load Godot project in headless mode without executing main scene")
    parser.add_argument("--run", action="store_true", help="Run Godot project main scene in headless mode and capture execution errors")
    parser.add_argument("--repair", action="store_true", help="Run AI-assisted Godot verification and repair loop")
    return parser


def resolve_project_root(parser: argparse.ArgumentParser, project_flag: str | None) -> Path:
    if project_flag is not None:
        root = Path(project_flag).expanduser().resolve()
        if not (root / "project.godot").is_file():
            parser.error(f"Invalid Godot project: missing project.godot in {root}")
        return root
    root = find_godot_project_root()
    if root is None:
        parser.error("Could not find project.godot. Run this command inside a Godot project or one of its subdirectories.")
    return root


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    complexity = args.complexity or settings.default_complexity.value
    project_root = resolve_project_root(parser, args.project)

    if args.check:
        print(run_check(project_root, settings))
        return

    if args.run:
        print(run_project_cmd(project_root, settings))
        return

    if args.repair:
        print(run_repair(project_root, settings, args.provider))
        return

    if args.prompt is None:
        run_interactive(project_root, complexity, args.provider)
        return
    try:
        print(run(project_root, args.prompt, complexity, args.provider))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()