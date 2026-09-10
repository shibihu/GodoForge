# Godot File Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe Godot file-agent layer that lets RBXForge inspect project files automatically and mutate files only after explicit confirmation.

**Architecture:** Keep `GodotProjectAnalyzer` for project discovery/context and add a focused filesystem service plus provider-neutral tool contracts. The service resolves every path inside the Godot project, exposes deterministic read/search operations, and requires an injected confirmation callback for create/write/delete operations. Gemini integration consumes the tool layer rather than implementing filesystem access itself.

**Tech Stack:** Python 3.11+, pathlib, dataclasses, pytest, existing `google-genai` Gemini provider, existing setuptools console entry point.

**Spec:** `docs/superpowers/specs/2026-09-10-godot-file-agent-design.md`

## Global Constraints

- Python requirement remains `>=3.11`.
- The project remains usable from Termux and the `rbxforge "your prompt"` CLI remains the primary interface.
- Read-only tools require no confirmation.
- `create_file`, `write_file`, and `delete_file` always require confirmation.
- Agent paths must remain inside the resolved Godot project root.
- `.godot`, `.git`, `bin`, and `obj` are inaccessible to file-agent operations.
- `project.godot` can be read but cannot be deleted.
- Existing analyzer, Gemini, router, and CLI behavior must not be removed.
- No live Gemini API call is required for unit tests.

---

### Task 1: Add the secure filesystem service

**Files:**
- Create: `src/rbxforge/godot/files.py`
- Test: `tests/test_godot_files.py`

**Interfaces:**
- Produces `GodotFileService(root: str | Path, max_file_bytes: int = 200_000)`.
- Produces `list_files(relative_dir: str | Path = ".") -> list[str]`.
- Produces `read_file(relative_path: str | Path) -> str`.
- Produces `search_code(query: str, relative_dir: str | Path = ".") -> list[CodeMatch]`.
- Produces `create_file(relative_path: str | Path, content: str, confirm: Confirmation) -> OperationResult`.
- Produces `write_file(relative_path: str | Path, content: str, confirm: Confirmation) -> OperationResult`.
- Produces `delete_file(relative_path: str | Path, confirm: Confirmation) -> OperationResult`.
- Produces `FileToolError(ValueError)` for controlled tool failures.
- Produces `CodeMatch(path: str, line: int, text: str)` and `OperationResult(operation: str, path: str, changed: bool, backup_path: str | None = None)` dataclasses.
- `Confirmation` is `Callable[[str, str, str], bool]`.

- [ ] **Step 1: Write failing path-safety and read tests**

```python
def test_read_file_and_reject_parent_traversal(tmp_path):
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text("[application]\n", encoding="utf-8")
    (project / "player.gd").write_text("extends Node\n", encoding="utf-8")
    (tmp_path / "outside.gd").write_text("secret\n", encoding="utf-8")

    service = GodotFileService(project)
    assert service.read_file("player.gd") == "extends Node\n"
    with pytest.raises(FileToolError):
        service.read_file("../outside.gd")
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python -m pytest tests/test_godot_files.py -q
```

Expected: FAIL because `rbxforge.godot.files` and its service do not exist yet.

- [ ] **Step 3: Implement root validation and safe path resolution**

Use `Path.resolve(strict=False)`, compare the candidate with the resolved root using `candidate == root or root in candidate.parents`, reject inaccessible generated directories in any path component, reject symlinked paths that resolve outside the root, and reject a non-directory project root or missing `project.godot`.

- [ ] **Step 4: Implement bounded `read_file`**

Open the resolved file in binary mode, read at most `max_file_bytes`, decode UTF-8 with `errors="replace"`, and raise `FileToolError` for missing files, directories, permission errors, or invalid arguments.

- [ ] **Step 5: Run the focused test again**

Run:

```bash
python -m pytest tests/test_godot_files.py -q
```

Expected: PASS for the read and traversal tests.

- [ ] **Step 6: Commit the service baseline**

```bash
git add src/rbxforge/godot/files.py tests/test_godot_files.py
git commit -m "feat: add safe Godot file service"
```

---

### Task 2: Add deterministic listing and code search

**Files:**
- Modify: `src/rbxforge/godot/files.py`
- Modify: `tests/test_godot_files.py`

**Interfaces:**
- `list_files()` returns sorted project-relative paths for supported agent-visible files.
- `search_code()` returns sorted `CodeMatch` values with one-based line numbers.

- [ ] **Step 1: Write failing listing/search tests**

```python
def test_list_files_is_sorted_and_ignores_generated_dirs(tmp_path):
    project = make_project(tmp_path)
    (project / "z.gd").write_text("z", encoding="utf-8")
    (project / "a.gd").write_text("needle", encoding="utf-8")
    generated = project / ".godot"
    generated.mkdir()
    (generated / "hidden.gd").write_text("needle", encoding="utf-8")

    service = GodotFileService(project)
    assert service.list_files() == ["a.gd", "project.godot", "z.gd"]


def test_search_code_returns_line_numbers(tmp_path):
    project = make_project(tmp_path)
    (project / "player.gd").write_text("extends Node\nmove_and_slide()\n", encoding="utf-8")
    service = GodotFileService(project)

    matches = service.search_code("move_and_slide")

    assert [(m.path, m.line, m.text) for m in matches] == [
        ("player.gd", 2, "move_and_slide()")
    ]
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_godot_files.py -q
```

Expected: FAIL because listing/search behavior is not implemented.

- [ ] **Step 3: Implement deterministic listing**

Walk from the resolved root without following symlinks, skip `.godot`, `.git`, `bin`, and `obj`, and return sorted POSIX relative paths. Include normal project files needed by an agent, including scripts, scenes, resources, project metadata, and text/config files; do not read file contents during listing.

- [ ] **Step 4: Implement bounded code search**

Search `.gd`, `.tscn`, and `.tres` files. Read bounded bytes, split with `splitlines()`, perform a case-sensitive substring search, and emit `CodeMatch` for every matching line. Sort by path then line.

- [ ] **Step 5: Run the focused tests**

Run:

```bash
python -m pytest tests/test_godot_files.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/rbxforge/godot/files.py tests/test_godot_files.py
git commit -m "feat: add Godot file listing and code search"
```

---

### Task 3: Add confirmation-gated create/write/delete operations

**Files:**
- Modify: `src/rbxforge/godot/files.py`
- Modify: `tests/test_godot_files.py`

**Interfaces:**
- Every mutation receives `confirm(operation, path, details) -> bool`.
- A denied operation returns `OperationResult(..., changed=False)` and leaves the filesystem untouched.
- An approved create returns `changed=True`.
- An approved write creates `<filename>.rbxforge.bak` before replacement when the target exists.
- An approved delete returns `changed=True` unless the target does not exist, in which case it raises `FileToolError`.

- [ ] **Step 1: Write failing confirmation tests**

```python
def test_create_requires_confirmation(tmp_path):
    project = make_project(tmp_path)
    service = GodotFileService(project)

    denied = service.create_file("health.gd", "extends Node\n", lambda *_: False)
    assert denied.changed is False
    assert not (project / "health.gd").exists()

    approved = service.create_file("health.gd", "extends Node\n", lambda *_: True)
    assert approved.changed is True
    assert (project / "health.gd").read_text(encoding="utf-8") == "extends Node\n"


def test_write_creates_backup_after_confirmation(tmp_path):
    project = make_project(tmp_path)
    target = project / "player.gd"
    target.write_text("old\n", encoding="utf-8")
    service = GodotFileService(project)

    result = service.write_file("player.gd", "new\n", lambda *_: True)

    assert result.changed is True
    assert target.read_text(encoding="utf-8") == "new\n"
    assert (project / "player.gd.rbxforge.bak").read_text(encoding="utf-8") == "old\n"


def test_delete_never_deletes_project_manifest(tmp_path):
    project = make_project(tmp_path)
    service = GodotFileService(project)
    with pytest.raises(FileToolError):
        service.delete_file("project.godot", lambda *_: True)
    assert (project / "project.godot").exists()
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_godot_files.py -q
```

Expected: FAIL because mutation methods are not implemented.

- [ ] **Step 3: Implement confirmation-gated create**

Validate the target as a file path, reject existing files/directories, construct details containing the operation and relative path, call `confirm("create_file", relative_path, details)`, and only create parent directories and write content after approval.

- [ ] **Step 4: Implement confirmation-gated write with backup**

Reject directories and inaccessible paths. For an existing file, read its bounded old content, create a backup named `<original>.rbxforge.bak` before replacing the target, then atomically replace the target using a temporary file in the same directory and `Path.replace()` after approval. Return the backup path in `OperationResult`.

- [ ] **Step 5: Implement confirmation-gated delete**

Reject `project.godot`, generated/internal paths, directories, and missing targets. Call confirmation before `unlink()` and never delete if confirmation returns false.

- [ ] **Step 6: Run the focused tests**

Run:

```bash
python -m pytest tests/test_godot_files.py -q
```

Expected: PASS, including approval and denial cases.

- [ ] **Step 7: Commit**

```bash
git add src/rbxforge/godot/files.py tests/test_godot_files.py
git commit -m "feat: gate Godot file mutations behind confirmation"
```

---

### Task 4: Add provider-neutral tool schemas and execution wrapper

**Files:**
- Create: `src/rbxforge/core/tools.py`
- Create: `tests/test_tools.py`
- Modify: `src/rbxforge/godot/files.py` only if a small adapter is required

**Interfaces:**
- `ToolDefinition(name: str, description: str, parameters: dict, read_only: bool)`.
- `ToolCall(name: str, arguments: dict)`.
- `ToolResult(name: str, ok: bool, data: dict | list | str | None = None, error: str | None = None)`.
- `GodotToolExecutor(service: GodotFileService, confirm: Confirmation)`.
- `GodotToolExecutor.definitions() -> list[ToolDefinition]`.
- `GodotToolExecutor.execute(call: ToolCall) -> ToolResult`.

- [ ] **Step 1: Write failing tool-dispatch tests**

```python
def test_tool_executor_dispatches_read_file(tmp_path):
    project = make_project(tmp_path)
    (project / "player.gd").write_text("extends Node\n", encoding="utf-8")
    executor = GodotToolExecutor(GodotFileService(project), lambda *_: False)

    result = executor.execute(ToolCall("read_file", {"path": "player.gd"}))

    assert result.ok is True
    assert result.data == "extends Node\n"


def test_tool_executor_does_not_bypass_confirmation(tmp_path):
    project = make_project(tmp_path)
    executor = GodotToolExecutor(GodotFileService(project), lambda *_: False)

    result = executor.execute(ToolCall("delete_file", {"path": "player.gd"}))

    assert result.ok is False or result.data is not None
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_tools.py -q
```

Expected: FAIL because the tool contracts/executor do not exist.

- [ ] **Step 3: Implement immutable tool schemas**

Define the six tool names and JSON-schema-like parameter dictionaries. Mark only `list_files`, `read_file`, and `search_code` as read-only.

- [ ] **Step 4: Implement dispatch**

Map each tool name to the corresponding `GodotFileService` method, validate required arguments, convert exceptions to `ToolResult(ok=False, error=...)`, and pass the injected confirmation callback to mutation methods. Reject unknown tools with a controlled error.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python -m pytest tests/test_tools.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/rbxforge/core/tools.py tests/test_tools.py src/rbxforge/godot/files.py
git commit -m "feat: add provider-neutral Godot tool executor"
```

---

### Task 5: Integrate tool context into the Gemini agent flow

**Files:**
- Modify: `src/rbxforge/core/router.py` or the existing agent orchestration module, using the smallest existing integration point.
- Modify: `src/rbxforge/providers/gemini/provider.py` only if the current Gemini SDK integration requires tool-call translation.
- Modify: `src/rbxforge/main.py` to construct the executor and CLI confirmation function.
- Create/modify: `tests/test_agent_tools.py`

**Interfaces:**
- The Gemini-facing layer receives `list[ToolDefinition]` and can execute returned `ToolCall` values through `GodotToolExecutor`.
- The CLI confirmation function displays operation/path/details and returns a boolean from `input()`.
- Tool calls are bounded by a configurable maximum, default `12`, and mutation calls always pass through confirmation.

- [ ] **Step 1: Write failing integration tests**

```python
def test_agent_tool_definitions_are_available(tmp_path):
    project = make_project(tmp_path)
    executor = GodotToolExecutor(GodotFileService(project), lambda *_: True)
    names = [item.name for item in executor.definitions()]
    assert names == [
        "list_files",
        "read_file",
        "search_code",
        "create_file",
        "write_file",
        "delete_file",
    ]
```

Also add a fake-model test proving a returned `read_file` call is executed and its result is fed back into the model loop, while a returned `write_file` call cannot mutate when the fake confirmation returns false.

- [ ] **Step 2: Run the integration tests and verify they fail**

Run:

```bash
python -m pytest tests/test_agent_tools.py -q
```

Expected: FAIL until the agent integration exists.

- [ ] **Step 3: Integrate tool definitions at the existing Gemini request boundary**

Keep filesystem logic out of the Gemini provider. Translate provider-specific function/tool-call messages into `ToolCall` and translate `ToolResult` back into model-visible tool results. If the installed `google-genai` version exposes native function calling, use its supported structured tool schema; otherwise retain a provider-neutral adapter so unit tests remain offline.

- [ ] **Step 4: Add the CLI confirmation function**

Display:

```text
RBXForge wants to <operation>:

<path>

<details>

Apply this change? [y/N]:
```

Treat only `y`/`yes` case-insensitively as approval. Empty input and all other responses deny.

- [ ] **Step 5: Add bounded tool-call looping**

Allow up to 12 tool calls for one user request. Stop with a controlled message when the limit is reached. Never retry a denied mutation automatically.

- [ ] **Step 6: Run integration tests**

Run:

```bash
python -m pytest tests/test_agent_tools.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/rbxforge/core src/rbxforge/providers/gemini/provider.py src/rbxforge/main.py tests/test_agent_tools.py
git commit -m "feat: integrate Godot tools with Gemini agent"
```

---

### Task 6: Regression tests, documentation, and CLI verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example` only if a tool-call limit setting is added.
- Modify: existing tests only when assertions need updating for preserved behavior.

**Interfaces:**
- Primary CLI remains `rbxforge "your prompt"`.
- Existing `--project` override remains supported.

- [ ] **Step 1: Run the complete test suite before documentation changes**

Run:

```bash
python -m pytest -q
```

Expected: all existing and new tests pass.

- [ ] **Step 2: Update README with Phase 1 behavior**

Document the primary command:

```bash
cd ~/storage/shared/Documents/MyGame
rbxforge "Find my player script and explain movement"
```

Document that the agent can inspect files automatically and that create/write/delete operations ask for confirmation. Document the `.rbxforge.bak` backup behavior for overwrites and explain that Phase 2 will add Godot execution/error feedback.

- [ ] **Step 3: Run compile verification**

Run:

```bash
python -m compileall -q src
```

Expected: no output and exit code 0.

- [ ] **Step 4: Verify CLI help**

Run:

```bash
rbxforge --help
```

Expected: help output exits successfully and shows the positional prompt and optional `--project` behavior.

- [ ] **Step 5: Verify real project invocation**

Run from a real Godot project:

```bash
cd /path/to/your/godot/project && rbxforge "test prompt"
```

Expected: RBXForge detects the project via `project.godot`, performs the Gemini request, and does not require `PYTHONPATH=src`.

- [ ] **Step 6: Commit documentation and final verification**

```bash
git add README.md .env.example tests src

git commit -m "docs: document Godot file agent"
```

Then rerun:

```bash
python -m pytest -q
python -m compileall -q src
rbxforge --help
```

Expected: all tests pass, compilation succeeds, and CLI help succeeds.
