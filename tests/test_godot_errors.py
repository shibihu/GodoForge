from rbxforge.godot.errors import GodotErrorParser


def test_parse_empty_output():
    errors = GodotErrorParser.parse("", "")
    assert errors == []


def test_parse_script_error():
    stderr = "SCRIPT ERROR: Parse Error: Identifier 'foo' not declared in res://player.gd:42:10"
    errors = GodotErrorParser.parse("", stderr)
    assert len(errors) == 1
    err = errors[0]
    assert err.file == "res://player.gd"
    assert err.line == 42
    assert err.column == 10
    assert err.severity == "error"


def test_parse_multiple_errors():
    stderr = (
        "ERROR: Node not found: res://main.tscn:15\n"
        "WARNING: Unused variable 'x' in res://utils.gd:5\n"
        "SCRIPT ERROR: Invalid call to method 'foo' in res://player.gd:99"
    )
    errors = GodotErrorParser.parse("", stderr)
    assert len(errors) == 3
    assert errors[0].file == "res://main.tscn"
    assert errors[0].line == 15

    assert errors[1].file == "res://utils.gd"
    assert errors[1].line == 5
    assert errors[1].severity == "warning"

    assert errors[2].file == "res://player.gd"
    assert errors[2].line == 99
    assert errors[2].severity == "error"
