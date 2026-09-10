from pathlib import Path


def test_readme_describes_godot_mvp_and_cli():
    readme = Path('README.md').read_text(encoding='utf-8')
    assert 'Godot' in readme
    assert '--project' in readme
    assert 'Roblox' not in readme


def test_project_metadata_exists():
    pyproject = Path('pyproject.toml').read_text(encoding='utf-8')
    assert 'requires-python = ">=3.11"' in pyproject
    assert 'google-genai' in pyproject
