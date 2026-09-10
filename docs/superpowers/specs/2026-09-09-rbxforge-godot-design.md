# RBXForge Godot Development Layer Design

## Goal
Turn RBXForge from a Roblox-focused AI development tool into a Godot-focused AI development tool while preserving the provider-agnostic multi-LLM core.

## Scope
The first Godot MVP is file-based. It understands a Godot project directory, validates `project.godot`, discovers `.gd`, `.tscn`, and `.tres` files, extracts useful scene/script metadata, and produces compact project context for the AI router. A Godot Editor Plugin is explicitly deferred.

## Architecture
```text
User prompt
   |
   v
RBXForge Router -----> Ollama / Gemini
   |
   +---- GodotProjectAnalyzer
             |
             +-- project.godot
             +-- .gd scripts
             +-- .tscn scenes
             +-- .tres resources
```

The analyzer is independent of LLM providers. It returns typed project information and a bounded text context. This prevents provider code from needing to understand Godot file formats.

## Godot understanding
- `project.godot` is the project manifest and must be present at the project root.
- `.gd` files are treated as GDScript source files.
- `.tscn` files are treated as text scene files; the analyzer extracts node declarations, script references, and ext_resource paths without attempting to fully emulate the Godot parser.
- `.tres` files are treated as text resources; the analyzer records discovered resource/script references.
- Hidden directories and generated/build-heavy directories such as `.godot`, `.git`, `bin`, and `obj` are excluded from indexing.
- File size is bounded so a large asset cannot become accidental LLM context.

## Safety and error handling
- Project paths are normalized and resolved before reading.
- The analyzer refuses a path that is not a directory or lacks `project.godot`.
- Reads use UTF-8 with replacement for malformed bytes.
- Symlinks are not followed outside the project root.
- Missing or unreadable individual files are reported as skipped files instead of aborting the whole scan.
- AI providers keep their existing normalized error/fallback behavior.

## Testing
All analyzer tests use temporary directories and synthetic Godot text files. No Godot installation, Ollama server, or Gemini API key is required. Tests cover project discovery, scene metadata, script/resource references, ignored directories, context limits, and invalid projects.

## Future extension
A later Godot Editor Plugin can expose live Scene Tree/editor operations through a local bridge without changing the analyzer or LLM provider interfaces.
