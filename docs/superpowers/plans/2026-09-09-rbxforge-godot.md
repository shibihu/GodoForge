# RBXForge Godot Development Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a file-based Godot project analyzer to RBXForge and retarget the AI context layer from Roblox concepts to Godot concepts while retaining the multi-LLM architecture.

**Architecture:** The existing provider/router layer remains independent. A new `GodotProjectAnalyzer` scans a project root, extracts project/scenes/scripts/resources metadata, and builds a bounded context string that can be attached to an LLM request. A CLI command exposes project analysis without requiring a live Godot editor.

**Tech Stack:** Python 3.11+, pathlib, dataclasses, pytest, pytest-asyncio, existing httpx/google-genai provider stack.

**Spec:** `docs/superpowers/specs/2026-09-09-rbxforge-godot-design.md`

## Global Constraints

- Godot integration is file-based; no Godot Editor Plugin is included in this phase.
- No test requires a Godot installation, Ollama server, or Gemini API key.
- Project scanning must not follow symlinks outside the project root.
- `.godot`, `.git`, `bin`, and `obj` directories are excluded.
- File reads are UTF-8 with replacement and bounded by `max_file_bytes`.

---

### Task 1: Replace Roblox-oriented project documentation with Godot MVP documentation

**Files:**
- Modify: `README.md`
- Create: `.env.example`
- Create: `pyproject.toml`

**Interfaces:**
- Documents the public CLI and Python package setup used by later tasks.

- [ ] **Step 1: Write the failing documentation smoke test**

Create `tests/test_project_docs.py` that asserts README names Godot and does not instruct users to analyze Luau/Roblox projects.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_project_docs.py -q`
Expected: FAIL because the current README is Roblox-oriented and `pyproject.toml` is absent.

- [ ] **Step 3: Write minimal project metadata and documentation**

Add package metadata for Python 3.11+, runtime dependencies `httpx`, `python-dotenv`, `google-genai`, and dev dependencies `pytest`, `pytest-asyncio`. Document Godot setup and CLI usage.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_project_docs.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md .env.example pyproject.toml tests/test_project_docs.py
git commit -m "docs: retarget RBXForge for Godot"
```

### Task 2: Create the Godot project analyzer contract

**Files:**
- Create: `src/rbxforge/godot/models.py`
- Create: `src/rbxforge/godot/analyzer.py`
- Test: `tests/test_godot_analyzer.py`

**Interfaces:**
- Produces `GodotProject`, `GodotFile`, `GodotScene`, and `GodotProjectAnalyzer.scan()`.

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path
from rbxforge.godot.analyzer import GodotProjectAnalyzer


def test_scan_requires_project_manifest(tmp_path: Path):
    try:
        GodotProjectAnalyzer(tmp_path).scan()
    except ValueError as exc:
        assert "project.godot" in str(exc)
    else:
        raise AssertionError("expected invalid project error")


def test_scan_discovers_godot_files_and_ignores_generated_dirs(tmp_path: Path):
    (tmp_path / "project.godot").write_text("[application]\nconfig/name=\"Demo\"\n", encoding="utf-8")
    (tmp_path / "player.gd").write_text("extends CharacterBody2D\n", encoding="utf-8")
    (tmp_path / "main.tscn").write_text("[gd_scene load_steps=2]\n", encoding="utf-8")
    (tmp_path / "data.tres").write_text("[gd_resource type=\"Resource\"]\n", encoding="utf-8")
    generated = tmp_path / ".godot"
    generated.mkdir()
    (generated / "ignored.gd").write_text("extends Node\n", encoding="utf-8")

    project = GodotProjectAnalyzer(tmp_path).scan()

    assert project.name == "Demo"
    assert {item.path for item in project.files} == {"player.gd", "main.tscn", "data.tres"}


def test_scene_extracts_nodes_and_external_resources(tmp_path: Path):
    (tmp_path / "project.godot").write_text("[application]\nconfig/name=\"Demo\"\n", encoding="utf-8")
    scene = '''[gd_scene load_steps=3]\n\n[ext_resource type=\"Script\" path=\"res://player.gd\" id=\"1\"]\n[ext_resource type=\"Texture2D\" path=\"res://player.png\" id=\"2\"]\n\n[node name=\"Player\" type=\"CharacterBody2D\"]\nscript = ExtResource(\"1\")\n\n[node name=\"Sprite\" type=\"Sprite2D\" parent=\".\"]\ntexture = ExtResource(\"2\")\n'''
    (tmp_path / "main.tscn").write_text(scene, encoding="utf-8")

    project = GodotProjectAnalyzer(tmp_path).scan()
    parsed = next(item for item in project.scenes if item.path == "main.tscn")

    assert "Player" in parsed.nodes
    assert "Sprite" in parsed.nodes
    assert "res://player.gd" in parsed.external_resources
    assert "res://player.png" in parsed.external_resources
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_godot_analyzer.py -q`
Expected: FAIL because the analyzer package does not exist.

- [ ] **Step 3: Implement the minimal analyzer**

Implement typed dataclasses and `GodotProjectAnalyzer(root, max_file_bytes=200_000)`. Parse the project name from `config/name`, discover supported files while skipping excluded directories, and parse `.tscn` node/resource lines.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_godot_analyzer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rbxforge/godot tests/test_godot_analyzer.py
git commit -m "feat: add Godot project analyzer"
```

### Task 3: Add bounded AI context generation for Godot projects

**Files:**
- Modify: `src/rbxforge/godot/analyzer.py`
- Test: `tests/test_godot_context.py`

**Interfaces:**
- `GodotProjectAnalyzer.build_context(project, max_chars=12000) -> str`.

- [ ] **Step 1: Write failing context tests**

```python
from pathlib import Path
from rbxforge.godot.analyzer import GodotProjectAnalyzer


def test_context_contains_project_scene_and_script_information(tmp_path: Path):
    (tmp_path / "project.godot").write_text("[application]\nconfig/name=\"Context Demo\"\n", encoding="utf-8")
    (tmp_path / "player.gd").write_text("extends CharacterBody2D\nfunc _physics_process(delta):\n    pass\n", encoding="utf-8")
    (tmp_path / "main.tscn").write_text("[node name=\"Player\" type=\"CharacterBody2D\"]\n", encoding="utf-8")

    analyzer = GodotProjectAnalyzer(tmp_path)
    project = analyzer.scan()
    context = analyzer.build_context(project, max_chars=2000)

    assert "Context Demo" in context
    assert "player.gd" in context
    assert "main.tscn" in context
    assert "CharacterBody2D" in context


def test_context_respects_character_limit(tmp_path: Path):
    (tmp_path / "project.godot").write_text("[application]\nconfig/name=\"Demo\"\n", encoding="utf-8")
    (tmp_path / "large.gd").write_text("# x\n" * 10000, encoding="utf-8")

    analyzer = GodotProjectAnalyzer(tmp_path)
    context = analyzer.build_context(analyzer.scan(), max_chars=500)

    assert len(context) <= 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_godot_context.py -q`
Expected: FAIL because `build_context` is not implemented.

- [ ] **Step 3: Implement context generation**

Include project name, file inventory, scene node/resource summaries, and short script/resource content. Truncate deterministically at `max_chars`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_godot_context.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rbxforge/godot/analyzer.py tests/test_godot_context.py
git commit -m "feat: build bounded Godot AI context"
```

### Task 4: Restore and extend the multi-LLM core for Godot prompts

**Files:**
- Create: `src/rbxforge/core/llm/models.py`
- Create: `src/rbxforge/core/llm/errors.py`
- Create: `src/rbxforge/core/llm/base.py`
- Create: `src/rbxforge/core/router.py`
- Create: `src/rbxforge/providers/ollama/provider.py`
- Create: `src/rbxforge/providers/gemini/provider.py`
- Create: `src/rbxforge/providers/registry.py`
- Create: `src/rbxforge/config.py`
- Test: `tests/test_router.py`
- Test: `tests/test_config.py`

**Interfaces:**
- `LLMRequest`, `LLMResponse`, `Message`, `Usage`, `TaskComplexity`.
- `LLMProvider.generate()` and `.health()`.
- `LLMRouter.generate(request, complexity, provider=None)`.
- `Settings.from_env()` and `build_providers(settings)`.

- [ ] **Step 1: Write failing router/config tests**

Test simple/moderate/complex routing, retryable fallback, explicit provider selection, and environment-backed defaults.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_router.py tests/test_config.py -q`
Expected: FAIL because the LLM core modules do not exist in this checkout.

- [ ] **Step 3: Implement the normalized LLM core and providers**

Use the provider behavior from the previously approved RBXForge architecture: simple → Ollama, moderate → Ollama then Gemini, complex → Gemini then Ollama; retryable `ProviderError` triggers fallback while non-retryable errors stop the request.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_router.py tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rbxforge/core src/rbxforge/providers src/rbxforge/config.py tests/test_router.py tests/test_config.py
git commit -m "feat: restore multi-LLM router"
```

### Task 5: Connect the CLI to Godot project context

**Files:**
- Create: `src/rbxforge/main.py`
- Create: `src/rbxforge/__init__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- CLI accepts `--project`, `--prompt`, `--complexity`, and optional `--provider`.

- [ ] **Step 1: Write failing CLI tests**

Test that a temporary Godot project can be analyzed and that the CLI constructs an LLM request containing the bounded Godot context. Provider calls are replaced with a deterministic fake provider.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -q`
Expected: FAIL because the CLI does not exist.

- [ ] **Step 3: Implement CLI integration**

Load settings, scan `--project`, append analyzer context to the user prompt, route the request, and print the response text. Return a clear error for invalid projects.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rbxforge/main.py src/rbxforge/__init__.py tests/test_cli.py
git commit -m "feat: add Godot-aware RBXForge CLI"
```

### Task 6: Full verification and package artifact

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Run the complete test suite**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Run Python compilation**

Run: `python -m compileall -q src`
Expected: exit code 0 and no compilation errors.

- [ ] **Step 3: Run the CLI help smoke test**

Run: `PYTHONPATH=src python -m rbxforge.main --help`
Expected: help text lists `--project`, `--prompt`, `--complexity`, and `--provider`.

- [ ] **Step 4: Create the distributable ZIP**

Run: `zip -r RBXForge-Godot-MVP.zip README.md .env.example .gitignore pyproject.toml docs src tests`
Expected: a ZIP containing the source, tests, documentation, and configuration.

- [ ] **Step 5: Commit**

```bash
git add README.md .gitignore
git commit -m "chore: finalize Godot MVP"
```
