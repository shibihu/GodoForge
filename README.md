# RBXForge

RBXForge is an AI development command center for **Godot** projects. It combines Godot-aware project analysis with a safe file-agent layer and optional Gemini tool calling so the AI can inspect project files and, with your confirmation, create, edit, or delete them.

## Current Phase 1

RBXForge can now:
- detect the nearest `project.godot`
- inspect project structure and Godot context
- list project files automatically
- read bounded text files automatically
- search `.gd`, `.tscn`, and `.tres` code with line numbers
- create files after explicit confirmation
- replace files after explicit confirmation
- create `<file>.rbxforge.bak` before overwriting an existing file
- delete files after explicit confirmation
- reject `..` traversal, symlink escapes, and generated/internal directories
- protect `project.godot` from deletion

For the file-agent workflow, Gemini is used when it is configured. Existing Ollama/router behavior remains available when tool calling is not selected.

The file-agent flow is:

```text
Your prompt
    │
    ▼
Gemini + Godot tools
    │
    ├── read/search → automatic
    │
    └── create/write/delete → confirmation
                              │
                              ▼
                         project files
```

## Phase 2: Godot Runtime Verification + AI Debugging & Repair Loop

Phase 2 adds headless Godot runtime verification and an AI-assisted repair loop.

### Phase 2 Features
- **Headless Godot Execution**: Run your Godot project in headless mode via `rbxforge --check`.
- **Error Parser**: Automatically extract structured diagnostics (file, line, column, error message, severity) from Godot 4 logs.
- **`run_godot` Tool**: Read-only tool allowing the AI agent to run Godot during conversation to verify script behavior.
- **AI Repair Loop**: Use `rbxforge --repair` to automatically execute Godot, capture runtime errors, inspect source files, apply targeted fixes with mandatory user confirmation, and re-verify until success or the attempt limit is reached.
- **Safety & Confirmation**: Mutation tools (`create_file`, `write_file`, `delete_file`) remain strictly protected and require user confirmation before applying fixes.

### Phase 2 Configuration Environment Variables
- `GODOFORGE_GODOT_PATH` (default: `godot`): Path to Godot 4 executable.
- `GODOFORGE_GODOT_TIMEOUT` (default: `30`): Maximum process execution timeout in seconds.
- `GODOFORGE_MAX_REPAIR_ATTEMPTS` (default: `3`): Maximum repair attempts during `--repair`.

### Phase 2 Usage

Run a headless check on the Godot project:
```bash
rbxforge --check
```

Run AI-assisted repair loop:
```bash
rbxforge --repair
```

### Phase 2 Limitations
Phase 2 does **NOT** provide:
- Godot Editor UI control
- Scene Tree live control
- Inspector automation
- Visual gameplay testing or mouse/keyboard input automation

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .venv\\Scripts\\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env
```

Set `GEMINI_API_KEY` and `GEMINI_MODEL` when you want the file-agent workflow. `RBXFORGE_MAX_TOOL_CALLS` defaults to `12`. Ollama uses `RBXFORGE_OLLAMA_BASE_URL` and `RBXFORGE_OLLAMA_MODEL`.

## CLI

After installing with `pip install -e .`, `rbxforge` is a real command on your PATH — no `PYTHONPATH` or `python -m` needed.

Run it from inside a Godot project (or any of its subdirectories). RBXForge walks upward from the current directory until it finds `project.godot` and uses that as the project root:

```bash
cd ~/storage/shared/Documents/MyGame
rbxforge "Why is my player movement not working?"

# also works from a subdirectory
cd ~/storage/shared/Documents/MyGame/scripts/player
rbxforge "Fix the player script"
```

If no `project.godot` is found in the current directory or its parents, you'll see:

```text
Could not find project.godot. Run this command inside a Godot project or one of its subdirectories.
```

You can explicitly point at a different project with `--project`:

```bash
rbxforge --project /path/to/my-godot-game "Explain the Player scene"
```

Select a complexity or provider explicitly with `--complexity` and `--provider`:

```bash
rbxforge --complexity simple --provider ollama "Explain the Player scene"
```

### File-agent example

```bash
cd ~/storage/shared/Documents/MyGame
rbxforge "Create a player script at scripts/player.gd with basic CharacterBody2D movement"
```

For a mutation, RBXForge will show the target path and ask:

```text
RBXForge wants to create_file:

scripts/player.gd

...details...

Apply this change? [y/N]:
```

Only `y` or `yes` applies the change. Overwrites create a `.rbxforge.bak` backup first.

### Interactive mode

Run `rbxforge` with no prompt to start an interactive session. It picks the Godot project from the current directory, then lets you ask questions one after another:

```text
RBXForge
Godot project: /path/to/my-godot-game
> Fix player movement
> Add a health system
> Explain this error
```

Type `exit` or `quit` to leave interactive mode.

## Godot files understood

- `project.godot` — project manifest and project name
- `.gd` — GDScript files
- `.tscn` — text scenes; node and external-resource metadata
- `.tres` — text resources and references

Generated directories such as `.godot`, `.git`, `bin`, and `obj` are ignored. File reads are bounded to prevent huge files from consuming AI context.

## Tests

```bash
pytest -q
python -m compileall -q src
```

## Roadmap

**Phase 2:** run Godot, capture runtime/editor errors, and feed them back into the agent.

**Phase 3:** Godot Editor Plugin/local bridge for live Scene Tree and editor actions.
