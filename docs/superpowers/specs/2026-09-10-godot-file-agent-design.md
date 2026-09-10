# Godot File Agent Design

**Date:** 2026-09-10
**Status:** Approved by user

## Goal

Add a safe file-operation layer to RBXForge so Gemini can inspect and propose changes to a Godot project, while read-only operations run automatically and destructive/mutating operations require explicit user confirmation.

## Scope

Phase 1 includes six tools:

- `list_files`
- `read_file`
- `search_code`
- `create_file`
- `write_file`
- `delete_file`

Phase 1 does not include running Godot, reading runtime logs, controlling the Godot Editor, or autonomous repair loops. Those are Phase 2/3 features.

## Architecture

The existing `GodotProjectAnalyzer` remains responsible for project discovery and Godot-aware analysis. A new `GodotFileAgent`/tool layer will own safe filesystem operations relative to a resolved project root. The Gemini-facing agent layer will invoke read-only tools automatically and route mutations through a confirmation callback/interface.

All tool paths are project-relative or resolved against the project root. A canonical-path containment check must reject paths outside the project, including `..` traversal and symlink escapes.

## Tool Contracts

### `list_files`

Input: optional relative directory, default `.`.

Output: deterministic list of project-relative paths. Ignore generated/internal directories already ignored by the analyzer (`.godot`, `.git`, `bin`, `obj`). Do not follow symlinked files or directories.

Read-only: yes.

### `read_file`

Input: project-relative path.

Output: UTF-8 text using replacement for invalid bytes, bounded by the configured maximum file size. Missing files and directories return controlled tool errors.

Read-only: yes.

### `search_code`

Input: text query and optional relative directory. Search supported Godot source/resource files (`.gd`, `.tscn`, `.tres`) and return deterministic matches containing path, line number, and matching line. Search is bounded by the same safety/size rules as file reads.

Read-only: yes.

### `create_file`

Input: relative path and complete file content.

Behavior: reject existing targets; validate parent path; request confirmation; create only after approval. Create parent directories only after approval.

Mutation: yes, confirmation required.

### `write_file`

Input: relative path and complete replacement content.

Behavior: reject directories; request confirmation showing the target and a concise before/after summary; before overwriting an existing file, create a `.rbxforge.bak` backup next to it. The backup is replaced atomically for subsequent writes. Write only after approval.

Mutation: yes, confirmation required.

### `delete_file`

Input: relative file path.

Behavior: reject directories and protected project metadata; request confirmation with an explicit irreversible warning; delete only after approval.

Mutation: yes, confirmation required.

## Confirmation Interface

The core file layer must not directly depend on terminal `input()`. It receives a confirmation callable/interface so CLI code can render prompts while tests can provide deterministic approval/denial.

Conceptually:

```python
confirm(operation: str, path: str, details: str) -> bool
```

Read-only tools never call it.

## Safety Rules

1. Every path must resolve beneath the project root.
2. Absolute paths supplied by a tool caller are rejected unless they resolve inside the project root; project-relative paths are preferred.
3. Symlink targets must not escape the project root.
4. Generated/internal directories `.godot`, `.git`, `bin`, and `obj` are inaccessible through agent tools.
5. `project.godot` may be read but must not be deleted by Phase 1 tools.
6. File sizes are bounded to prevent accidental memory exhaustion.
7. Operations return controlled errors instead of raw tracebacks.
8. Mutations happen only after confirmation.
9. Existing functionality in the analyzer, Gemini provider, router, and CLI must remain intact.

## Agent Integration

Phase 1 should expose tool definitions in a provider-neutral form so Gemini integration can consume them without embedding filesystem logic into the Gemini provider. The initial integration can use a structured tool request/result protocol and a bounded tool-call loop. The loop must stop after a configured maximum number of tool calls and must never bypass mutation confirmation.

The user-facing CLI remains:

```bash
cd /path/to/MyGame
rbxforge "Fix my player movement"
```

The existing project auto-detection remains the source of the project root.

## Testing

Tests must cover:

- listing and deterministic ordering
- reading bounded text
- code search with line numbers
- missing/invalid paths
- `..` traversal rejection
- symlink escape rejection
- ignored-directory rejection
- create approval and denial
- write approval and denial
- backup creation before overwrite
- delete approval and denial
- protected `project.godot`
- tool errors are controlled
- existing CLI/analyzer tests continue to pass

No live Gemini API call is required for the Phase 1 unit suite.
