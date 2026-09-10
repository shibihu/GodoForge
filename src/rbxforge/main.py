from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .config import Settings
from .core.llm.errors import ProviderError
from .core.agent import ToolAgent
from .core.llm.models import LLMRequest, Message, TaskComplexity
from .core.tools import GodotToolExecutor
from .core.router import LLMRouter
from .godot.analyzer import GodotProjectAnalyzer
from .godot.files import GodotFileService
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
        "You are RBXForge, an AI assistant for Godot development. "
        "Use the following project context when relevant.\n\n"
        f"{context}\n\n[User Request]\n{prompt}"
    )
    return LLMRequest([Message("user", content)])


def confirm_tool_action(operation: str, path: str, details: str) -> bool:
    print(f"RBXForge wants to {operation}:\n")
    print(path)
    print()
    print(details)
    answer = input("Apply this change? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def run_agent(project_root: str | Path, prompt: str, gemini_provider, max_tool_calls: int = 12) -> str:
    request = build_request(project_root, prompt)
    service = GodotFileService(project_root)
    executor = GodotToolExecutor(service, confirm_tool_action)
    agent = ToolAgent(
        lambda req, tools: gemini_provider.generate_with_tools(req, tools),
        max_tool_calls=max_tool_calls,
    )
    response = asyncio.run(agent.run(request, executor))
    return response.text


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
    settings = Settings.from_env()
    complexity = args.complexity or settings.default_complexity.value
    project_root = resolve_project_root(parser, args.project)
    if args.prompt is None:
        run_interactive(project_root, complexity, args.provider)
        return
    try:
        print(run(project_root, args.prompt, complexity, args.provider))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()